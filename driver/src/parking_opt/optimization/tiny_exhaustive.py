"""Complete enumeration for hand-enumerable offline oracle problems."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from time import perf_counter
from typing import Any

from parking_opt.domain.enums import SolverStatus


class OracleProof(StrEnum):
    """Proof evidence available for one offline oracle result."""

    COMPLETE_ENUMERATION = "COMPLETE_ENUMERATION"
    NONE = "NONE"


@dataclass(frozen=True, slots=True)
class TinyObjective:
    """Natural-unit O1-O6 values with one canonical lexicographic key."""

    unfinished_departures: int = 0
    departure_sla_violations: int = 0
    unresolved_manual_escalations: int = 0
    completed_arrivals: int = 0
    rejected_arrivals: int = 0
    unfinished_arrivals: int = 0
    departure_delay_s: int = 0
    departure_wait_s: int = 0
    arrival_wait_s: int = 0
    normal_position_seconds: int = 0
    relocation_count: int = 0
    relocation_distance_m: float = 0.0
    path_cost_m: float = 0.0
    decision_changes: int = 0
    fallback_count: int = 0

    def __post_init__(self) -> None:
        for field_name, value in self.to_mapping().items():
            if value < 0:
                raise ValueError(f"{field_name} must be non-negative")

    def lexicographic_key(self) -> tuple[int | float, ...]:
        """Return the frozen O1-O6 minimization key."""

        return (
            self.unfinished_departures,
            self.departure_sla_violations,
            self.unresolved_manual_escalations,
            -self.completed_arrivals,
            self.rejected_arrivals,
            self.unfinished_arrivals,
            self.departure_delay_s,
            self.departure_wait_s,
            self.arrival_wait_s,
            -self.normal_position_seconds,
            self.relocation_count,
            self.relocation_distance_m,
            self.path_cost_m,
            self.decision_changes,
            self.fallback_count,
        )

    def to_mapping(self) -> dict[str, int | float]:
        """Expose named natural-unit values without sign inversion."""

        return {
            "unfinished_departures": self.unfinished_departures,
            "departure_sla_violations": self.departure_sla_violations,
            "unresolved_manual_escalations": self.unresolved_manual_escalations,
            "completed_arrivals": self.completed_arrivals,
            "rejected_arrivals": self.rejected_arrivals,
            "unfinished_arrivals": self.unfinished_arrivals,
            "departure_delay_s": self.departure_delay_s,
            "departure_wait_s": self.departure_wait_s,
            "arrival_wait_s": self.arrival_wait_s,
            "normal_position_seconds": self.normal_position_seconds,
            "relocation_count": self.relocation_count,
            "relocation_distance_m": self.relocation_distance_m,
            "path_cost_m": self.path_cost_m,
            "decision_changes": self.decision_changes,
            "fallback_count": self.fallback_count,
        }


@dataclass(frozen=True, slots=True)
class TinyCandidate:
    """One explicitly enumerated business plan and its validation result."""

    plan_id: str
    decisions: tuple[str, ...]
    objective: TinyObjective
    feasible: bool = True
    violation_codes: tuple[str, ...] = ()
    measurements: tuple[tuple[str, float], ...] = ()

    def __post_init__(self) -> None:
        if not self.plan_id or not self.decisions:
            raise ValueError("tiny candidate requires a plan ID and at least one decision")
        if self.feasible and self.violation_codes:
            raise ValueError("a feasible candidate cannot contain violation codes")
        if not self.feasible and not self.violation_codes:
            raise ValueError("an infeasible candidate requires at least one violation code")
        names = [name for name, _ in self.measurements]
        if len(names) != len(set(names)):
            raise ValueError("candidate measurement names must be unique")


@dataclass(frozen=True, slots=True)
class TinyOracleProblem:
    """Finite offline problem whose candidate set is declared complete."""

    problem_id: str
    candidates: tuple[TinyCandidate, ...]
    oracle_time_limit_s: float = 60.0
    information_mode: str = "OFFLINE_ORACLE"

    def __post_init__(self) -> None:
        if not self.problem_id:
            raise ValueError("tiny oracle problem_id must be non-empty")
        if not self.candidates:
            raise ValueError("tiny oracle problem requires at least one candidate")
        if self.information_mode != "OFFLINE_ORACLE":
            raise ValueError("tiny oracle must be explicitly labeled OFFLINE_ORACLE")
        if not 0 < self.oracle_time_limit_s <= 60:
            raise ValueError("tiny oracle time limit must be in (0, 60] seconds")
        plan_ids = [item.plan_id for item in self.candidates]
        if len(plan_ids) != len(set(plan_ids)):
            raise ValueError("tiny oracle candidate plan IDs must be unique")


@dataclass(frozen=True, slots=True)
class OracleResult:
    """One exact or time-limited result with explicit proof and bound."""

    problem_id: str
    information_mode: str
    solver_status: SolverStatus
    proof: OracleProof
    selected_plan: TinyCandidate | None
    best_bound: TinyObjective | None
    candidate_count: int
    evaluated_candidate_count: int
    feasible_candidate_count: int
    elapsed_s: float
    time_limit_s: float

    def __post_init__(self) -> None:
        if self.elapsed_s < 0:
            raise ValueError("oracle elapsed_s must be non-negative")
        if not 0 <= self.evaluated_candidate_count <= self.candidate_count:
            raise ValueError("evaluated candidate count is outside the candidate set")
        if not 0 <= self.feasible_candidate_count <= self.evaluated_candidate_count:
            raise ValueError("feasible candidate count exceeds evaluated candidates")
        if self.solver_status is SolverStatus.OPTIMAL:
            if (
                self.proof is not OracleProof.COMPLETE_ENUMERATION
                or self.selected_plan is None
                or self.best_bound != self.selected_plan.objective
            ):
                raise ValueError("OPTIMAL requires complete enumeration and a matching bound")
        elif self.solver_status is SolverStatus.INFEASIBLE:
            if (
                self.proof is not OracleProof.COMPLETE_ENUMERATION
                or self.selected_plan is not None
                or self.best_bound is not None
            ):
                raise ValueError("INFEASIBLE requires a complete no-plan proof")
        elif self.proof is not OracleProof.NONE or self.best_bound is not None:
            raise ValueError("time-limited results cannot claim an enumeration proof or bound")


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


__all__ = [
    "OracleProof",
    "OracleResult",
    "TinyCandidate",
    "TinyObjective",
    "TinyOracleProblem",
    "oracle_result_to_mapping",
    "solve_tiny_oracle",
]
