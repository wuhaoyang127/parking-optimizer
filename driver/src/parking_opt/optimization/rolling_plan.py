"""Window plan construction, validation, and configured bounds."""

from __future__ import annotations

from parking_opt.contracts.canonical import canonical_sha256
from parking_opt.domain.enums import ActionStatus, PrimaryDecision
from parking_opt.domain.records import DecisionRequest
from parking_opt.optimization.rolling_objective import _compatible_prefix, _objective
from parking_opt.optimization.rolling_types import (
    _HARD_MAX_BUFFER_MATCHINGS,
    _HARD_MAX_PLANS,
    _HARD_MAX_POSITIONS,
    _HARD_MAX_REQUESTS,
    _HARD_MAX_SOFT_RECORDS,
    RollingObjective,
    WindowPlan,
    _selection_mapping,
)
from parking_opt.strategies._selection import Selection


def _window_plan(
    request: DecisionRequest,
    selections: tuple[Selection, ...],
    *,
    is_warm_start: bool = False,
) -> WindowPlan:
    objective = _objective(request, selections)
    content = {
        "selections": [_selection_mapping(item) for item in selections],
        "objective": objective.to_mapping(),
    }
    return WindowPlan(
        plan_id=f"window-plan-{canonical_sha256(content)[:20]}",
        selections=selections,
        objective=objective,
        is_warm_start=is_warm_start,
    )


def validate_window_plan(
    plan: WindowPlan,
    *,
    retained_request_ids: tuple[str, ...],
) -> None:
    """Reject incomplete plans, conflicting capacity, or illegal tail actions."""

    if not plan.selections:
        raise ValueError("window plan must contain at least one selection")
    actual_ids = tuple(item.target.request_id for item in plan.selections)
    if len(actual_ids) != len(set(actual_ids)) or set(actual_ids) != set(retained_request_ids):
        raise ValueError("window plan must dispose every retained request exactly once")
    if not _compatible_prefix(plan.selections):
        raise ValueError("window plan contains conflicting actions or assignments")
    for selection in plan.selections:
        if selection.primary_decision is PrimaryDecision.RECOMMEND_ACTIONS:
            if not selection.actions:
                raise ValueError("action recommendation must contain actions")
            if any(item.status is not ActionStatus.RECOMMENDED for item in selection.actions):
                raise ValueError("window plan may contain only recommended actions")
        elif selection.actions or selection.transaction is not None:
            raise ValueError("non-action window disposition cannot carry actions")


def _append_bounded_plan(
    plans: list[WindowPlan],
    candidate: WindowPlan,
    *,
    limit: int,
) -> bool:
    if any(item.plan_id == candidate.plan_id for item in plans):
        return False
    plans.append(candidate)
    plans.sort(key=lambda item: (item.objective.key(), item.plan_id))
    truncated = len(plans) > limit
    if truncated:
        plans.pop()
    return truncated


def _legal_soft_record_ids(request: DecisionRequest) -> tuple[str, ...]:
    records: list[tuple[int, str]] = []
    for vehicle in request.observed_snapshot.vehicles:
        information = vehicle.departure_information
        if (
            information.expected_departure_time_s is not None
            and information.known_at_time_s <= request.decision_time_s
            and information.source.value in {"reservation", "user_estimate", "model_prediction"}
        ):
            record_id = information.source_record_id or (
                f"{vehicle.anonymous_vehicle_id}-{information.source.value}"
            )
            records.append((information.known_at_time_s, record_id))
    records.sort()
    limit = int(request.approved_config["max_soft_future_records"])
    return tuple(item[1] for item in records[:limit])


def _validate_configured_bounds(request: DecisionRequest) -> None:
    limits = (
        ("max_requests_per_solve", _HARD_MAX_REQUESTS),
        ("max_positions_per_arrival", _HARD_MAX_POSITIONS),
        ("max_buffer_matchings_per_departure", _HARD_MAX_BUFFER_MATCHINGS),
        ("max_action_plans_total", _HARD_MAX_PLANS),
        ("max_soft_future_records", _HARD_MAX_SOFT_RECORDS),
    )
    for field, hard_limit in limits:
        value = int(request.approved_config[field])
        minimum = 0 if field == "max_soft_future_records" else 1
        if not minimum <= value <= hard_limit:
            raise ValueError(f"{field}={value} exceeds frozen C5 bounds")
