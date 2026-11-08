"""Arrival, wait, assignment, and departure-request reduction."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from parking_opt.domain.conversion import (
    action_from_mapping,
    initial_vehicle_state,
    pending_request_from_mapping,
    reservation_from_mapping,
)
from parking_opt.domain.enums import (
    ActionStatus,
    ActionType,
    ArrivalStatus,
    DepartureStatus,
    LocationKind,
    PositionKind,
)
from parking_opt.domain.state import AuthoritativeState
from parking_opt.domain.transitions import _WorkingState, _require
from parking_opt.domain.transitions_helpers import (
    _active_claim_owners,
    _assert_action_path,
    _assert_entry_clear,
)
from parking_opt.domain.transitions_resources import _remove_pending_for_vehicle


def _apply_arrival(work: _WorkingState, event: Mapping[str, Any]) -> None:
    vehicle_id = event["anonymous_vehicle_id"]
    _require(vehicle_id not in work.vehicles, f"vehicle {vehicle_id} already exists")
    request = pending_request_from_mapping(event["payload"]["pending_request"])
    _require(request.anonymous_vehicle_id == vehicle_id, "arrival request vehicle mismatch")
    _require(request.requested_at_s == event["sim_time_s"], "arrival request time mismatch")
    _require(request.event_sequence_no == event["sequence_no"], "arrival request sequence mismatch")
    work.vehicles[vehicle_id] = initial_vehicle_state(vehicle_id)
    work.pending_requests[request.request_id] = request


def _apply_wait(work: _WorkingState, event: Mapping[str, Any]) -> None:
    vehicle_id = event["anonymous_vehicle_id"]
    vehicle = work.vehicles[vehicle_id]
    _require(
        vehicle.location_state.kind is LocationKind.ENTRY_QUEUE
        and vehicle.arrival_status in {ArrivalStatus.PENDING, ArrivalStatus.RECOMMENDED},
        "WAIT is legal only for an unadmitted arrival",
    )
    request_id = event["payload"]["request_id"]
    _require(request_id in work.pending_requests, "WAIT request does not exist")
    request = work.pending_requests[request_id]
    elapsed = event["sim_time_s"] - request.requested_at_s
    _require(elapsed < work.source.max_arrival_wait_s, "arrival wait deadline reached")
    waiting_count = sum(
        item.location_state.kind is LocationKind.ENTRY_QUEUE
        and item.arrival_status in {ArrivalStatus.PENDING, ArrivalStatus.RECOMMENDED}
        and item.waiting_since_s is not None
        for item in work.vehicles.values()
    )
    if vehicle.waiting_since_s is None:
        _require(waiting_count < work.source.arrival_wait_capacity, "arrival wait capacity exhausted")
    work.vehicles[vehicle_id] = replace(
        vehicle,
        arrival_status=ArrivalStatus.PENDING,
        waiting_since_s=vehicle.waiting_since_s if vehicle.waiting_since_s is not None else event["sim_time_s"],
    )


def _apply_assign_recommended(
    state: AuthoritativeState,
    work: _WorkingState,
    event: Mapping[str, Any],
) -> None:
    action = action_from_mapping(event["action"])
    _require(action.status is ActionStatus.RECOMMENDED, "assignment must be RECOMMENDED")
    _require(action.action_type is ActionType.ASSIGN, "event is not an assignment")
    _require(action.action_id not in work.actions, "assignment action already exists")
    vehicle = work.vehicles[action.anonymous_vehicle_id]
    _require(
        vehicle.location_state.kind is LocationKind.ENTRY_QUEUE
        and vehicle.arrival_status in {ArrivalStatus.PENDING, ArrivalStatus.RECOMMENDED},
        "assignment recommendation requires an unadmitted arrival",
    )
    destination = action.destination_position_id
    assert destination is not None
    position = work.positions[destination]
    _require(position.assignable and not position.planned_closure, "slot is not assignable")
    _require(position.physically_available, "slot is physically unavailable")
    _require(not _active_claim_owners(work, destination), "slot already has a capacity owner")
    _assert_entry_clear(state, work, destination)
    _assert_action_path(state, work, action)
    work.actions[action.action_id] = action
    work.vehicles[action.anonymous_vehicle_id] = replace(
        vehicle,
        arrival_status=ArrivalStatus.RECOMMENDED,
        action_context_id=action.action_id,
    )


def _apply_assignment_accepted(
    state: AuthoritativeState,
    work: _WorkingState,
    event: Mapping[str, Any],
) -> None:
    action = action_from_mapping(event["action"])
    _require(action.status is ActionStatus.ACCEPTED, "assignment must be ACCEPTED")
    from parking_opt.domain.transitions_helpers import _replace_action

    _replace_action(work, action, {ActionStatus.RECOMMENDED})
    vehicle = work.vehicles[action.anonymous_vehicle_id]
    _require(vehicle.arrival_status is ArrivalStatus.RECOMMENDED, "vehicle not recommended")
    records = event["payload"]["created_reservations"]
    _require(len(records) == 1, "assignment acceptance needs exactly one reservation")
    reservation = reservation_from_mapping(records[0])
    _require(
        reservation.owner_vehicle_id == action.anonymous_vehicle_id
        and reservation.position_id == action.destination_position_id
        and reservation.transaction_id is None
        and reservation.purpose == "admitted_assignment",
        "assignment reservation does not match the accepted action",
    )
    _require(reservation.reservation_id not in work.reservations, "duplicate reservation ID")
    destination = reservation.position_id
    position = work.positions[destination]
    _require(
        position.physically_available and position.assignable and not position.planned_closure,
        "accepted assignment destination is no longer assignable",
    )
    _require(not _active_claim_owners(work, destination), "assignment destination acquired another owner")
    _assert_entry_clear(state, work, destination)
    _assert_action_path(state, work, action)
    work.reservations[reservation.reservation_id] = reservation
    work.vehicles[action.anonymous_vehicle_id] = replace(
        vehicle,
        arrival_status=ArrivalStatus.ADMITTED,
        ever_admitted=True,
        admitted_at_s=vehicle.admitted_at_s if vehicle.admitted_at_s is not None else event["sim_time_s"],
        waiting_since_s=None,
        action_context_id=action.action_id,
    )
    _remove_pending_for_vehicle(work, action.anonymous_vehicle_id, "ARRIVAL")


def _apply_departure_requested(work: _WorkingState, event: Mapping[str, Any]) -> None:
    vehicle_id = event["anonymous_vehicle_id"]
    vehicle = work.vehicles[vehicle_id]
    location = vehicle.location_state
    _require(location.kind is LocationKind.AT_POSITION, "departure requires a parked vehicle")
    assert location.position_id is not None
    _require(
        work.positions[location.position_id].position_kind is PositionKind.NORMAL,
        "normal departure cannot be requested from a buffer",
    )
    _require(
        vehicle.departure_status in {DepartureStatus.NONE, DepartureStatus.PENDING},
        "departure already in service or completed",
    )
    request = pending_request_from_mapping(event["payload"]["pending_request"])
    _require(request.anonymous_vehicle_id == vehicle_id, "departure request vehicle mismatch")
    _require(request.request_type == "DEPARTURE", "wrong departure request type")
    work.vehicles[vehicle_id] = replace(vehicle, departure_status=DepartureStatus.PENDING)
    work.pending_requests[request.request_id] = request
