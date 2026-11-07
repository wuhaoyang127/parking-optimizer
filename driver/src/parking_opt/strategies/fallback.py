"""Bounded deterministic fallback and precomputed failure-closed outcomes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from time import monotonic

from parking_opt.domain.enums import SolverStatus, ValidationStatus
from parking_opt.domain.records import (
    DecisionRequest,
    DecisionResult,
    DecisionTiming,
    FallbackRecord,
)
from parking_opt.strategies._selection import (
    Selection,
    emergency_selection,
    select_decision,
)


def result_from_selection(
    request: DecisionRequest,
    selection: Selection,
    *,
    solver_status: SolverStatus,
    fallback_record: FallbackRecord | None,
    elapsed_s: float,
) -> DecisionResult:
    """Decorate one selection with the frozen result envelope."""

    return DecisionResult(
        decision_id=f"decision-{request.request_id}",
        request_id=request.request_id,
        algorithm_id=request.algorithm_id,
        algorithm_version=request.algorithm_version,
        config_sha256=request.config_sha256,
        layout_sha256=request.layout_sha256,
        visible_snapshot_sha256=request.visible_snapshot_sha256,
        input_model_sha256=None,
        target_request_id=selection.target.request_id,
        target_anonymous_vehicle_id=selection.target.anonymous_vehicle_id,
        primary_decision=selection.primary_decision,
        recommended_actions=selection.actions,
        candidate_transaction=selection.transaction,
        solver_status=solver_status,
        fallback_record=fallback_record,
        validation_status=ValidationStatus.VALID,
        explanation_codes=selection.explanation_codes,
        timing=DecisionTiming(
            end_to_end_s=elapsed_s,
            validation_and_modeling_s=elapsed_s,
            solver_s=0.0,
            postsolve_validation_s=0.0,
            minimum_logging_s=float(request.approved_config["minimum_logging_reserve_s"]),
            solver_time_limit_s=0.0,
        ),
    )


def deterministic_fallback(
    request: DecisionRequest,
    *,
    policy_return_deadline: float,
    original_status: SolverStatus,
    reason: str,
    force_emergency: bool = False,
    clock: Callable[[], float] = monotonic,
) -> DecisionResult:
    """Run one bounded first-fit scan or return the precomputed safe outcome."""

    started = clock()
    emergency = emergency_selection(request)
    selected: Selection | None
    if force_emergency:
        selected = emergency
        fallback_reason = reason
    elif started >= policy_return_deadline:
        selected = emergency
        fallback_reason = "HARD_DEADLINE_REACHED"
    else:
        selected = select_decision(
            request,
            first_fit=True,
            deadline=policy_return_deadline,
            clock=clock,
        )
        if selected is None:
            selected = emergency
            fallback_reason = "FALLBACK_DEADLINE_EXHAUSTED"
        else:
            fallback_reason = reason
    assert selected is not None
    elapsed = max(0.0, clock() - started)
    record = FallbackRecord(
        original_method=request.algorithm_id,
        original_solver_status=original_status,
        reason=fallback_reason,
        used_strategy="minimal-deterministic-rule-v1",
        elapsed_s=elapsed,
        result_validation_status=ValidationStatus.VALID,
    )
    result = result_from_selection(
        request,
        selected,
        solver_status=original_status,
        fallback_record=record,
        elapsed_s=elapsed,
    )
    return replace(
        result,
        explanation_codes=(*result.explanation_codes, "FALLBACK_USED"),
    )
