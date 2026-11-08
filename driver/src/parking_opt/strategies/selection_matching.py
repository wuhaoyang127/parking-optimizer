"""Feasible matching, exposure, and arrival context for bounded selection."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from itertools import permutations

from parking_opt.domain.records import BufferAssignment, DecisionRequest
from parking_opt.strategies._selection import (
    _ArrivalCandidateContext,
    _locked_resources,
    _path,
    _position_claims,
)
from parking_opt.strategies.selection_context import (
    _busy_stack_groups,
    _entry_clear,
    _free_active_buffers,
    _legal_soft_departure_times,
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
        else tuple(buffers[item] for item in request.approved_config["active_buffer_position_ids"] if item in buffers)
    )
    if len(available) < len(blockers):
        return None
    limit = int(request.approved_config["max_buffer_matchings_per_departure"])
    best: tuple[tuple[float, float, tuple[str, ...]], tuple[BufferAssignment, ...]] | None = None
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
        score = (round_trip, maximum_leg, tuple(item.buffer_position_id for item in assignments))
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
            request, slots=slots, positions=positions, claims=claims, locked=locked
        ),
        soft_departure_times=_legal_soft_departure_times(request),
    )
