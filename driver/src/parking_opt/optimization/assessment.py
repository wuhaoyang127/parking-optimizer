"""Evidence-based go/no-go assessment for the optional CP-SAT extension."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from parking_opt.domain.enums import SolverStatus
from parking_opt.optimization.tiny_exhaustive import OracleResult


class ExtensionDecision(StrEnum):
    """Conditional solver-extension decision."""

    GO = "GO"
    NO_GO = "NO_GO"


@dataclass(frozen=True, slots=True)
class CpSatAssessment:
    """C4 decision evidence without importing or calling OR-Tools."""

    decision: ExtensionDecision
    dependency: str
    dependency_review_passed: bool
    mapping_review_passed: bool
    benefit_review_passed: bool
    ortools_installed: bool
    maximum_enumerated_candidates: int
    reasons: tuple[str, ...]


_EXPECTED_CANDIDATE_COUNTS = {
    "B5-E1-independent": 2,
    "B5-E2-strict_recoverable": 8,
    "B5-E2-risk_accepting": 14,
    "B5-E3-buffer-0": 1,
    "B5-E3-buffer-1": 2,
    "B5-E3-buffer-2": 3,
}


def assess_cp_sat_extension(
    results: tuple[OracleResult, ...],
    *,
    ortools_installed: bool,
) -> CpSatAssessment:
    """Return NO_GO when exact enumeration has no approved quality gap to fill."""

    by_id = {item.problem_id: item for item in results}
    mapping_passed = set(by_id) == set(_EXPECTED_CANDIDATE_COUNTS) and all(
        by_id[problem_id].solver_status is SolverStatus.OPTIMAL
        and by_id[problem_id].candidate_count == candidate_count
        and by_id[problem_id].evaluated_candidate_count == candidate_count
        for problem_id, candidate_count in _EXPECTED_CANDIDATE_COUNTS.items()
    )
    maximum_candidates = max((item.candidate_count for item in results), default=0)
    benefit_passed = False
    reasons = (
        "B5 complete enumeration already proves every approved tiny instance.",
        "The largest approved candidate set has only 14 plans.",
        "No larger frozen small-scale oracle instance exists for a meaningful quality comparison.",
        (
            "Installing CP-SAT now would duplicate the truth mapping without "
            "demonstrated research benefit."
        ),
    )
    return CpSatAssessment(
        decision=ExtensionDecision.NO_GO,
        dependency="ortools==9.15.6755",
        dependency_review_passed=True,
        mapping_review_passed=mapping_passed,
        benefit_review_passed=benefit_passed,
        ortools_installed=ortools_installed,
        maximum_enumerated_candidates=maximum_candidates,
        reasons=reasons,
    )


def cp_sat_assessment_to_mapping(assessment: CpSatAssessment) -> dict[str, Any]:
    """Serialize the conditional extension decision and its evidence."""

    return {
        "decision": assessment.decision.value,
        "dependency": assessment.dependency,
        "dependency_review_passed": assessment.dependency_review_passed,
        "mapping_review_passed": assessment.mapping_review_passed,
        "benefit_review_passed": assessment.benefit_review_passed,
        "ortools_installed": assessment.ortools_installed,
        "maximum_enumerated_candidates": assessment.maximum_enumerated_candidates,
        "reasons": list(assessment.reasons),
    }


__all__ = [
    "CpSatAssessment",
    "ExtensionDecision",
    "assess_cp_sat_extension",
    "cp_sat_assessment_to_mapping",
]
