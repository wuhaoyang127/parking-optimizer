"""Deterministic online main baseline approved for C3."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from time import monotonic

from parking_opt.contracts.schema_validation import SchemaCatalog
from parking_opt.domain.enums import SolverStatus
from parking_opt.domain.records import DecisionRequest, DecisionResult
from parking_opt.strategies._selection import (
    ArrivalCandidateAssessment,
    assess_arrival_candidates,
    deterministic_target,
    emergency_selection,
    select_decision,
)
from parking_opt.strategies.fallback import deterministic_fallback, result_from_selection
from parking_opt.strategies.protocol import (
    validate_decision_request,
    validate_decision_result,
)


class OnlineRulePolicy:
    """Bounded deterministic policy with explicit validation and fallback."""

    def __init__(
        self,
        *,
        schema_catalog: SchemaCatalog,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._schema_catalog = schema_catalog
        self._clock = clock

    def decide(self, request: DecisionRequest) -> DecisionResult:
        """Return one validated online candidate without touching simulator truth."""

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
        except (TypeError, ValueError):
            result = deterministic_fallback(
                request,
                policy_return_deadline=policy_return_deadline,
                original_status=SolverStatus.MODEL_INVALID,
                reason="INVALID_REQUEST_ENVELOPE",
                force_emergency=True,
                clock=self._clock,
            )
            validate_decision_result(result, self._schema_catalog)
            return result

        selection = select_decision(
            request,
            first_fit=False,
            deadline=main_deadline,
            clock=self._clock,
        )
        if selection is None or self._clock() >= main_deadline:
            result = deterministic_fallback(
                request,
                policy_return_deadline=policy_return_deadline,
                original_status=SolverStatus.TIME_LIMIT_NO_FEASIBLE,
                reason="ONLINE_RULE_DEADLINE_EXHAUSTED",
                clock=self._clock,
            )
        else:
            elapsed = max(0.0, self._clock() - started)
            result = result_from_selection(
                request,
                selection,
                solver_status=SolverStatus.NOT_RUN,
                fallback_record=None,
                elapsed_s=elapsed,
            )
        try:
            validate_decision_result(result, self._schema_catalog)
        except (TypeError, ValueError):
            result = deterministic_fallback(
                request,
                policy_return_deadline=policy_return_deadline,
                original_status=SolverStatus.VALIDATION_FAILED,
                reason="RESULT_VALIDATION_FAILED",
                force_emergency=True,
                clock=self._clock,
            )
            validate_decision_result(result, self._schema_catalog)
        elapsed = max(0.0, self._clock() - started)
        return replace(
            result,
            timing=replace(result.timing, end_to_end_s=elapsed),
        )

    def explain_arrival_candidates(
        self,
        request: DecisionRequest,
    ) -> tuple[ArrivalCandidateAssessment, ...]:
        """Return the exact arrival filters and ordering used by :meth:`decide`."""

        validate_decision_request(request, self._schema_catalog)
        target = deterministic_target(request)
        if target is None or target.request_type != "ARRIVAL":
            raise ValueError("arrival candidate explanation requires one arrival target")
        started = self._clock()
        logging_reserve = float(request.approved_config["minimum_logging_reserve_s"])
        deadline = started + request.decision_deadline_s - logging_reserve
        return assess_arrival_candidates(
            request,
            target,
            deadline=deadline,
            clock=self._clock,
        )


__all__ = ["ArrivalCandidateAssessment", "OnlineRulePolicy", "emergency_selection"]
