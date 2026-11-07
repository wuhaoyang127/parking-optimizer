"""Shared bounded selection logic for the online rule and minimal fallback."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from itertools import pairwise, permutations
from typing import Any

from parking_opt.domain.enums import (
    ActionStatus,
    ActionType,
    ExecutorType,
    LocationKind,
    ManualStatus,
    PrimaryDecision,
    TransactionStatus,
)
from parking_opt.domain.records import (
    Action,
    BufferAssignment,
    DecisionRequest,
    PendingRequest,
    PrecedenceEdge,
    RelocationTransaction,
)


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
    """Choose the mandatory arrival closure target or canonical first pending item."""

    pending = request.observed_snapshot.pending_requests
    if request.trigger_event_type == "ARRIVAL_REQUESTED":
        return next(
            (item for item in pending if item.request_id == request.trigger_request_id),
            None,
        )
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
        key=lambda item: (
            float(item["distance_m"]),
            int(item["travel_time_s"]),
            item["path_cost_id"],
        ),
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


def _busy_stack_groups(request: DecisionRequest) -> set[str]:
    group_by_position = {
        item["position_id"]: item["stack_group_id"] for item in request.layout["slots"]
    }
    groups: set[str] = set()
    for action in request.observed_snapshot.actions:
        if action.status not in {
            ActionStatus.RECOMMENDED,
            ActionStatus.ACCEPTED,
            ActionStatus.WAITING_FOR_RESOURCES,
            ActionStatus.STARTED,
        }:
            continue
        if action.action_type is ActionType.ASSIGN:
            position_id = action.destination_position_id
        elif action.action_type is ActionType.DIRECT_EXIT:
            position_id = action.origin_position_id
        else:
            continue
        if position_id in group_by_position:
            groups.add(group_by_position[position_id])
    return groups


def _legal_soft_departure_times(request: DecisionRequest) -> dict[str, int]:
    """Return only bounded, decision-time-visible soft departure values."""

    if not bool(request.approved_config["use_soft_departure_information"]):
        return {}
    records: list[tuple[int, str, str, int]] = []
    for vehicle in request.observed_snapshot.vehicles:
        information = vehicle.departure_information
        if (
            information.expected_departure_time_s is not None
            and information.known_at_time_s <= request.decision_time_s
            and information.source.value in {"reservation", "user_estimate", "model_prediction"}
        ):
            records.append(
                (
                    information.known_at_time_s,
                    information.source_record_id
                    or f"{vehicle.anonymous_vehicle_id}-{information.source.value}",
                    vehicle.anonymous_vehicle_id,
                    information.expected_departure_time_s,
                )
            )
    records.sort()
    limit = int(request.approved_config["max_soft_future_records"])
    return {vehicle_id: expected for _, _, vehicle_id, expected in records[:limit]}


def _departure_order_mismatches(
    request: DecisionRequest,
    target: PendingRequest,
    candidate_slot: Mapping[str, Any],
    *,
    slots: tuple[Mapping[str, Any], ...],
    soft_departure_times: Mapping[str, int],
) -> int:
    """Count soft ordering discordance; missing/equal values are neutral."""

    target_expected = soft_departure_times.get(target.anonymous_vehicle_id)
    if target_expected is None:
        return 0
    depth_by_position = {item["position_id"]: int(item["depth"]) for item in slots}
    occupant_by_position = {
        item.position_id: item.occupant_vehicle_id
        for item in request.observed_snapshot.positions
        if item.occupant_vehicle_id is not None
    }
    candidate_depth = int(candidate_slot["depth"])
    mismatch_count = 0
    for position_id, other_vehicle_id in occupant_by_position.items():
        other_slot = next(
            (
                item
                for item in slots
                if item["position_id"] == position_id
                and item["stack_group_id"] == candidate_slot["stack_group_id"]
            ),
            None,
        )
        if other_slot is None:
            continue
        other_expected = soft_departure_times.get(other_vehicle_id)
        if other_expected is None:
            continue
        if (candidate_depth - depth_by_position[position_id]) * (
            target_expected - other_expected
        ) < 0:
            mismatch_count += 1
    return mismatch_count


def _entry_clear(
    slot: Mapping[str, Any],
    *,
    slots: tuple[Mapping[str, Any], ...],
    claims: Mapping[str, set[str]],
    locked: set[tuple[str, str]],
) -> bool:
    if ("stack_group", slot["stack_group_id"]) in locked:
        return False
    for other in slots:
        if (
            other["stack_group_id"] == slot["stack_group_id"]
            and int(other["depth"]) < int(slot["depth"])
            and (claims[other["position_id"]] or ("position", other["position_id"]) in locked)
        ):
            return False
    return ("position", slot["position_id"]) not in locked


def _free_active_buffers(
    request: DecisionRequest,
    buffer_by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    positions = {item.position_id: item for item in request.observed_snapshot.positions}
    claims = _position_claims(request)
    locked = _locked_resources(request)
    return tuple(
        buffer_by_id[buffer_id]
        for buffer_id in request.approved_config["active_buffer_position_ids"]
        if buffer_id in buffer_by_id
        and positions[buffer_id].physically_available
        and not claims[buffer_id]
        and ("position", buffer_id) not in locked
    )


def _feasible_matching(
    request: DecisionRequest,
    blockers: tuple[tuple[str, Mapping[str, Any]], ...],
    *,
    require_currently_free: bool,
    first_fit: bool,
    deadline: float,
    clock: Callable[[], float],
) -> tuple[tuple[BufferAssignment, ...], float, float] | None:
    layout = request.layout
    buffers = {item["position_id"]: item for item in layout["buffer_slots"]}
    available = (
        _free_active_buffers(request, buffers)
        if require_currently_free
        else tuple(
            buffers[item]
            for item in request.approved_config["active_buffer_position_ids"]
            if item in buffers
        )
    )
    if len(available) < len(blockers):
        return None
    limit = int(request.approved_config["max_buffer_matchings_per_departure"])
    best: (
        tuple[
            tuple[float, float, tuple[str, ...]],
            tuple[BufferAssignment, ...],
        ]
        | None
    ) = None
    seen = 0
    for selected in permutations(available, len(blockers)):
        if clock() >= deadline or seen >= limit:
            break
        seen += 1
        assignments: list[BufferAssignment] = []
        round_trip = 0.0
        maximum_leg = 0.0
        feasible = True
        for (vehicle_id, origin), buffer in zip(blockers, selected, strict=True):
            outbound = _path(layout, origin["access_node_id"], buffer["access_node_id"])
            restore = _path(layout, buffer["access_node_id"], origin["access_node_id"])
            if outbound is None or restore is None:
                feasible = False
                break
            outbound_m = float(outbound["distance_m"])
            restore_m = float(restore["distance_m"])
            round_trip += outbound_m + restore_m
            maximum_leg = max(maximum_leg, outbound_m, restore_m)
            assignments.append(
                BufferAssignment(
                    blocker_vehicle_id=vehicle_id,
                    original_position_id=origin["position_id"],
                    buffer_position_id=buffer["position_id"],
                )
            )
        if not feasible:
            continue
        score = (
            round_trip,
            maximum_leg,
            tuple(item.buffer_position_id for item in assignments),
        )
        candidate = (score, tuple(assignments))
        if first_fit:
            return candidate[1], score[0], score[1]
        if best is None or candidate[0] < best[0]:
            best = candidate
    if best is None:
        return None
    return best[1], best[0][0], best[0][1]


def _exposure_count(
    request: DecisionRequest,
    group_id: str,
    projected_position_id: str | None,
    projected_vehicle_id: str | None,
    *,
    deadline: float,
    clock: Callable[[], float],
) -> int:
    slots = tuple(item for item in request.layout["slots"] if item["stack_group_id"] == group_id)
    occupant_by_position = {
        item.position_id: item.occupant_vehicle_id
        for item in request.observed_snapshot.positions
        if item.occupant_vehicle_id is not None
    }
    if projected_position_id is not None and projected_vehicle_id is not None:
        occupant_by_position[projected_position_id] = projected_vehicle_id
    occupied = tuple(
        (occupant_by_position[item["position_id"]], item)
        for item in slots
        if item["position_id"] in occupant_by_position
    )
    exposure = 0
    for _, target_slot in occupied:
        blockers = tuple(
            (vehicle_id, slot)
            for vehicle_id, slot in occupied
            if int(slot["depth"]) < int(target_slot["depth"])
        )
        if not blockers:
            continue
        if (
            _feasible_matching(
                request,
                tuple(sorted(blockers, key=lambda item: int(item[1]["depth"]))),
                require_currently_free=True,
                first_fit=True,
                deadline=deadline,
                clock=clock,
            )
            is None
        ):
            exposure += 1
    return exposure


def _baseline_assignable_position_ids(
    request: DecisionRequest,
    *,
    slots: tuple[Mapping[str, Any], ...],
    positions: Mapping[str, Any],
    claims: Mapping[str, set[str]],
    locked: set[tuple[str, str]],
) -> set[str]:
    return {
        item["position_id"]
        for item in slots
        if not claims[item["position_id"]]
        and positions[item["position_id"]].physically_available
        and positions[item["position_id"]].assignable
        and not positions[item["position_id"]].planned_closure
        and _entry_clear(item, slots=slots, claims=claims, locked=locked)
    }


def _projected_remaining_assignable_capacity(
    slot: Mapping[str, Any],
    *,
    slots: tuple[Mapping[str, Any], ...],
    baseline_assignable_ids: set[str],
) -> int:
    newly_blocked = sum(
        1
        for other in slots
        if other["position_id"] in baseline_assignable_ids
        and other["stack_group_id"] == slot["stack_group_id"]
        and int(other["depth"]) > int(slot["depth"])
    )
    return len(baseline_assignable_ids) - 1 - newly_blocked


def _arrival_candidate_context(request: DecisionRequest) -> _ArrivalCandidateContext:
    slots = tuple(request.layout["slots"])
    positions = {item.position_id: item for item in request.observed_snapshot.positions}
    claims = _position_claims(request)
    locked = _locked_resources(request)
    return _ArrivalCandidateContext(
        slots=slots,
        positions=positions,
        claims=claims,
        locked=locked,
        busy_stack_groups=_busy_stack_groups(request),
        baseline_assignable_ids=_baseline_assignable_position_ids(
            request,
            slots=slots,
            positions=positions,
            claims=claims,
            locked=locked,
        ),
        soft_departure_times=_legal_soft_departure_times(request),
    )


def _assess_arrival_slot(
    request: DecisionRequest,
    target: PendingRequest,
    slot: Mapping[str, Any],
    *,
    context: _ArrivalCandidateContext,
    deadline: float,
    clock: Callable[[], float],
) -> ArrivalCandidateAssessment:
    position_id = str(slot["position_id"])
    state = context.positions[position_id]
    reasons: list[str] = []
    if not state.physically_available:
        reasons.append("POSITION_PHYSICALLY_UNAVAILABLE")
    if not state.assignable:
        reasons.append("POSITION_NOT_ASSIGNABLE")
    if state.planned_closure:
        reasons.append("POSITION_PLANNED_CLOSURE")
    if context.claims[position_id]:
        reasons.append("POSITION_OCCUPIED_OR_RESERVED")
    if slot["stack_group_id"] in context.busy_stack_groups:
        reasons.append("STACK_GROUP_BUSY")
    if not _entry_clear(
        slot,
        slots=context.slots,
        claims=context.claims,
        locked=context.locked,
    ):
        reasons.append("ENTRY_NOT_CLEAR")
    path = _path(request.layout, target.entrance_node_id or "", slot["access_node_id"])
    if path is None:
        reasons.append("ENTRY_PATH_UNREACHABLE")
    if reasons:
        return ArrivalCandidateAssessment(
            position_id=position_id,
            stack_group_id=str(slot["stack_group_id"]),
            depth=int(slot["depth"]),
            feasible=False,
            reason_codes=tuple(dict.fromkeys(reasons)),
            score=None,
            distance_m=None if path is None else float(path["distance_m"]),
            incremental_unrecoverable_exposure=None,
            incremental_blocked_vehicle_count=None,
            remaining_one_step_assignable_capacity=None,
            departure_order_mismatch_count=None,
            slot=slot,
            path=path,
        )
    assert path is not None

    before = _exposure_count(
        request,
        str(slot["stack_group_id"]),
        None,
        None,
        deadline=deadline,
        clock=clock,
    )
    after = _exposure_count(
        request,
        str(slot["stack_group_id"]),
        position_id,
        target.anonymous_vehicle_id,
        deadline=deadline,
        clock=clock,
    )
    incremental_exposure = max(0, after - before)
    if (
        str(request.approved_config["recoverability_policy"]) == "strict_recoverable"
        and incremental_exposure
    ):
        return ArrivalCandidateAssessment(
            position_id=position_id,
            stack_group_id=str(slot["stack_group_id"]),
            depth=int(slot["depth"]),
            feasible=False,
            reason_codes=("UNRECOVERABLE_BLOCKING_EXPOSURE",),
            score=None,
            distance_m=float(path["distance_m"]),
            incremental_unrecoverable_exposure=incremental_exposure,
            incremental_blocked_vehicle_count=None,
            remaining_one_step_assignable_capacity=None,
            departure_order_mismatch_count=None,
            slot=slot,
            path=path,
        )
    incremental_blocked = sum(
        1
        for other in context.slots
        if other["stack_group_id"] == slot["stack_group_id"]
        and int(other["depth"]) > int(slot["depth"])
        and context.claims[str(other["position_id"])]
    )
    remaining_capacity = _projected_remaining_assignable_capacity(
        slot,
        slots=context.slots,
        baseline_assignable_ids=context.baseline_assignable_ids,
    )
    departure_mismatches = _departure_order_mismatches(
        request,
        target,
        slot,
        slots=context.slots,
        soft_departure_times=context.soft_departure_times,
    )
    score: tuple[object, ...] = (
        incremental_exposure,
        incremental_blocked,
        -remaining_capacity,
        float(path["distance_m"]),
        -int(slot["depth"]),
        departure_mismatches,
        slot["stack_group_id"],
        position_id,
    )
    return ArrivalCandidateAssessment(
        position_id=position_id,
        stack_group_id=str(slot["stack_group_id"]),
        depth=int(slot["depth"]),
        feasible=True,
        reason_codes=(),
        score=score,
        distance_m=float(path["distance_m"]),
        incremental_unrecoverable_exposure=incremental_exposure,
        incremental_blocked_vehicle_count=incremental_blocked,
        remaining_one_step_assignable_capacity=remaining_capacity,
        departure_order_mismatch_count=departure_mismatches,
        slot=slot,
        path=path,
    )


def assess_arrival_candidates(
    request: DecisionRequest,
    target: PendingRequest,
    *,
    deadline: float,
    clock: Callable[[], float],
) -> tuple[ArrivalCandidateAssessment, ...]:
    """Assess every position with the same filters and score used by the online rule."""

    context = _arrival_candidate_context(request)
    assessments: list[ArrivalCandidateAssessment] = []
    for slot in sorted(context.slots, key=lambda item: item["position_id"]):
        if clock() >= deadline:
            break
        assessments.append(
            _assess_arrival_slot(
                request,
                target,
                slot,
                context=context,
                deadline=deadline,
                clock=clock,
            )
        )
    return tuple(assessments)


def _action(
    *,
    request: DecisionRequest,
    action_id: str,
    vehicle_id: str,
    action_type: ActionType,
    path: Mapping[str, Any],
    origin_position_id: str | None,
    destination_position_id: str | None,
    destination_exit_id: str | None,
    transaction_id: str | None = None,
) -> Action:
    config = request.approved_config
    distance_m = float(path["distance_m"])
    if action_type in {ActionType.RELOCATE_TO_BUFFER, ActionType.RESTORE_ORIGINAL}:
        duration = math.ceil(
            float(config["relocation_setup_s"]) + distance_m / float(config["relocation_speed_mps"])
        )
        executor_units = 1
    else:
        duration = int(path["travel_time_s"])
        executor_units = 0
    return Action(
        action_id=action_id,
        transaction_id=transaction_id,
        anonymous_vehicle_id=vehicle_id,
        action_type=action_type,
        status=ActionStatus.RECOMMENDED,
        origin_position_id=origin_position_id,
        destination_position_id=destination_position_id,
        destination_exit_id=destination_exit_id,
        distance_m=distance_m,
        modeled_duration_s=duration,
        executor_type=ExecutorType(str(config["executor_type"])),
        executor_units=executor_units,
        channel_zone_ids=tuple(path["channel_zone_ids"]),
        reason="deterministic online C3 recommendation",
        recommended_at_s=request.decision_time_s,
    )


def _bounded_arrival_candidates(
    request: DecisionRequest,
    target: PendingRequest,
    *,
    limit: int,
    first_fit: bool,
    deadline: float,
    clock: Callable[[], float],
) -> tuple[
    tuple[tuple[tuple[object, ...], Mapping[str, Any], Mapping[str, Any]], ...],
    int,
    bool,
]:
    if limit < 1:
        raise ValueError("arrival candidate limit must be positive")
    context = _arrival_candidate_context(request)
    candidates: list[tuple[tuple[object, ...], Mapping[str, Any], Mapping[str, Any]]] = []
    seen = 0
    timed_out = False
    for slot in sorted(context.slots, key=lambda item: item["position_id"]):
        if clock() >= deadline:
            timed_out = True
            break
        assessment = _assess_arrival_slot(
            request,
            target,
            slot,
            context=context,
            deadline=deadline,
            clock=clock,
        )
        if not assessment.feasible:
            continue
        assert assessment.score is not None and assessment.path is not None
        score = assessment.score
        seen += 1
        candidates.append((score, assessment.slot, assessment.path))
        candidates.sort(key=lambda item: item[0])
        if len(candidates) > limit:
            candidates.pop()
        if first_fit:
            break
    return tuple(candidates), seen, timed_out


def _arrival_non_action_selection(
    request: DecisionRequest,
    target: PendingRequest,
) -> Selection:
    vehicle = next(
        item
        for item in request.observed_snapshot.vehicles
        if item.anonymous_vehicle_id == target.anonymous_vehicle_id
    )
    waiting = sum(
        item.waiting_since_s is not None and item.location_state.kind is LocationKind.ENTRY_QUEUE
        for item in request.observed_snapshot.vehicles
    )
    already_waiting = vehicle.waiting_since_s is not None
    within_time = request.decision_time_s - target.requested_at_s < int(
        request.approved_config["max_arrival_wait_s"]
    )
    capacity = already_waiting or waiting < int(request.approved_config["arrival_wait_capacity"])
    if within_time and capacity:
        return Selection(
            target=target,
            primary_decision=PrimaryDecision.WAIT,
            explanation_codes=("NO_FEASIBLE_POSITION",),
        )
    return Selection(
        target=target,
        primary_decision=PrimaryDecision.REJECT,
        explanation_codes=("NO_FEASIBLE_POSITION_OR_WAIT_CAPACITY",),
    )


def _arrival_selection_from_candidate(
    request: DecisionRequest,
    target: PendingRequest,
    candidate: tuple[tuple[object, ...], Mapping[str, Any], Mapping[str, Any]],
) -> Selection:
    _, slot, path = candidate
    action = _action(
        request=request,
        action_id=f"{request.request_id}-assign",
        vehicle_id=target.anonymous_vehicle_id,
        action_type=ActionType.ASSIGN,
        path=path,
        origin_position_id=None,
        destination_position_id=slot["position_id"],
        destination_exit_id=None,
    )
    return Selection(
        target=target,
        primary_decision=PrimaryDecision.RECOMMEND_ACTIONS,
        actions=(action,),
        explanation_codes=("ONLINE_ASSIGN_FEASIBLE",),
    )


def _arrival_selection(
    request: DecisionRequest,
    target: PendingRequest,
    *,
    first_fit: bool,
    deadline: float,
    clock: Callable[[], float],
) -> Selection:
    candidates, _, _ = _bounded_arrival_candidates(
        request,
        target,
        limit=1,
        first_fit=first_fit,
        deadline=deadline,
        clock=clock,
    )
    if candidates:
        return _arrival_selection_from_candidate(request, target, candidates[0])
    return _arrival_non_action_selection(request, target)


def bounded_selections_for_target(
    request: DecisionRequest,
    target: PendingRequest,
    *,
    deadline: float,
    clock: Callable[[], float],
) -> BoundedSelectionSet:
    """Generate only the configured number of visible per-request options."""

    if target.request_type == "ARRIVAL":
        limit = int(request.approved_config["max_positions_per_arrival"])
        candidates, seen, timed_out = _bounded_arrival_candidates(
            request,
            target,
            limit=limit,
            first_fit=False,
            deadline=deadline,
            clock=clock,
        )
        selections = tuple(
            _arrival_selection_from_candidate(request, target, candidate)
            for candidate in candidates
        )
        non_action = _arrival_non_action_selection(request, target)
        if non_action.primary_decision is not PrimaryDecision.REJECT:
            selections = (*selections, non_action)
        elif not selections:
            selections = (non_action,)
        return BoundedSelectionSet(
            selections=selections,
            positions_seen=seen,
            positions_kept=len(candidates),
            timed_out=timed_out,
        )

    selection = _departure_selection(
        request,
        target,
        first_fit=False,
        deadline=deadline,
        clock=clock,
    )
    matchings = int(selection.transaction is not None)
    return BoundedSelectionSet(
        selections=(selection,),
        buffer_matchings_seen=matchings,
        buffer_matchings_kept=matchings,
        timed_out=clock() >= deadline,
    )


def _departure_selection(
    request: DecisionRequest,
    target: PendingRequest,
    *,
    first_fit: bool,
    deadline: float,
    clock: Callable[[], float],
) -> Selection:
    vehicles = {item.anonymous_vehicle_id: item for item in request.observed_snapshot.vehicles}
    vehicle = vehicles[target.anonymous_vehicle_id]
    if vehicle.location_state.kind is LocationKind.POSITION_UNCERTAIN:
        return Selection(
            target=target,
            primary_decision=PrimaryDecision.REQUEST_MANUAL_INTERVENTION,
            explanation_codes=("POSITION_RECONCILIATION_REQUIRED",),
        )
    if vehicle.manual_status not in {ManualStatus.NONE, ManualStatus.FAILED}:
        return Selection(
            target=target,
            primary_decision=PrimaryDecision.WAIT,
            explanation_codes=("MANUAL_INTERVENTION_ALREADY_ACTIVE",),
        )
    if vehicle.active_transaction_id is not None:
        return Selection(
            target=target,
            primary_decision=PrimaryDecision.WAIT,
            explanation_codes=("ACTIVE_TRANSACTION_CONFIRMATION_PENDING",),
        )
    if any(
        item.anonymous_vehicle_id == target.anonymous_vehicle_id
        and item.status
        in {
            ActionStatus.RECOMMENDED,
            ActionStatus.ACCEPTED,
            ActionStatus.WAITING_FOR_RESOURCES,
            ActionStatus.STARTED,
        }
        for item in request.observed_snapshot.actions
    ):
        return Selection(
            target=target,
            primary_decision=PrimaryDecision.WAIT,
            explanation_codes=("ACTION_CONFIRMATION_PENDING",),
        )
    if vehicle.location_state.kind is not LocationKind.AT_POSITION:
        return Selection(
            target=target,
            primary_decision=PrimaryDecision.WAIT,
            explanation_codes=("DEPARTURE_POSITION_NOT_READY",),
        )
    origin_id = vehicle.location_state.position_id
    assert origin_id is not None
    slot_by_id = {item["position_id"]: item for item in request.layout["slots"]}
    origin = slot_by_id[origin_id]
    if origin["stack_group_id"] in _busy_stack_groups(request):
        return Selection(
            target=target,
            primary_decision=PrimaryDecision.WAIT,
            explanation_codes=("STACK_GROUP_MOVEMENT_PENDING",),
        )
    occupants = {
        item.position_id: item.occupant_vehicle_id
        for item in request.observed_snapshot.positions
        if item.occupant_vehicle_id is not None
    }
    blockers = tuple(
        (occupants[item["position_id"]], item)
        for item in request.layout["slots"]
        if item["stack_group_id"] == origin["stack_group_id"]
        and int(item["depth"]) < int(origin["depth"])
        and item["position_id"] in occupants
    )
    blockers = tuple(sorted(blockers, key=lambda item: int(item[1]["depth"])))
    exits = sorted(
        item["road_node_id"] for item in request.layout["road_nodes"] if item["node_kind"] == "exit"
    )
    if not blockers:
        paths = [
            path
            for exit_id in exits
            if (path := _path(request.layout, origin["access_node_id"], exit_id)) is not None
        ]
        if not paths:
            return Selection(
                target=target,
                primary_decision=PrimaryDecision.REQUEST_MANUAL_INTERVENTION,
                explanation_codes=("EXIT_PATH_UNREACHABLE",),
            )
        path = min(
            paths,
            key=lambda item: (
                float(item["distance_m"]),
                int(item["travel_time_s"]),
                item["to_node_id"],
            ),
        )
        action = _action(
            request=request,
            action_id=f"{request.request_id}-exit",
            vehicle_id=target.anonymous_vehicle_id,
            action_type=ActionType.DIRECT_EXIT,
            path=path,
            origin_position_id=origin_id,
            destination_position_id=None,
            destination_exit_id=path["to_node_id"],
        )
        return Selection(
            target=target,
            primary_decision=PrimaryDecision.RECOMMEND_ACTIONS,
            actions=(action,),
            explanation_codes=("ONLINE_DIRECT_EXIT",),
        )

    current = _feasible_matching(
        request,
        blockers,
        require_currently_free=True,
        first_fit=first_fit,
        deadline=deadline,
        clock=clock,
    )
    structural = _feasible_matching(
        request,
        blockers,
        require_currently_free=False,
        first_fit=True,
        deadline=deadline,
        clock=clock,
    )
    if current is None:
        if structural is None:
            return Selection(
                target=target,
                primary_decision=PrimaryDecision.REQUEST_MANUAL_INTERVENTION,
                explanation_codes=("BUFFER_MATCHING_OR_REACHABILITY_INFEASIBLE",),
            )
        if request.decision_time_s - target.requested_at_s >= int(
            request.approved_config["max_departure_wait_s"]
        ):
            return Selection(
                target=target,
                primary_decision=PrimaryDecision.REQUEST_MANUAL_INTERVENTION,
                explanation_codes=("DEPARTURE_SLA_VIOLATED",),
            )
        return Selection(
            target=target,
            primary_decision=PrimaryDecision.WAIT,
            explanation_codes=("TRANSIENT_BUFFER_CONFLICT",),
        )

    assignments, _, _ = current
    transaction_id = f"{request.request_id}-txn"
    actions: list[Action] = []
    for index, assignment in enumerate(assignments, start=1):
        blocker_slot = slot_by_id[assignment.original_position_id]
        buffer = next(
            item
            for item in request.layout["buffer_slots"]
            if item["position_id"] == assignment.buffer_position_id
        )
        path = _path(
            request.layout,
            blocker_slot["access_node_id"],
            buffer["access_node_id"],
        )
        assert path is not None
        actions.append(
            _action(
                request=request,
                action_id=f"{request.request_id}-txn-a{index:02d}",
                vehicle_id=assignment.blocker_vehicle_id,
                action_type=ActionType.RELOCATE_TO_BUFFER,
                path=path,
                origin_position_id=assignment.original_position_id,
                destination_position_id=assignment.buffer_position_id,
                destination_exit_id=None,
                transaction_id=transaction_id,
            )
        )
    exit_paths = [
        path
        for exit_id in exits
        if (path := _path(request.layout, origin["access_node_id"], exit_id)) is not None
    ]
    if not exit_paths:
        return Selection(
            target=target,
            primary_decision=PrimaryDecision.REQUEST_MANUAL_INTERVENTION,
            explanation_codes=("EXIT_PATH_UNREACHABLE",),
        )
    exit_path = min(
        exit_paths,
        key=lambda item: (
            float(item["distance_m"]),
            int(item["travel_time_s"]),
            item["to_node_id"],
        ),
    )
    actions.append(
        _action(
            request=request,
            action_id=f"{request.request_id}-txn-a{len(actions) + 1:02d}",
            vehicle_id=target.anonymous_vehicle_id,
            action_type=ActionType.DIRECT_EXIT,
            path=exit_path,
            origin_position_id=origin_id,
            destination_position_id=None,
            destination_exit_id=exit_path["to_node_id"],
            transaction_id=transaction_id,
        )
    )
    for assignment in reversed(assignments):
        blocker_slot = slot_by_id[assignment.original_position_id]
        buffer = next(
            item
            for item in request.layout["buffer_slots"]
            if item["position_id"] == assignment.buffer_position_id
        )
        path = _path(
            request.layout,
            buffer["access_node_id"],
            blocker_slot["access_node_id"],
        )
        assert path is not None
        actions.append(
            _action(
                request=request,
                action_id=f"{request.request_id}-txn-a{len(actions) + 1:02d}",
                vehicle_id=assignment.blocker_vehicle_id,
                action_type=ActionType.RESTORE_ORIGINAL,
                path=path,
                origin_position_id=assignment.buffer_position_id,
                destination_position_id=assignment.original_position_id,
                destination_exit_id=None,
                transaction_id=transaction_id,
            )
        )
    action_ids = tuple(item.action_id for item in actions)
    transaction = RelocationTransaction(
        transaction_id=transaction_id,
        target_vehicle_id=target.anonymous_vehicle_id,
        status=TransactionStatus.PROPOSED,
        blocker_vehicle_ids=tuple(item[0] for item in blockers),
        buffer_assignments=assignments,
        action_ids=action_ids,
        precedence_edges=tuple(
            PrecedenceEdge(before_action_id=left, after_action_id=right)
            for left, right in pairwise(action_ids)
        ),
        created_at_s=request.decision_time_s,
        ended_at_s=None,
    )
    return Selection(
        target=target,
        primary_decision=PrimaryDecision.RECOMMEND_ACTIONS,
        actions=tuple(actions),
        transaction=transaction,
        explanation_codes=("ONLINE_PASSIVE_RELOCATION_TRANSACTION",),
    )


def _service_key(request: DecisionRequest, item: PendingRequest) -> tuple[object, ...]:
    vehicle = next(
        value
        for value in request.observed_snapshot.vehicles
        if value.anonymous_vehicle_id == item.anonymous_vehicle_id
    )
    physical_rank = 2 if item.request_type == "DEPARTURE" else 4
    sla_violated = (
        item.request_type == "DEPARTURE"
        and request.decision_time_s - item.requested_at_s
        >= int(request.approved_config["max_departure_wait_s"])
    )
    immediately_executable = (
        item.request_type == "DEPARTURE" and vehicle.location_state.kind is LocationKind.AT_POSITION
    )
    return (
        physical_rank,
        0 if sla_violated else 1,
        item.requested_at_s,
        0 if immediately_executable else 1,
        item.event_sequence_no,
        item.anonymous_vehicle_id,
    )


def select_decision(
    request: DecisionRequest,
    *,
    first_fit: bool,
    deadline: float,
    clock: Callable[[], float],
) -> Selection | None:
    """Select one bounded deterministic action, WAIT, REJECT, or manual request."""

    mandatory = deterministic_target(request)
    pending = list(request.observed_snapshot.pending_requests)
    pending.sort(key=lambda item: _service_key(request, item))
    max_items = int(request.approved_config["max_requests_per_solve"])
    if mandatory is not None:
        ordered = [mandatory, *(item for item in pending if item != mandatory)]
    else:
        ordered = pending
    ordered = ordered[:max_items]
    first_wait: Selection | None = None
    for target in ordered:
        if clock() >= deadline:
            return None
        if target.request_type == "DEPARTURE":
            result = _departure_selection(
                request,
                target,
                first_fit=first_fit,
                deadline=deadline,
                clock=clock,
            )
        else:
            result = _arrival_selection(
                request,
                target,
                first_fit=first_fit,
                deadline=deadline,
                clock=clock,
            )
        if mandatory is not None and target == mandatory:
            return result
        if result.primary_decision is PrimaryDecision.WAIT:
            first_wait = first_wait or result
            continue
        return result
    return first_wait
