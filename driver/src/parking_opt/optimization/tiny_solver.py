"""Complete enumeration solver for offline oracle problems."""

from __future__ import annotations

from collections.abc import Callable
from time import perf_counter
from typing import Any

from parking_opt.domain.enums import SolverStatus
from parking_opt.optimization.tiny_exhaustive import (
    OracleProof,
    OracleResult,
    TinyCandidate,
    TinyOracleProblem,
)


def solve_tiny_oracle(
    problem: TinyOracleProblem,
    *,
    clock: Callable[[], float] = perf_counter,
) -> OracleResult:
    """Enumerate every candidate unless the explicit 60-second cap is reached."""

    started = clock()
    evaluated = 0
    feasible: list[TinyCandidate] = []
    timed_out = False
    for candidate in problem.candidates:
        if clock() - started >= problem.oracle_time_limit_s:
            timed_out = True
            break
        evaluated += 1
        if candidate.feasible:
            feasible.append(candidate)
    elapsed = max(0.0, clock() - started)
    selected = min(
        feasible,
        key=lambda item: (
            item.objective.lexicographic_key(),
            item.decisions,
            item.plan_id,
        ),
        default=None,
    )
    if timed_out:
        status = (
            SolverStatus.TIME_LIMIT_FEASIBLE
            if selected is not None
            else SolverStatus.TIME_LIMIT_NO_FEASIBLE
        )
        proof = OracleProof.NONE
        bound = None
    elif selected is None:
        status = SolverStatus.INFEASIBLE
        proof = OracleProof.COMPLETE_ENUMERATION
        bound = None
    else:
        status = SolverStatus.OPTIMAL
        proof = OracleProof.COMPLETE_ENUMERATION
        bound = selected.objective
    return OracleResult(
        problem_id=problem.problem_id,
        information_mode=problem.information_mode,
        solver_status=status,
        proof=proof,
        selected_plan=selected,
        best_bound=bound,
        candidate_count=len(problem.candidates),
        evaluated_candidate_count=evaluated,
        feasible_candidate_count=len(feasible),
        elapsed_s=elapsed,
        time_limit_s=problem.oracle_time_limit_s,
    )


def oracle_result_to_mapping(result: OracleResult) -> dict[str, Any]:
    """Serialize proof, bounds, runtime, and selected finite plan."""

    selected = result.selected_plan
    return {
        "problem_id": result.problem_id,
        "information_mode": result.information_mode,
        "solver_status": result.solver_status.value,
        "proof": result.proof.value,
        "selected_plan": (
            {
                "plan_id": selected.plan_id,
                "decisions": list(selected.decisions),
                "objective": selected.objective.to_mapping(),
                "measurements": dict(selected.measurements),
            }
            if selected is not None
            else None
        ),
        "best_bound": result.best_bound.to_mapping() if result.best_bound else None,
        "candidate_count": result.candidate_count,
        "evaluated_candidate_count": result.evaluated_candidate_count,
        "feasible_candidate_count": result.feasible_candidate_count,
        "elapsed_s": result.elapsed_s,
        "time_limit_s": result.time_limit_s,
    }
