"""Bounded rolling candidate over complete, visible-information window plans."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from time import monotonic
from typing import Any

from parking_opt.contracts.canonical import canonical_sha256
from parking_opt.contracts.schema_validation import SchemaCatalog
from parking_opt.domain.conversion import action_to_mapping, transaction_to_mapping
from parking_opt.domain.enums import (
    ActionStatus,
    ActionType,
    ArrivalStatus,
    PrimaryDecision,
    SolverStatus,
    ValidationStatus,
)
from parking_opt.domain.records import (
    CandidateGenerationRecord,
    DecisionRequest,
    DecisionResult,
    DecisionTiming,
    FallbackRecord,
    PendingRequest,
)
from parking_opt.strategies._selection import (
    Selection,
    bounded_selections_for_target,
    deterministic_target,
    select_decision,
)
from parking_opt.strategies.fallback import (
    deterministic_fallback,
    result_from_selection,
)
from parking_opt.strategies.protocol import (
    validate_decision_request,
    validate_decision_result,
)

_HARD_MAX_REQUESTS = 12
_HARD_MAX_POSITIONS = 8
_HARD_MAX_BUFFER_MATCHINGS = 4
_HARD_MAX_PLANS = 64
_HARD_MAX_SOFT_RECORDS = 20


@dataclass(frozen=True, slots=True)
class RollingObjective:
    """Frozen R1a-R5b window objective in natural units."""

    overdue_departures_unfinished: int
    departures_unfinished: int
    active_transactions_unfinished: int
    admitted_arrivals_unfinished: int
    arrivals_completed: int
    waiting_s: int
    relocation_legs: int
    relocation_distance_m: float
    non_relocation_distance_m: float
    blocked_exposure_vehicle_s: int
    reservation_position_s: int

    def key(self) -> tuple[int | float, ...]:
        """Return the frozen lexicographic minimization key."""

        return (
            self.overdue_departures_unfinished,
            self.departures_unfinished,
            self.active_transactions_unfinished,
            self.admitted_arrivals_unfinished,
            -self.arrivals_completed,
            self.waiting_s,
            self.relocation_legs,
            self.relocation_distance_m,
            self.non_relocation_distance_m,
            self.blocked_exposure_vehicle_s,
            self.reservation_position_s,
        )

    def to_mapping(self) -> dict[str, int | float]:
        """Return canonical, unit-preserving model-input data."""

        return {
            "overdue_departures_unfinished": self.overdue_departures_unfinished,
            "departures_unfinished": self.departures_unfinished,
            "active_transactions_unfinished": self.active_transactions_unfinished,
            "admitted_arrivals_unfinished": self.admitted_arrivals_unfinished,
            "arrivals_completed": self.arrivals_completed,
            "waiting_s": self.waiting_s,
            "relocation_legs": self.relocation_legs,
            "relocation_distance_m": self.relocation_distance_m,
            "non_relocation_distance_m": self.non_relocation_distance_m,
            "blocked_exposure_vehicle_s": self.blocked_exposure_vehicle_s,
            "reservation_position_s": self.reservation_position_s,
        }


@dataclass(frozen=True, slots=True)
class WindowPlan:
    """One complete disposition for every retained visible request."""

    plan_id: str
    selections: tuple[Selection, ...]
    objective: RollingObjective
    is_warm_start: bool = False

    @property
    def first_selection(self) -> Selection:
        """Return the only selection that may leave the rolling boundary."""

        return self.selections[0]


@dataclass(frozen=True, slots=True)
class BoundedRollingInput:
    """Immutable candidate set and audit evidence supplied to the selector."""

    input_model_sha256: str
    retained_request_ids: tuple[str, ...]
    legal_soft_record_ids: tuple[str, ...]
    warm_start: WindowPlan
    plans: tuple[WindowPlan, ...]
    candidate_generation: CandidateGenerationRecord


def _selection_mapping(selection: Selection) -> dict[str, Any]:
    return {
        "target_request_id": selection.target.request_id,
        "target_anonymous_vehicle_id": selection.target.anonymous_vehicle_id,
        "primary_decision": selection.primary_decision.value,
        "recommended_actions": [action_to_mapping(item) for item in selection.actions],
        "candidate_transaction": (
            transaction_to_mapping(selection.transaction)
            if selection.transaction is not None
            else None
        ),
        "explanation_codes": list(selection.explanation_codes),
    }


def _selection_signature(selection: Selection) -> str:
    return canonical_sha256(_selection_mapping(selection))


def _service_key(request: DecisionRequest, item: PendingRequest) -> tuple[object, ...]:
    vehicle = next(
        value
        for value in request.observed_snapshot.vehicles
        if value.anonymous_vehicle_id == item.anonymous_vehicle_id
    )
    sla_violated = (
        item.request_type == "DEPARTURE"
        and request.decision_time_s - item.requested_at_s
        >= int(request.approved_config["max_departure_wait_s"])
    )
    immediately_executable = (
        item.request_type == "DEPARTURE" and vehicle.location_state.kind.value == "AT_POSITION"
    )
    return (
        2 if item.request_type == "DEPARTURE" else 4,
        0 if sla_violated else 1,
        item.requested_at_s,
        0 if immediately_executable else 1,
        item.event_sequence_no,
        item.anonymous_vehicle_id,
    )


def _bounded_requests(request: DecisionRequest) -> tuple[tuple[PendingRequest, ...], int]:
    pending = sorted(
        request.observed_snapshot.pending_requests,
        key=lambda item: _service_key(request, item),
    )
    mandatory = deterministic_target(request)
    if mandatory is not None:
        pending = [mandatory, *(item for item in pending if item != mandatory)]
    limit = int(request.approved_config["max_requests_per_solve"])
    return tuple(pending[:limit]), len(pending)


def _safe_deferred_selection(request: DecisionRequest, target: PendingRequest) -> Selection:
    if target.request_type == "ARRIVAL":
        waited = request.decision_time_s - target.requested_at_s
        if waited >= int(request.approved_config["max_arrival_wait_s"]):
            return Selection(
                target=target,
                primary_decision=PrimaryDecision.REJECT,
                explanation_codes=("ROLLING_WINDOW_WAIT_LIMIT_REACHED",),
            )
        return Selection(
            target=target,
            primary_decision=PrimaryDecision.WAIT,
            explanation_codes=("ROLLING_WINDOW_DEFERRED",),
        )
    waited = request.decision_time_s - target.requested_at_s
    if waited >= int(request.approved_config["max_departure_wait_s"]):
        return Selection(
            target=target,
            primary_decision=PrimaryDecision.REQUEST_MANUAL_INTERVENTION,
            explanation_codes=("ROLLING_WINDOW_DEPARTURE_SLA_VIOLATED",),
        )
    return Selection(
        target=target,
        primary_decision=PrimaryDecision.WAIT,
        explanation_codes=("ROLLING_WINDOW_DEFERRED",),
    )


def _assigned_position(selection: Selection) -> str | None:
    for action in selection.actions:
        if action.action_type is ActionType.ASSIGN:
            return action.destination_position_id
    return None


def _compatible_prefix(selections: tuple[Selection, ...]) -> bool:
    action_ids: set[str] = set()
    assigned_positions: set[str] = set()
    target_ids: set[str] = set()
    for selection in selections:
        if selection.target.request_id in target_ids:
            return False
        target_ids.add(selection.target.request_id)
        destination = _assigned_position(selection)
        if destination is not None:
            if destination in assigned_positions:
                return False
            assigned_positions.add(destination)
        current_ids = {item.action_id for item in selection.actions}
        if len(current_ids) != len(selection.actions) or action_ids & current_ids:
            return False
        action_ids.update(current_ids)
        if (
            selection.transaction is not None
            and set(selection.transaction.action_ids) != current_ids
        ):
            return False
    return True


def _objective(
    request: DecisionRequest,
    selections: tuple[Selection, ...],
) -> RollingObjective:
    completed_departures: set[str] = set()
    completed_arrivals: set[str] = set()
    waiting_s = 0
    relocation_legs = 0
    relocation_distance_m = 0.0
    non_relocation_distance_m = 0.0
    blocked_exposure = 0
    reservation_s = 0
    slots = {item["position_id"]: item for item in request.layout["slots"]}
    occupied = {
        item.position_id for item in request.observed_snapshot.positions if item.occupant_vehicle_id
    }
    for selection in selections:
        target = selection.target
        if selection.primary_decision is PrimaryDecision.WAIT:
            waiting_s += max(0, request.decision_time_s - target.requested_at_s)
            waiting_s += int(request.approved_config["rolling_window_s"])
        if selection.primary_decision is PrimaryDecision.RECOMMEND_ACTIONS:
            if target.request_type == "DEPARTURE":
                completed_departures.add(target.request_id)
            else:
                completed_arrivals.add(target.request_id)
        for action in selection.actions:
            if action.action_type in {
                ActionType.RELOCATE_TO_BUFFER,
                ActionType.RESTORE_ORIGINAL,
            }:
                relocation_legs += 1
                relocation_distance_m += action.distance_m
            else:
                non_relocation_distance_m += action.distance_m
            if action.action_type is ActionType.ASSIGN:
                reservation_s += action.modeled_duration_s
                destination = action.destination_position_id
                if destination is not None:
                    slot = slots[destination]
                    blocked_exposure += sum(
                        other["stack_group_id"] == slot["stack_group_id"]
                        and int(other["depth"]) > int(slot["depth"])
                        and other["position_id"] in occupied
                        for other in slots.values()
                    ) * int(request.approved_config["rolling_window_s"])

    departures = tuple(
        selection.target for selection in selections if selection.target.request_type == "DEPARTURE"
    )
    unfinished_departures = tuple(
        item for item in departures if item.request_id not in completed_departures
    )
    overdue = sum(
        request.decision_time_s - item.requested_at_s
        >= int(request.approved_config["max_departure_wait_s"])
        for item in unfinished_departures
    )
    active_transactions = sum(
        item.status.value
        not in {
            "COMPLETED",
            "CANCELLED",
            "FAILED_RESOLVED",
        }
        for item in request.observed_snapshot.transactions
    )
    selected_vehicle_ids = {selection.target.anonymous_vehicle_id for selection in selections}
    completed_arrival_vehicle_ids = {
        selection.target.anonymous_vehicle_id
        for selection in selections
        if selection.target.request_id in completed_arrivals
    }
    admitted_incomplete = sum(
        item.anonymous_vehicle_id in selected_vehicle_ids
        and item.ever_admitted
        and item.arrival_status is not ArrivalStatus.ENTRY_COMPLETED
        and item.anonymous_vehicle_id not in completed_arrival_vehicle_ids
        for item in request.observed_snapshot.vehicles
    )
    return RollingObjective(
        overdue_departures_unfinished=overdue,
        departures_unfinished=len(unfinished_departures),
        active_transactions_unfinished=active_transactions,
        admitted_arrivals_unfinished=admitted_incomplete,
        arrivals_completed=len(completed_arrivals),
        waiting_s=waiting_s,
        relocation_legs=relocation_legs,
        relocation_distance_m=relocation_distance_m,
        non_relocation_distance_m=non_relocation_distance_m,
        blocked_exposure_vehicle_s=blocked_exposure,
        reservation_position_s=reservation_s,
    )


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
                plan_truncated |= _append_bounded_plan(
                    existing_plans,
                    candidate_plan,
                    limit=plan_limit,
                )
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


def _incumbent_fallback(
    request: DecisionRequest,
    incumbent: DecisionResult,
    *,
    original_status: SolverStatus,
    reason: str,
    elapsed_s: float,
    candidate_generation: CandidateGenerationRecord | None = None,
    input_model_sha256: str | None = None,
) -> DecisionResult:
    record = FallbackRecord(
        original_method=request.algorithm_id,
        original_solver_status=original_status,
        reason=reason,
        used_strategy="online-rule-v1",
        elapsed_s=elapsed_s,
        result_validation_status=ValidationStatus.VALID,
    )
    return replace(
        incumbent,
        solver_status=original_status,
        fallback_record=record,
        input_model_sha256=input_model_sha256,
        candidate_generation=candidate_generation,
        explanation_codes=tuple(
            dict.fromkeys((*incumbent.explanation_codes, reason, "FALLBACK_USED"))
        ),
        timing=replace(
            incumbent.timing,
            end_to_end_s=elapsed_s,
            validation_and_modeling_s=elapsed_s,
        ),
    )


class RollingCandidatePolicy:
    """C5 feature-flagged rolling policy with an online incumbent."""

    def __init__(
        self,
        *,
        schema_catalog: SchemaCatalog,
        clock: Callable[[], float] = monotonic,
        cancel_requested: Callable[[], bool] = lambda: False,
    ) -> None:
        self._schema_catalog = schema_catalog
        self._clock = clock
        self._cancel_requested = cancel_requested

    def decide(self, request: DecisionRequest) -> DecisionResult:
        """Return only the best bounded plan's first visible decision."""

        started = self._clock()
        logging_reserve = float(request.approved_config["minimum_logging_reserve_s"])
        fallback_reserve = min(
            float(request.approved_config["fallback_target_s"]),
            0.1 * request.decision_deadline_s,
        )
        policy_return_deadline = started + request.decision_deadline_s - logging_reserve
        main_deadline = policy_return_deadline - fallback_reserve
        try:
            validate_decision_request(request, self._schema_catalog)
            _validate_configured_bounds(request)
        except (TypeError, ValueError):
            result = deterministic_fallback(
                request,
                policy_return_deadline=policy_return_deadline,
                original_status=SolverStatus.MODEL_INVALID,
                reason="INVALID_REQUEST_OR_CANDIDATE_BOUNDS",
                force_emergency=True,
                clock=self._clock,
            )
            validate_decision_result(result, self._schema_catalog)
            return result

        optimization_started = self._clock()
        target_budget = min(
            float(request.approved_config["optimization_budget_s"]),
            max(0.0, main_deadline - optimization_started),
        )
        modeling_deadline = min(
            main_deadline,
            optimization_started + 0.20 * target_budget,
        )
        incumbent_selection = select_decision(
            request,
            first_fit=False,
            deadline=modeling_deadline,
            clock=self._clock,
        )
        if incumbent_selection is None:
            result = deterministic_fallback(
                request,
                policy_return_deadline=policy_return_deadline,
                original_status=SolverStatus.TIME_LIMIT_NO_FEASIBLE,
                reason="NO_VALID_ONLINE_INCUMBENT",
                clock=self._clock,
            )
            validate_decision_result(result, self._schema_catalog)
            return result
        incumbent = result_from_selection(
            request,
            incumbent_selection,
            solver_status=SolverStatus.NOT_RUN,
            fallback_record=None,
            elapsed_s=max(0.0, self._clock() - started),
        )
        validate_decision_result(incumbent, self._schema_catalog)
        if not bool(request.approved_config["rolling_enabled"]):
            result = _incumbent_fallback(
                request,
                incumbent,
                original_status=SolverStatus.NOT_RUN,
                reason="ROLLING_FEATURE_DISABLED",
                elapsed_s=max(0.0, self._clock() - started),
            )
            validate_decision_result(result, self._schema_catalog)
            return result
        if self._cancel_requested():
            result = _incumbent_fallback(
                request,
                incumbent,
                original_status=SolverStatus.TIME_LIMIT_FEASIBLE,
                reason="ROLLING_CANCELLED",
                elapsed_s=max(0.0, self._clock() - started),
            )
            validate_decision_result(result, self._schema_catalog)
            return result

        try:
            model_input = build_bounded_rolling_input(
                request,
                incumbent=incumbent_selection,
                modeling_deadline=modeling_deadline,
                clock=self._clock,
            )
        except TimeoutError:
            result = _incumbent_fallback(
                request,
                incumbent,
                original_status=SolverStatus.NOT_RUN,
                reason="MODELING_BUDGET_EXHAUSTED",
                elapsed_s=max(0.0, self._clock() - started),
            )
            validate_decision_result(result, self._schema_catalog)
            return result
        except (TypeError, ValueError):
            result = _incumbent_fallback(
                request,
                incumbent,
                original_status=SolverStatus.MODEL_INVALID,
                reason="NO_COMPLETE_FEASIBLE_WARM_START",
                elapsed_s=max(0.0, self._clock() - started),
            )
            validate_decision_result(result, self._schema_catalog)
            return result

        solver_limit = max(
            0.0,
            min(
                0.60 * target_budget,
                main_deadline - self._clock() - 0.20 * target_budget,
            ),
        )
        solver_deadline = self._clock() + solver_limit
        solve_started = self._clock()
        best = model_input.warm_start
        completed = True
        for plan in model_input.plans:
            if self._cancel_requested() or self._clock() >= solver_deadline:
                completed = False
                break
            if plan.objective.key() < best.objective.key() or (
                plan.objective.key() == best.objective.key() and plan.plan_id < best.plan_id
            ):
                best = plan
        solver_elapsed = max(0.0, self._clock() - solve_started)
        postsolve_started = self._clock()
        try:
            validate_window_plan(best, retained_request_ids=model_input.retained_request_ids)
        except ValueError:
            result = _incumbent_fallback(
                request,
                incumbent,
                original_status=SolverStatus.VALIDATION_FAILED,
                reason="FULL_WINDOW_PLAN_VALIDATION_FAILED",
                elapsed_s=max(0.0, self._clock() - started),
                candidate_generation=model_input.candidate_generation,
                input_model_sha256=model_input.input_model_sha256,
            )
            validate_decision_result(result, self._schema_catalog)
            return result
        status = SolverStatus.OPTIMAL if completed else SolverStatus.TIME_LIMIT_FEASIBLE
        elapsed = max(0.0, self._clock() - started)
        result = result_from_selection(
            request,
            best.first_selection,
            solver_status=status,
            fallback_record=None,
            elapsed_s=elapsed,
        )
        result = replace(
            result,
            input_model_sha256=model_input.input_model_sha256,
            candidate_generation=model_input.candidate_generation,
            explanation_codes=tuple(
                dict.fromkeys(
                    (
                        *result.explanation_codes,
                        (
                            "BOUNDED_CANDIDATE_OPTIMAL"
                            if completed
                            else "BOUNDED_CANDIDATE_TIME_LIMIT_FEASIBLE"
                        ),
                        "FIRST_DECISION_ONLY",
                    )
                )
            ),
            timing=DecisionTiming(
                end_to_end_s=elapsed,
                validation_and_modeling_s=max(0.0, solve_started - started),
                solver_s=solver_elapsed,
                postsolve_validation_s=max(0.0, self._clock() - postsolve_started),
                minimum_logging_s=logging_reserve,
                solver_time_limit_s=solver_limit,
            ),
        )
        try:
            validate_decision_result(result, self._schema_catalog)
        except (TypeError, ValueError):
            result = _incumbent_fallback(
                request,
                incumbent,
                original_status=SolverStatus.VALIDATION_FAILED,
                reason="FIRST_DECISION_VALIDATION_FAILED",
                elapsed_s=max(0.0, self._clock() - started),
                candidate_generation=model_input.candidate_generation,
                input_model_sha256=model_input.input_model_sha256,
            )
            validate_decision_result(result, self._schema_catalog)
        return result


__all__ = [
    "BoundedRollingInput",
    "RollingCandidatePolicy",
    "RollingObjective",
    "WindowPlan",
    "build_bounded_rolling_input",
    "validate_window_plan",
]
