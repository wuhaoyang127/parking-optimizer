"""Shared bounded selection logic for the online rule and minimal fallback."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from parking_opt.domain.enums import LocationKind, PrimaryDecision
from parking_opt.domain.records import DecisionRequest, PendingRequest

if TYPE_CHECKING:
    from parking_opt.domain.records import Action, RelocationTransaction


@dataclass(frozen=True, slots=True)
class Selection:
    """One primary policy selection before result-envelope decoration."""

    target: PendingRequest
    primary_decision: PrimaryDecision
    actions: tuple[Action, ...] = ()
    transaction: RelocationTransaction | None = None
    explanation_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BoundedSelectionSet:
    """Per-request options retained while enforcing C5 candidate bounds."""

    selections: tuple[Selection, ...]
    positions_seen: int = 0
    positions_kept: int = 0
    buffer_matchings_seen: int = 0
    buffer_matchings_kept: int = 0
    timed_out: bool = False


@dataclass(frozen=True, slots=True)
class ArrivalCandidateAssessment:
    """One arrival position assessed by the exact online-rule filters and ordering."""

    position_id: str
    stack_group_id: str
    depth: int
    feasible: bool
    reason_codes: tuple[str, ...]
    score: tuple[object, ...] | None
    distance_m: float | None
    incremental_unrecoverable_exposure: int | None
    incremental_blocked_vehicle_count: int | None
    remaining_one_step_assignable_capacity: int | None
    departure_order_mismatch_count: int | None
    slot: Mapping[str, Any]
    path: Mapping[str, Any] | None


@dataclass(frozen=True, slots=True)
class _ArrivalCandidateContext:
    slots: tuple[Mapping[str, Any], ...]
    positions: Mapping[str, Any]
    claims: Mapping[str, set[str]]
    locked: set[tuple[str, str]]
    busy_stack_groups: set[str]
    baseline_assignable_ids: set[str]
    soft_departure_times: Mapping[str, int]


def deterministic_target(request: DecisionRequest) -> PendingRequest | None:
    pending = request.observed_snapshot.pending_requests
    if request.trigger_event_type == "ARRIVAL_REQUESTED":
        return next((item for item in pending if item.request_id == request.trigger_request_id), None)
    return pending[0] if pending else None


def emergency_selection(request: DecisionRequest) -> Selection:
    """Precompute an O(1) failure-closed WAIT/REJECT/manual result."""

    target = deterministic_target(request)
    if target is None:
        target = PendingRequest(
            request_id=request.trigger_request_id or "no-pending-request",
            anonymous_vehicle_id=request.trigger_anonymous_vehicle_id or "no-pending-vehicle",
            request_type="ARRIVAL",
            requested_at_s=request.decision_time_s,
            event_sequence_no=1,
            entrance_node_id=None,
        )
    vehicles = {item.anonymous_vehicle_id: item for item in request.observed_snapshot.vehicles}
    vehicle = vehicles.get(target.anonymous_vehicle_id)
    if vehicle is not None and vehicle.location_state.kind is LocationKind.POSITION_UNCERTAIN:
        return Selection(
            target=target,
            primary_decision=PrimaryDecision.REQUEST_MANUAL_INTERVENTION,
            explanation_codes=("FAIL_CLOSED_RECONCILIATION_REQUIRED",),
        )
    if target.request_type == "ARRIVAL":
        config = request.approved_config
        waiting = sum(
            item.waiting_since_s is not None
            and item.location_state.kind is LocationKind.ENTRY_QUEUE
            for item in request.observed_snapshot.vehicles
        )
        already_waiting = vehicle is not None and vehicle.waiting_since_s is not None
        within_time = request.decision_time_s - target.requested_at_s < int(
            config["max_arrival_wait_s"]
        )
        capacity = already_waiting or waiting < int(config["arrival_wait_capacity"])
        if within_time and capacity:
            return Selection(
                target=target,
                primary_decision=PrimaryDecision.WAIT,
                explanation_codes=("FAIL_CLOSED_WAIT",),
            )
        return Selection(
            target=target,
            primary_decision=PrimaryDecision.REJECT,
            explanation_codes=("FAIL_CLOSED_NO_WAIT_CAPACITY_OR_TIME",),
        )
    return Selection(
        target=target,
        primary_decision=PrimaryDecision.WAIT,
        explanation_codes=("FAIL_CLOSED_WAIT",),
    )


def _path(
    layout: Mapping[str, Any],
    from_node_id: str,
    to_node_id: str,
) -> Mapping[str, Any] | None:
    candidates = [
        item
        for item in layout["path_costs"]
        if item["from_node_id"] == from_node_id and item["to_node_id"] == to_node_id
    ]
    return min(
        candidates,
        key=lambda item: (float(item["distance_m"]), int(item["travel_time_s"]), item["path_cost_id"]),
        default=None,
    )


def _position_claims(request: DecisionRequest) -> dict[str, set[str]]:
    claims = {
        item.position_id: ({item.occupant_vehicle_id} if item.occupant_vehicle_id else set())
        for item in request.observed_snapshot.positions
    }
    for reservation in request.observed_snapshot.reservations:
        claims[reservation.position_id].add(reservation.owner_vehicle_id)
    return claims


def _locked_resources(request: DecisionRequest) -> set[tuple[str, str]]:
    return {(item.resource_type, item.resource_id) for item in request.observed_snapshot.locks}


from parking_opt.strategies.selection_action import _action  # noqa: E402
from parking_opt.strategies.selection_arrival import (  # noqa: E402
    _bounded_arrival_candidates,
    _assess_arrival_slot,
    assess_arrival_candidates,
)
from parking_opt.strategies.selection_bounded import bounded_selections_for_target  # noqa: E402
from parking_opt.strategies.selection_choose import (  # noqa: E402
    _arrival_non_action_selection,
    _arrival_selection,
    _arrival_selection_from_candidate,
    _departure_selection,
    _service_key,
    select_decision,
)
from parking_opt.strategies.selection_context import (  # noqa: E402
    _busy_stack_groups,
    _departure_order_mismatches,
    _entry_clear,
    _free_active_buffers,
    _legal_soft_departure_times,
)
from parking_opt.strategies.selection_matching import (  # noqa: E402
    _arrival_candidate_context,
    _baseline_assignable_position_ids,
    _exposure_count,
    _feasible_matching,
    _projected_remaining_assignable_capacity,
)
