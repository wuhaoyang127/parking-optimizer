"""Action recommendation, acceptance, start, and completion reduction."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from parking_opt.domain.conversion import action_from_mapping
from parking_opt.domain.enums import (
    ActionStatus,
    ActionType,
    ArrivalStatus,
    DepartureStatus,
    LocationKind,
    TransactionStatus,
)
from parking_opt.domain.records import Action
from parking_opt.domain.state import AuthoritativeState
from parking_opt.domain.transitions import _WorkingState, _require
from parking_opt.domain.transitions_helpers import (
    _assert_action_path,
    _assert_entry_clear,
    _replace_action,
    _shallower_occupants,
)
from parking_opt.domain.transitions_resources import (
    _acquire_resources,
    _assert_lock_access,
    _release_resources,
    _remove_pending_for_vehicle,
)


def _apply_action_recommended(
    state: AuthoritativeState,
    work: _WorkingState,
    event: Mapping[str, Any],
) -> None:
    action = action_from_mapping(event["action"])
    _require(action.status is ActionStatus.RECOMMENDED, "action must be RECOMMENDED")
    _require(action.action_type is not ActionType.ASSIGN, "ASSIGN uses its dedicated event")
    _require(action.action_id not in work.actions, "action already exists")
    vehicle = work.vehicles[action.anonymous_vehicle_id]
    _require(vehicle.departure_status is DepartureStatus.PENDING, "departure action requires a pending departure")
    if action.action_type is ActionType.DIRECT_EXIT:
        _require(
            vehicle.location_state.kind is LocationKind.AT_POSITION and vehicle.location_state.position_id == action.origin_position_id,
            "direct-exit origin does not match vehicle",
        )
        _require(not _shallower_occupants(state, work, action.origin_position_id or ""), "direct exit is blocked")
    else:
        _require(action.transaction_id in work.transactions, "relocation lacks transaction")
    _assert_action_path(state, work, action)
    work.actions[action.action_id] = action
    work.vehicles[action.anonymous_vehicle_id] = replace(vehicle, action_context_id=action.action_id)


def _apply_action_accepted(work: _WorkingState, event: Mapping[str, Any]) -> None:
    action = action_from_mapping(event["action"])
    _require(action.status is ActionStatus.ACCEPTED, "action must be ACCEPTED")
    _replace_action(work, action, {ActionStatus.RECOMMENDED})
    vehicle = work.vehicles[action.anonymous_vehicle_id]
    work.vehicles[action.anonymous_vehicle_id] = replace(vehicle, action_context_id=action.action_id)


def _apply_action_waiting(work: _WorkingState, event: Mapping[str, Any]) -> None:
    action = action_from_mapping(event["action"])
    _require(action.status is ActionStatus.WAITING_FOR_RESOURCES, "action must be WAITING_FOR_RESOURCES")
    _replace_action(work, action, {ActionStatus.ACCEPTED})


def _assert_predecessors_complete(work: _WorkingState, action: Action) -> None:
    if action.transaction_id is None:
        return
    transaction = work.transactions[action.transaction_id]
    predecessors = {item.before_action_id for item in transaction.precedence_edges if item.after_action_id == action.action_id}
    _require(all(work.actions[item].status is ActionStatus.COMPLETED for item in predecessors), f"action {action.action_id} predecessor is incomplete")


def _apply_action_started(
    state: AuthoritativeState,
    work: _WorkingState,
    event: Mapping[str, Any],
) -> None:
    action = action_from_mapping(event["action"])
    _require(action.status is ActionStatus.STARTED, "action must be STARTED")
    _replace_action(work, action, {ActionStatus.ACCEPTED, ActionStatus.WAITING_FOR_RESOURCES})
    _assert_predecessors_complete(work, action)
    _assert_lock_access(state, work, action)
    vehicle = work.vehicles[action.anonymous_vehicle_id]
    if action.action_type is ActionType.ASSIGN:
        _require(
            vehicle.location_state.kind is LocationKind.ENTRY_QUEUE and vehicle.arrival_status is ArrivalStatus.ADMITTED,
            "assignment start requires an admitted entry-queue vehicle",
        )
        destination = action.destination_position_id
        assert destination is not None
        _assert_entry_clear(state, work, destination)
    else:
        _require(
            vehicle.location_state.kind is LocationKind.AT_POSITION and vehicle.location_state.position_id == action.origin_position_id,
            "action origin does not match the parked vehicle",
        )
        origin = action.origin_position_id
        assert origin is not None
        work.positions[origin] = replace(work.positions[origin], occupant_vehicle_id=None)
        if action.action_type is ActionType.DIRECT_EXIT:
            _require(vehicle.departure_status is DepartureStatus.PENDING, "direct exit start requires pending departure")
            _require(not _shallower_occupants(state, work, origin), "direct exit is blocked")
    if action.destination_position_id is not None:
        _require(
            any(
                item.position_id == action.destination_position_id and item.owner_vehicle_id == action.anonymous_vehicle_id
                for item in work.reservations.values()
            ),
            "action destination lacks a vehicle-owned reservation",
        )
    _acquire_resources(work, action)
    work.vehicles[action.anonymous_vehicle_id] = replace(
        vehicle,
        location_state=replace(vehicle.location_state, kind=LocationKind.IN_TRANSIT, position_id=None, action_id=action.action_id),
        departure_status=DepartureStatus.IN_SERVICE if action.action_type is ActionType.DIRECT_EXIT else vehicle.departure_status,
        action_context_id=action.action_id,
    )


def _apply_action_completed(work: _WorkingState, event: Mapping[str, Any]) -> None:
    action = action_from_mapping(event["action"])
    _require(action.status is ActionStatus.COMPLETED, "action must be COMPLETED")
    _replace_action(work, action, {ActionStatus.STARTED})
    vehicle = work.vehicles[action.anonymous_vehicle_id]
    _require(
        vehicle.location_state.kind is LocationKind.IN_TRANSIT and vehicle.location_state.action_id == action.action_id,
        "completed action vehicle is not in its transit state",
    )
    _release_resources(work, action)
    if action.action_type is ActionType.DIRECT_EXIT:
        work.vehicles[action.anonymous_vehicle_id] = replace(
            vehicle,
            location_state=replace(vehicle.location_state, kind=LocationKind.EXITED, position_id=None, action_id=None),
            departure_status=DepartureStatus.COMPLETED,
            action_context_id=None,
        )
        _remove_pending_for_vehicle(work, action.anonymous_vehicle_id, "DEPARTURE")
        return
    destination = action.destination_position_id
    assert destination is not None
    _require(work.positions[destination].occupant_vehicle_id is None, "completed destination is occupied")
    work.positions[destination] = replace(work.positions[destination], occupant_vehicle_id=action.anonymous_vehicle_id)
    work.vehicles[action.anonymous_vehicle_id] = replace(
        vehicle,
        location_state=replace(vehicle.location_state, kind=LocationKind.AT_POSITION, position_id=destination, action_id=None),
        arrival_status=ArrivalStatus.ENTRY_COMPLETED if action.action_type is ActionType.ASSIGN else vehicle.arrival_status,
        action_context_id=None,
    )
    if action.action_type is ActionType.ASSIGN:
        work.reservations = {
            key: item
            for key, item in work.reservations.items()
            if not (
                item.owner_vehicle_id == action.anonymous_vehicle_id
                and item.position_id == destination
                and item.purpose == "admitted_assignment"
            )
        }


def _fail_transaction_if_needed(work: _WorkingState, action: Action) -> None:
    if action.transaction_id is None:
        return
    transaction = work.transactions[action.transaction_id]
    work.transactions[action.transaction_id] = replace(transaction, status=TransactionStatus.FAILED_MANUAL_PENDING)
