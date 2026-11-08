"""Build the bounded rolling input (warm start plus at most 64 plans)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from time import monotonic

from parking_opt.contracts.canonical import canonical_sha256
from parking_opt.domain.records import CandidateGenerationRecord, DecisionRequest
from parking_opt.optimization.rolling_objective import (
    _bounded_requests,
    _compatible_prefix,
    _safe_deferred_selection,
)
from parking_opt.optimization.rolling_plan import (
    _append_bounded_plan,
    _legal_soft_record_ids,
    _validate_configured_bounds,
    _window_plan,
    validate_window_plan,
)
from parking_opt.optimization.rolling_types import (
    BoundedRollingInput,
    WindowPlan,
    _selection_signature,
)
from parking_opt.strategies._selection import Selection, bounded_selections_for_target


def build_bounded_rolling_input(
    request: DecisionRequest,
    *,
    incumbent: Selection,
    modeling_deadline: float,
    clock: Callable[[], float] = monotonic,
) -> BoundedRollingInput:
    """Build warm start and at most 64 plans without materializing a product."""

    _validate_configured_bounds(request)
    retained, requests_seen = _bounded_requests(request)
    if not retained:
        raise ValueError("rolling input requires at least one pending request")
    if incumbent.target.request_id not in {item.request_id for item in retained}:
        raise ValueError("online incumbent target was removed by request truncation")
    retained = (
        incumbent.target,
        *(item for item in retained if item.request_id != incumbent.target.request_id),
    )
    reasons: set[str] = set()
    if requests_seen > len(retained):
        reasons.add("REQUEST_LIMIT")

    option_sets: list[tuple[Selection, ...]] = []
    positions_seen = 0
    positions_kept = 0
    matchings_seen = 0
    matchings_kept = 0
    for index, target in enumerate(retained):
        if clock() >= modeling_deadline:
            raise TimeoutError("MODELING_BUDGET_EXHAUSTED")
        target_request = replace(
            request,
            request_id=f"{request.request_id}-window-{index + 1:02d}",
            trigger_event_type=(
                "ARRIVAL_REQUESTED" if target.request_type == "ARRIVAL" else "DEPARTURE_REQUESTED"
            ),
            trigger_request_id=target.request_id,
            trigger_anonymous_vehicle_id=target.anonymous_vehicle_id,
        )
        generated = bounded_selections_for_target(
            target_request,
            target,
            deadline=modeling_deadline,
            clock=clock,
        )
        if generated.timed_out:
            raise TimeoutError("MODELING_BUDGET_EXHAUSTED")
        positions_seen += generated.positions_seen
        positions_kept += generated.positions_kept
        matchings_seen += generated.buffer_matchings_seen
        matchings_kept += generated.buffer_matchings_kept
        options = list(generated.selections)
        if target.request_id == incumbent.target.request_id:
            options.insert(0, incumbent)
        options.append(_safe_deferred_selection(request, target))
        unique = {_selection_signature(selection): selection for selection in options}
        ordered = tuple(unique[key] for key in sorted(unique))
        option_sets.append(ordered)
        if generated.positions_seen > generated.positions_kept:
            reasons.add("POSITION_LIMIT")
        if generated.buffer_matchings_seen > generated.buffer_matchings_kept:
            reasons.add("BUFFER_MATCHING_LIMIT")

    warm_selections: list[Selection] = [incumbent]
    for target, target_options in zip(retained[1:], option_sets[1:], strict=True):
        selected = next(
            (option for option in target_options if _compatible_prefix((*warm_selections, option))),
            _safe_deferred_selection(request, target),
        )
        warm_selections.append(selected)
    warm_start = _window_plan(request, tuple(warm_selections), is_warm_start=True)
    retained_ids = tuple(item.request_id for item in retained)
    validate_window_plan(warm_start, retained_request_ids=retained_ids)

    plan_limit = int(request.approved_config["max_action_plans_total"])
    partials: list[tuple[Selection, ...]] = [()]
    plan_truncated = False
    for target_options in option_sets:
        next_partials: list[tuple[Selection, ...]] = []
        for partial in partials:
            for option in target_options:
                if clock() >= modeling_deadline:
                    raise TimeoutError("MODELING_BUDGET_EXHAUSTED")
                candidate = (*partial, option)
                if not _compatible_prefix(candidate):
                    continue
                candidate_plan = _window_plan(request, candidate)
                existing_plans = [_window_plan(request, item) for item in next_partials]
                plan_truncated |= _append_bounded_plan(existing_plans, candidate_plan, limit=plan_limit)
                next_partials = [item.selections for item in existing_plans]
        if not next_partials:
            raise ValueError("NO_COMPLETE_FEASIBLE_WARM_START")
        partials = next_partials

    plans: list[WindowPlan] = [warm_start]
    for selections in partials:
        complete_plan = _window_plan(request, selections)
        validate_window_plan(complete_plan, retained_request_ids=retained_ids)
        plan_truncated |= _append_bounded_plan(plans, complete_plan, limit=plan_limit)
    if plan_truncated:
        reasons.add("ACTION_PLAN_LIMIT")
    plans.sort(key=lambda item: (item.objective.key(), item.plan_id))
    if not any(item.plan_id == warm_start.plan_id for item in plans):
        if len(plans) == plan_limit:
            plans.pop()
        plans.append(warm_start)
        plans.sort(key=lambda item: (item.objective.key(), item.plan_id))

    soft_ids = _legal_soft_record_ids(request)
    visible_soft_count = sum(
        item.departure_information.expected_departure_time_s is not None
        for item in request.observed_snapshot.vehicles
    )
    if visible_soft_count > len(soft_ids):
        reasons.add("SOFT_RECORD_LIMIT")
    record = CandidateGenerationRecord(
        requests_seen=requests_seen,
        requests_kept=len(retained),
        positions_seen=positions_seen,
        positions_kept=positions_kept,
        buffer_matchings_seen=matchings_seen,
        buffer_matchings_kept=matchings_kept,
        action_plans_kept=len(plans),
        truncation_reasons=tuple(sorted(reasons)),
    )
    model_content = {
        "schema_version": "1.0.0",
        "information_mode": "OBSERVED_SNAPSHOT_ONLY",
        "layout_sha256": request.layout_sha256,
        "config_sha256": request.config_sha256,
        "visible_snapshot_sha256": request.visible_snapshot_sha256,
        "retained_request_ids": list(retained_ids),
        "legal_soft_record_ids": list(soft_ids),
        "candidate_generation": {
            "requests_seen": record.requests_seen,
            "requests_kept": record.requests_kept,
            "positions_seen": record.positions_seen,
            "positions_kept": record.positions_kept,
            "buffer_matchings_seen": record.buffer_matchings_seen,
            "buffer_matchings_kept": record.buffer_matchings_kept,
            "action_plans_kept": record.action_plans_kept,
            "truncation_reasons": list(record.truncation_reasons),
        },
        "plans": [
            {
                "plan_id": item.plan_id,
                "objective": item.objective.to_mapping(),
                "selections": [_selection_mapping(selection) for selection in item.selections],
            }
            for item in plans
        ],
    }
    return BoundedRollingInput(
        input_model_sha256=canonical_sha256(model_content),
        retained_request_ids=retained_ids,
        legal_soft_record_ids=soft_ids,
        warm_start=warm_start,
        plans=tuple(plans),
        candidate_generation=record,
    )
