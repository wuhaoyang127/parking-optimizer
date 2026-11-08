"""Arrival candidate assessment for bounded selection."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from parking_opt.domain.records import DecisionRequest, PendingRequest
from parking_opt.strategies._selection import ArrivalCandidateAssessment, _path
from parking_opt.strategies.selection_context import _departure_order_mismatches, _entry_clear
from parking_opt.strategies.selection_matching import (
    _arrival_candidate_context,
    _exposure_count,
    _projected_remaining_assignable_capacity,
)


def _assess_arrival_slot(
    request: DecisionRequest,
    target: PendingRequest,
    slot: Mapping[str, object],
    *,
    context,
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
    if not _entry_clear(slot, slots=context.slots, claims=context.claims, locked=context.locked):
        reasons.append("ENTRY_NOT_CLEAR")
    path = _path(request.layout, target.entrance_node_id or "", str(slot["access_node_id"]))
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
    before = _exposure_count(request, str(slot["stack_group_id"]), None, None, deadline=deadline, clock=clock)
    after = _exposure_count(request, str(slot["stack_group_id"]), position_id, target.anonymous_vehicle_id, deadline=deadline, clock=clock)
    incremental_exposure = max(0, after - before)
    if str(request.approved_config["recoverability_policy"]) == "strict_recoverable" and incremental_exposure:
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
        slot, slots=context.slots, baseline_assignable_ids=context.baseline_assignable_ids
    )
    departure_mismatches = _departure_order_mismatches(
        request, target, slot, slots=context.slots, soft_departure_times=context.soft_departure_times
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
    context = _arrival_candidate_context(request)
    assessments: list[ArrivalCandidateAssessment] = []
    for slot in sorted(context.slots, key=lambda item: item["position_id"]):
        if clock() >= deadline:
            break
        assessments.append(
            _assess_arrival_slot(request, target, slot, context=context, deadline=deadline, clock=clock)
        )
    return tuple(assessments)


def _bounded_arrival_candidates(
    request: DecisionRequest,
    target: PendingRequest,
    *,
    limit: int,
    first_fit: bool,
    deadline: float,
    clock: Callable[[], float],
) -> tuple[tuple[tuple[tuple[object, ...], Mapping[str, object], Mapping[str, object]], ...], int, bool]:
    if limit < 1:
        raise ValueError("arrival candidate limit must be positive")
    context = _arrival_candidate_context(request)
    candidates: list[tuple[tuple[object, ...], Mapping[str, object], Mapping[str, object]]] = []
    seen = 0
    timed_out = False
    for slot in sorted(context.slots, key=lambda item: item["position_id"]):
        if clock() >= deadline:
            timed_out = True
            break
        assessment = _assess_arrival_slot(request, target, slot, context=context, deadline=deadline, clock=clock)
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
