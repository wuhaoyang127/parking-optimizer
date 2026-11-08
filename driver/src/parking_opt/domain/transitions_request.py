"""Reject, cancel, manual, and information-update reduction."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from parking_opt.domain.conversion import departure_information_from_mapping
from parking_opt.domain.enums import (
    ActionStatus,
    ActionType,
    ArrivalStatus,
    LocationKind,
    ManualStatus,
    ReservationStatus,
)
from parking_opt.domain.transitions import _WorkingState, _require
from parking_opt.domain.transitions_resources import _remove_pending_for_vehicle


def _apply_reject(work: _WorkingState, event: Mapping[str, Any]) -> None:
    vehicle_id = event["anonymous_vehicle_id"]
    vehicle = work.vehicles[vehicle_id]
    _require(
        not vehicle.ever_admitted and vehicle.location_state.kind is LocationKind.ENTRY_QUEUE,
        "an admitted or non-queued vehicle cannot be rejected",
    )
    work.vehicles[vehicle_id] = replace(
        vehicle,
        location_state=replace(vehicle.location_state, kind=LocationKind.REJECTED, position_id=None, action_id=None),
        arrival_status=ArrivalStatus.REJECTED,
        waiting_since_s=None,
        action_context_id=None,
    )
    _remove_pending_for_vehicle(work, vehicle_id, "ARRIVAL")


def _apply_user_cancelled(work: _WorkingState, event: Mapping[str, Any]) -> None:
    vehicle_id = event["anonymous_vehicle_id"]
    vehicle = work.vehicles[vehicle_id]
    _require(
        vehicle.arrival_status in {ArrivalStatus.PENDING, ArrivalStatus.RECOMMENDED, ArrivalStatus.ADMITTED},
        "USER_CANCELLED requires a pending, incomplete arrival",
    )
    _require(vehicle.location_state.kind is LocationKind.ENTRY_QUEUE, "started movement must be reconciled before cancellation")
    for action_id, action in tuple(work.actions.items()):
        if (
            action.anonymous_vehicle_id == vehicle_id
            and action.action_type is ActionType.ASSIGN
            and action.status in {ActionStatus.RECOMMENDED, ActionStatus.ACCEPTED, ActionStatus.WAITING_FOR_RESOURCES}
        ):
            work.actions[action_id] = replace(action, status=ActionStatus.ABORTED, ended_at_s=event["sim_time_s"])
    work.reservations = {
        key: item
        for key, item in work.reservations.items()
        if not (item.owner_vehicle_id == vehicle_id and item.purpose == "admitted_assignment")
    }
    work.vehicles[vehicle_id] = replace(
        vehicle,
        location_state=replace(vehicle.location_state, kind=LocationKind.EXITED, position_id=None, action_id=None),
        arrival_status=ArrivalStatus.CANCELLED,
        waiting_since_s=None,
        action_context_id=None,
    )
    _remove_pending_for_vehicle(work, vehicle_id, "ARRIVAL")


def _apply_manual(work: _WorkingState, event: Mapping[str, Any]) -> None:
    vehicle_id = event["anonymous_vehicle_id"]
    vehicle = work.vehicles[vehicle_id]
    _require(
        vehicle.location_state.kind not in {LocationKind.EXITED, LocationKind.REJECTED},
        "manual intervention cannot target a terminal vehicle",
    )
    if event["event_type"] == "MANUAL_INTERVENTION_REQUESTED":
        status = ManualStatus.REQUESTED
        _require(vehicle.manual_status in {ManualStatus.NONE, ManualStatus.FAILED}, "manual intervention is already active")
    else:
        status = ManualStatus(event["payload"]["manual_status"])
        allowed = {
            ManualStatus.REQUESTED: {ManualStatus.ACKNOWLEDGED, ManualStatus.FAILED},
            ManualStatus.ACKNOWLEDGED: {ManualStatus.IN_PROGRESS, ManualStatus.FAILED},
            ManualStatus.IN_PROGRESS: {ManualStatus.COMPLETED, ManualStatus.FAILED},
        }
        _require(status in allowed.get(vehicle.manual_status, set()), "illegal manual status")
    work.vehicles[vehicle_id] = replace(vehicle, manual_status=status)


def _apply_information_updated(work: _WorkingState, event: Mapping[str, Any]) -> None:
    vehicle_id = event["anonymous_vehicle_id"]
    vehicle = work.vehicles[vehicle_id]
    information = departure_information_from_mapping(event["payload"]["departure_information"])
    _require(information.known_at_time_s <= event["sim_time_s"], "information update is not yet known")
    work.vehicles[vehicle_id] = replace(
        vehicle,
        reservation_status=ReservationStatus(event["payload"]["reservation_status"]),
        departure_information=information,
    )
