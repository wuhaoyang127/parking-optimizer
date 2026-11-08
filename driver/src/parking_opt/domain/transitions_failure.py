"""Failure, reconciliation, and transaction-stage reduction."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from parking_opt.domain.conversion import (
    action_from_mapping,
    location_from_mapping,
    transaction_from_mapping,
)
from parking_opt.domain.enums import (
    ActionStatus,
    ActionType,
    DepartureStatus,
    LocationKind,
    PositionConfirmation,
    TransactionStatus,
)
from parking_opt.domain.transitions import StateTransitionError, _WorkingState, _require
from parking_opt.domain.transitions_action import _fail_transaction_if_needed
from parking_opt.domain.transitions_helpers import _replace_action
from parking_opt.domain.transitions_resources import (
    _release_resources,
    _release_transaction_protection,
)


def _apply_action_failed_known(work: _WorkingState, event: Mapping[str, Any]) -> None:
    action = action_from_mapping(event["action"])
    _require(
        action.status is ActionStatus.FAILED and action.position_confirmation is not PositionConfirmation.UNKNOWN,
        "known-position failure must be FAILED with a known confirmation",
    )
    _replace_action(work, action, {ActionStatus.STARTED})
    vehicle = work.vehicles[action.anonymous_vehicle_id]
    location = location_from_mapping(event["payload"]["confirmed_location_state"])
    _require(location.kind is LocationKind.AT_POSITION, "known failure needs AT_POSITION")
    position_id = location.position_id
    assert position_id is not None
    if action.position_confirmation is PositionConfirmation.AT_ORIGIN:
        _require(position_id == action.origin_position_id, "AT_ORIGIN confirmation mismatch")
    elif action.position_confirmation is PositionConfirmation.AT_DESTINATION:
        _require(position_id == action.destination_position_id, "AT_DESTINATION confirmation mismatch")
    elif action.position_confirmation is PositionConfirmation.AT_OTHER_POSITION:
        _require(
            position_id not in {action.origin_position_id, action.destination_position_id},
            "AT_OTHER_POSITION must identify a third modeled position",
        )
    _require(
        work.positions[position_id].occupant_vehicle_id in {None, action.anonymous_vehicle_id},
        "confirmed failure position has another occupant",
    )
    _release_resources(work, action)
    work.positions[position_id] = replace(work.positions[position_id], occupant_vehicle_id=action.anonymous_vehicle_id)
    work.vehicles[action.anonymous_vehicle_id] = replace(vehicle, location_state=location, action_context_id=action.action_id)
    _fail_transaction_if_needed(work, action)


def _apply_action_failed_unknown(work: _WorkingState, event: Mapping[str, Any]) -> None:
    action = action_from_mapping(event["action"])
    _require(
        action.status is ActionStatus.FAILED and action.position_confirmation is PositionConfirmation.UNKNOWN,
        "unknown-position failure must be FAILED/UNKNOWN",
    )
    _replace_action(work, action, {ActionStatus.STARTED})
    vehicle = work.vehicles[action.anonymous_vehicle_id]
    _release_resources(work, action)
    work.vehicles[action.anonymous_vehicle_id] = replace(
        vehicle,
        location_state=replace(vehicle.location_state, kind=LocationKind.POSITION_UNCERTAIN, position_id=None, action_id=action.action_id),
        action_context_id=action.action_id,
    )
    _fail_transaction_if_needed(work, action)


def _apply_aborted(work: _WorkingState, event: Mapping[str, Any]) -> None:
    action = action_from_mapping(event["action"])
    _require(action.status is ActionStatus.ABORTED, "action must be ABORTED")
    _replace_action(
        work,
        action,
        {ActionStatus.RECOMMENDED, ActionStatus.ACCEPTED, ActionStatus.WAITING_FOR_RESOURCES},
    )
    _require(action.started_at_s is None, "before-start abort cannot have started_at_s")


def _apply_position_reconciled(work: _WorkingState, event: Mapping[str, Any]) -> None:
    vehicle_id = event["anonymous_vehicle_id"]
    vehicle = work.vehicles[vehicle_id]
    _require(vehicle.location_state.kind is LocationKind.POSITION_UNCERTAIN, "vehicle position is not uncertain")
    location = location_from_mapping(event["payload"]["confirmed_location_state"])
    _require(location.kind in {LocationKind.AT_POSITION, LocationKind.EXITED}, "reconciliation must confirm a position or real exit")
    if location.kind is LocationKind.AT_POSITION:
        position_id = location.position_id
        assert position_id is not None
        _require(work.positions[position_id].occupant_vehicle_id in {None, vehicle_id}, "reconciled position has another occupant")
        work.positions[position_id] = replace(work.positions[position_id], occupant_vehicle_id=vehicle_id)
    work.vehicles[vehicle_id] = replace(
        vehicle,
        location_state=location,
        action_context_id=None,
        departure_status=DepartureStatus.COMPLETED if location.kind is LocationKind.EXITED else vehicle.departure_status,
    )


def _apply_transaction_stage(work: _WorkingState, event: Mapping[str, Any]) -> None:
    incoming = transaction_from_mapping(event["transaction"])
    current = work.transactions[incoming.transaction_id]
    _require(incoming.transaction_id == event["transaction_id"], "transaction stage envelope mismatch")
    actions = [work.actions[action_id] for action_id in current.action_ids]
    legal_next: TransactionStatus
    if current.status is TransactionStatus.RESERVED:
        legal_next = TransactionStatus.MOVING_BLOCKERS_OUT
    elif current.status is TransactionStatus.MOVING_BLOCKERS_OUT:
        relocation_actions = [item for item in actions if item.action_type is ActionType.RELOCATE_TO_BUFFER]
        _require(all(item.status is ActionStatus.COMPLETED for item in relocation_actions), "not all blockers have reached buffers")
        legal_next = TransactionStatus.TARGET_EXITING
    elif current.status is TransactionStatus.TARGET_EXITING:
        target_exit = next(item for item in actions if item.action_type is ActionType.DIRECT_EXIT)
        _require(target_exit.status is ActionStatus.COMPLETED, "target exit has not completed")
        legal_next = TransactionStatus.RESTORING_ORIGINALS
    elif current.status is TransactionStatus.RESTORING_ORIGINALS:
        restore_actions = [item for item in actions if item.action_type is ActionType.RESTORE_ORIGINAL]
        _require(all(item.status is ActionStatus.COMPLETED for item in restore_actions), "not all blockers have returned to original positions")
        legal_next = TransactionStatus.COMPLETED
    else:
        raise StateTransitionError(f"transaction {current.transaction_id} cannot advance")
    _require(incoming.status is legal_next, "transaction advanced to the wrong stage")
    _require(replace(incoming, status=current.status, ended_at_s=current.ended_at_s) == current, "transaction immutable fields changed during stage advance")
    work.transactions[incoming.transaction_id] = incoming
    if legal_next is TransactionStatus.COMPLETED:
        _require(not any(item.status is ActionStatus.STARTED for item in actions), "cannot release a transaction with a started action")
        _release_transaction_protection(work, incoming.transaction_id)


def _apply_transaction_cancelled(work: _WorkingState, event: Mapping[str, Any]) -> None:
    incoming = transaction_from_mapping(event["transaction"])
    current = work.transactions[incoming.transaction_id]
    _require(current.status is TransactionStatus.RESERVED, "transaction is not cancellable")
    _require(incoming.status is TransactionStatus.CANCELLED, "transaction is not CANCELLED")
    _require(replace(incoming, status=current.status, ended_at_s=current.ended_at_s) == current, "transaction immutable fields changed during cancellation")
    _require(
        not any(
            work.actions[action_id].status in {ActionStatus.STARTED, ActionStatus.COMPLETED, ActionStatus.FAILED}
            for action_id in current.action_ids
        ),
        "transaction execution has already started",
    )
    work.transactions[incoming.transaction_id] = incoming
    _release_transaction_protection(work, incoming.transaction_id)


def _apply_transaction_reconciled(work: _WorkingState, event: Mapping[str, Any]) -> None:
    incoming = transaction_from_mapping(event["transaction"])
    current = work.transactions[incoming.transaction_id]
    _require(current.status is TransactionStatus.FAILED_MANUAL_PENDING, "transaction is not awaiting failure reconciliation")
    _require(incoming.status is TransactionStatus.FAILED_RESOLVED, "transaction did not enter FAILED_RESOLVED")
    _require(replace(incoming, status=current.status, ended_at_s=current.ended_at_s) == current, "transaction immutable fields changed during reconciliation")
    affected = (current.target_vehicle_id, *current.blocker_vehicle_ids)
    _require(
        all(work.vehicles[item].location_state.kind is not LocationKind.POSITION_UNCERTAIN for item in affected),
        "transaction still contains an uncertain vehicle",
    )
    _require(not any(work.actions[action_id].status is ActionStatus.STARTED for action_id in current.action_ids), "transaction still has a started action")
    work.transactions[incoming.transaction_id] = incoming
    _release_transaction_protection(work, incoming.transaction_id)
