"""C5 feature-flagged rolling policy with an online incumbent."""
from __future__ import annotations
from collections.abc import Callable
from dataclasses import replace
from time import monotonic
from parking_opt.contracts.schema_validation import SchemaCatalog
from parking_opt.domain.enums import SolverStatus, ValidationStatus
from parking_opt.domain.records import (
    CandidateGenerationRecord,
    DecisionRequest,
    DecisionResult,
    DecisionTiming,
    FallbackRecord,
)
from parking_opt.optimization.rolling_build import build_bounded_rolling_input
from parking_opt.optimization.rolling_plan import _validate_configured_bounds, validate_window_plan
from parking_opt.strategies._selection import select_decision
from parking_opt.strategies.fallback import deterministic_fallback, result_from_selection
from parking_opt.strategies.protocol import validate_decision_request, validate_decision_result
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
        explanation_codes=tuple(dict.fromkeys((*incumbent.explanation_codes, reason, "FALLBACK_USED"))),
        timing=replace(
            incumbent.timing,
            end_to_end_s=elapsed_s,
            validation_and_modeling_s=elapsed_s,
        ),
    )
class RollingCandidatePolicy:
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
    def _fallback(
        self,
        request: DecisionRequest,
        incumbent: DecisionResult,
        *,
        original_status: SolverStatus,
        reason: str,
        started: float,
        candidate_generation: CandidateGenerationRecord | None = None,
        input_model_sha256: str | None = None,
    ) -> DecisionResult:
        result = _incumbent_fallback(
            request,
            incumbent,
            original_status=original_status,
            reason=reason,
            elapsed_s=max(0.0, self._clock() - started),
            candidate_generation=candidate_generation,
            input_model_sha256=input_model_sha256,
        )
        validate_decision_result(result, self._schema_catalog)
        return result
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
            result = deterministic_fallback(request, policy_return_deadline=policy_return_deadline, original_status=SolverStatus.MODEL_INVALID, reason="INVALID_REQUEST_OR_CANDIDATE_BOUNDS", force_emergency=True, clock=self._clock)
            validate_decision_result(result, self._schema_catalog)
            return result
        optimization_started = self._clock()
        target_budget = min(float(request.approved_config["optimization_budget_s"]), max(0.0, main_deadline - optimization_started))
        modeling_deadline = min(main_deadline, optimization_started + 0.20 * target_budget)
        incumbent_selection = select_decision(request, first_fit=False, deadline=modeling_deadline, clock=self._clock)
        if incumbent_selection is None:
            result = deterministic_fallback(request, policy_return_deadline=policy_return_deadline, original_status=SolverStatus.TIME_LIMIT_NO_FEASIBLE, reason="NO_VALID_ONLINE_INCUMBENT", clock=self._clock)
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
            return self._fallback(request, incumbent, original_status=SolverStatus.NOT_RUN, reason="ROLLING_FEATURE_DISABLED", started=started)
        if self._cancel_requested():
            return self._fallback(request, incumbent, original_status=SolverStatus.TIME_LIMIT_FEASIBLE, reason="ROLLING_CANCELLED", started=started)
        try:
            model_input = build_bounded_rolling_input(
                request,
                incumbent=incumbent_selection,
                modeling_deadline=modeling_deadline,
                clock=self._clock,
            )
        except TimeoutError:
            return self._fallback(request, incumbent, original_status=SolverStatus.NOT_RUN, reason="MODELING_BUDGET_EXHAUSTED", started=started)
        except (TypeError, ValueError):
            return self._fallback(request, incumbent, original_status=SolverStatus.MODEL_INVALID, reason="NO_COMPLETE_FEASIBLE_WARM_START", started=started)
        solver_limit = max(0.0, min(0.60 * target_budget, main_deadline - self._clock() - 0.20 * target_budget))
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
            return self._fallback(request, incumbent, original_status=SolverStatus.VALIDATION_FAILED, reason="FULL_WINDOW_PLAN_VALIDATION_FAILED", started=started, candidate_generation=model_input.candidate_generation, input_model_sha256=model_input.input_model_sha256)
        status = SolverStatus.OPTIMAL if completed else SolverStatus.TIME_LIMIT_FEASIBLE
        elapsed = max(0.0, self._clock() - started)
        result = result_from_selection(request, best.first_selection, solver_status=status, fallback_record=None, elapsed_s=elapsed)
        result = replace(
            result,
            input_model_sha256=model_input.input_model_sha256,
            candidate_generation=model_input.candidate_generation,
            explanation_codes=tuple(
                dict.fromkeys(
                    (
                        *result.explanation_codes,
                        "BOUNDED_CANDIDATE_OPTIMAL" if completed else "BOUNDED_CANDIDATE_TIME_LIMIT_FEASIBLE",
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
            result = self._fallback(
                request, incumbent, original_status=SolverStatus.VALIDATION_FAILED,
                reason="FIRST_DECISION_VALIDATION_FAILED", started=started,
                candidate_generation=model_input.candidate_generation,
                input_model_sha256=model_input.input_model_sha256,
            )
        return result
