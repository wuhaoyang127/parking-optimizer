"""Sandbox state editing (confirm, close, remove)."""

from __future__ import annotations

from dataclasses import replace

from parking_opt.application.sandbox_types import SandboxDecision
from parking_opt.domain.enums import (
    ArrivalStatus,
    DepartureStatus,
    LocationKind,
    PositionKind,
    PrimaryDecision,
)
from parking_opt.domain.invariants import assert_state_invariants
from parking_opt.domain.records import LocationState
from parking_opt.domain.state import AuthoritativeState


def confirm_sandbox_decision(decision: SandboxDecision) -> AuthoritativeState:
    """Apply a successful sandbox recommendation as one confirmed final state."""

    result = decision.result
    state = decision.input_state
    target_id = result.target_anonymous_vehicle_id
    if result.primary_decision is not PrimaryDecision.RECOMMEND_ACTIONS:
        raise ValueError("only a recommended sandbox action can be confirmed")
    if decision.decision_kind == "ARRIVAL":
        destination = decision.selected_position_id
        if destination is None:
            raise ValueError("arrival decision has no selected destination")
        confirmed = replace(
            state,
            sequence_no=state.sequence_no + 1,
            vehicles=tuple(
                replace(
                    item,
                    location_state=LocationState(LocationKind.AT_POSITION, destination),
                    arrival_status=ArrivalStatus.ENTRY_COMPLETED,
                    ever_admitted=True,
                    admitted_at_s=state.sim_time_s,
                    waiting_since_s=None,
                )
                if item.anonymous_vehicle_id == target_id
                else item
                for item in state.vehicles
            ),
            positions=tuple(
                replace(item, occupant_vehicle_id=target_id) if item.position_id == destination else item
                for item in state.positions
            ),
            pending_requests=tuple(
                item for item in state.pending_requests if item.request_id != result.target_request_id
            ),
        )
    elif decision.decision_kind == "DEPARTURE":
        origin = next(
            item.location_state.position_id
            for item in state.vehicles
            if item.anonymous_vehicle_id == target_id
        )
        confirmed = replace(
            state,
            sequence_no=state.sequence_no + 1,
            vehicles=tuple(
                replace(
                    item,
                    location_state=LocationState(LocationKind.EXITED),
                    departure_status=DepartureStatus.COMPLETED,
                    waiting_since_s=None,
                )
                if item.anonymous_vehicle_id == target_id
                else item
                for item in state.vehicles
            ),
            positions=tuple(
                replace(item, occupant_vehicle_id=None) if item.position_id == origin else item
                for item in state.positions
            ),
            pending_requests=tuple(
                item for item in state.pending_requests if item.request_id != result.target_request_id
            ),
        )
    else:
        raise ValueError("unsupported sandbox decision kind")
    assert_state_invariants(confirmed)
    return confirmed


def set_position_closed(
    state: AuthoritativeState,
    position_id: str,
    *,
    closed: bool,
) -> AuthoritativeState:
    """Close or reopen an unoccupied normal sandbox position."""

    target = next((item for item in state.positions if item.position_id == position_id), None)
    if target is None or target.position_kind is not PositionKind.NORMAL:
        raise ValueError("only a known normal position can be edited")
    if closed and target.occupant_vehicle_id is not None:
        raise ValueError("an occupied position cannot be closed")
    result = replace(
        state,
        sequence_no=state.sequence_no + 1,
        positions=tuple(
            replace(item, physically_available=not closed, assignable=not closed, planned_closure=closed)
            if item.position_id == position_id
            else item
            for item in state.positions
        ),
    )
    assert_state_invariants(result)
    return result


def remove_parked_vehicle(
    state: AuthoritativeState, anonymous_vehicle_id: str
) -> AuthoritativeState:
    """Remove one parked synthetic vehicle from the editable sandbox."""

    vehicle = next(
        (
            item
            for item in state.vehicles
            if item.anonymous_vehicle_id == anonymous_vehicle_id
            and item.location_state.kind is LocationKind.AT_POSITION
        ),
        None,
    )
    if vehicle is None or vehicle.location_state.position_id is None:
        raise ValueError("only a parked sandbox vehicle can be removed")
    position_id = vehicle.location_state.position_id
    result = replace(
        state,
        sequence_no=state.sequence_no + 1,
        vehicles=tuple(item for item in state.vehicles if item.anonymous_vehicle_id != anonymous_vehicle_id),
        positions=tuple(
            replace(item, occupant_vehicle_id=None) if item.position_id == position_id else item
            for item in state.positions
        ),
        pending_requests=tuple(
            item for item in state.pending_requests if item.anonymous_vehicle_id != anonymous_vehicle_id
        ),
    )
    assert_state_invariants(result)
    return result
