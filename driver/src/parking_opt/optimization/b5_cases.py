"""Data-driven complete candidate generation for the frozen B5 tiny cases."""

from __future__ import annotations

from dataclasses import dataclass

from parking_opt.domain.enums import RecoverabilityPolicy
from parking_opt.optimization.tiny_exhaustive import (
    TinyCandidate,
    TinyObjective,
    TinyOracleProblem,
)


@dataclass(frozen=True, slots=True)
class _Slot:
    position_id: str
    group_id: str
    depth: int
    path_cost_m: float


_E2_SLOTS = (
    _Slot("g1d1", "g1", 1, 3.0),
    _Slot("g1d2", "g1", 2, 4.0),
    _Slot("g2d1", "g2", 1, 5.0),
    _Slot("g2d2", "g2", 2, 6.0),
)
_E2_ARRIVALS = (("A", 0), ("B", 1), ("C", 2))


def e1_independent_problem() -> TinyOracleProblem:
    """Return both feasible E1 assignments without preselecting the answer."""

    candidates = tuple(
        TinyCandidate(
            plan_id=f"E1-P{index}",
            decisions=(position_id,),
            objective=TinyObjective(
                completed_arrivals=1,
                normal_position_seconds=10,
                path_cost_m=path_cost_m,
            ),
            measurements=(
                ("demand_satisfaction_rate", 1.0),
                ("normal_space_time_utilization", 0.5),
                ("relocation_count", 0.0),
                ("relocation_distance_m", 0.0),
            ),
        )
        for index, (position_id, path_cost_m) in enumerate(
            (("n1", 10.0), ("n2", 20.0)),
            start=1,
        )
    )
    return TinyOracleProblem("B5-E1-independent", candidates)


def _entry_clear(slot: _Slot, occupied: frozenset[str]) -> bool:
    return all(
        other.position_id not in occupied
        for other in _E2_SLOTS
        if other.group_id == slot.group_id and other.depth < slot.depth
    )


def _exposure_count(occupied: frozenset[str]) -> int:
    return sum(
        any(
            other.position_id in occupied
            and other.group_id == slot.group_id
            and other.depth < slot.depth
            for other in _E2_SLOTS
        )
        for slot in _E2_SLOTS
        if slot.position_id in occupied
    )


def _enumerate_e2_decisions(
    policy: RecoverabilityPolicy,
) -> tuple[tuple[str, ...], ...]:
    completed: list[tuple[str, ...]] = []

    def visit(
        arrival_index: int,
        occupied: frozenset[str],
        decisions: tuple[str, ...],
    ) -> None:
        if arrival_index == len(_E2_ARRIVALS):
            completed.append(decisions)
            return
        legal: list[_Slot] = []
        for slot in _E2_SLOTS:
            if slot.position_id in occupied or not _entry_clear(slot, occupied):
                continue
            projected = occupied | {slot.position_id}
            if policy is RecoverabilityPolicy.STRICT_RECOVERABLE and _exposure_count(projected) > 0:
                continue
            legal.append(slot)
        if not legal:
            visit(arrival_index + 1, occupied, (*decisions, "REJECT"))
            return
        for slot in legal:
            visit(
                arrival_index + 1,
                occupied | {slot.position_id},
                (*decisions, slot.position_id),
            )

    visit(0, frozenset(), ())
    return tuple(completed)


def e2_tandem_problem(policy: RecoverabilityPolicy) -> TinyOracleProblem:
    """Generate the complete E2 legal sequence set for one frozen policy."""

    sequences = _enumerate_e2_decisions(policy)
    prefix = "S" if policy is RecoverabilityPolicy.STRICT_RECOVERABLE else "R"
    slot_by_id = {item.position_id: item for item in _E2_SLOTS}
    candidates: list[TinyCandidate] = []
    for index, decisions in enumerate(sequences, start=1):
        completed = sum(item != "REJECT" for item in decisions)
        rejected = len(decisions) - completed
        occupied = frozenset(item for item in decisions if item != "REJECT")
        normal_position_seconds = sum(
            10 - arrival_time
            for (_, arrival_time), decision in zip(_E2_ARRIVALS, decisions, strict=True)
            if decision != "REJECT"
        )
        path_cost = sum(
            slot_by_id[decision].path_cost_m for decision in decisions if decision != "REJECT"
        )
        exposure = _exposure_count(occupied)
        candidates.append(
            TinyCandidate(
                plan_id=f"E2-{prefix}{index}",
                decisions=decisions,
                objective=TinyObjective(
                    completed_arrivals=completed,
                    rejected_arrivals=rejected,
                    normal_position_seconds=normal_position_seconds,
                    path_cost_m=path_cost,
                ),
                measurements=(
                    ("exposure_count", float(exposure)),
                    ("demand_satisfaction_rate", completed / 3),
                    ("normal_space_time_utilization", normal_position_seconds / 40),
                    ("path_cost_m", path_cost),
                ),
            )
        )
    return TinyOracleProblem(
        f"B5-E2-{policy.value}",
        tuple(candidates),
    )


def e3_blocked_departure_problem(buffer_count: int) -> TinyOracleProblem:
    """Generate manual and reachable automatic E3 transaction candidates."""

    if buffer_count not in {0, 1, 2}:
        raise ValueError("B5 E3 buffer_count must be 0, 1, or 2")
    buffer_legs = (("b1", 5.0, 5), ("b2", 8.0, 8))[:buffer_count]
    candidates = [
        TinyCandidate(
            plan_id=f"E3-B{buffer_count}-MANUAL",
            decisions=("WAIT", "REQUEST_MANUAL_INTERVENTION"),
            objective=TinyObjective(
                unfinished_departures=1,
                unresolved_manual_escalations=1,
                departure_delay_s=30,
                departure_wait_s=30,
                normal_position_seconds=60,
            ),
            measurements=(
                ("automatic_feasible", 0.0),
                ("completed_departures", 0.0),
                ("manual_intervention_count", 1.0),
                ("relocation_count", 0.0),
                ("relocation_distance_m", 0.0),
            ),
        )
    ]
    for buffer_id, leg_distance_m, leg_duration_s in buffer_legs:
        relocation_distance = 2 * leg_distance_m
        target_completed_at_s = leg_duration_s + 7
        transaction_completed_at_s = target_completed_at_s + leg_duration_s
        normal_position_seconds = leg_duration_s + (30 - transaction_completed_at_s)
        candidates.append(
            TinyCandidate(
                plan_id=f"E3-B{buffer_count}-AUTO-{buffer_id.upper()}",
                decisions=(
                    f"RELOCATE_TO_BUFFER:{buffer_id}",
                    "DIRECT_EXIT:A",
                    f"RESTORE_ORIGINAL:{buffer_id}",
                ),
                objective=TinyObjective(
                    departure_delay_s=target_completed_at_s,
                    normal_position_seconds=normal_position_seconds,
                    relocation_count=2,
                    relocation_distance_m=relocation_distance,
                    path_cost_m=relocation_distance + 7,
                ),
                measurements=(
                    ("automatic_feasible", 1.0),
                    ("completed_departures", 1.0),
                    ("manual_intervention_count", 0.0),
                    ("target_departure_completed_at_s", float(target_completed_at_s)),
                    ("transaction_completed_at_s", float(transaction_completed_at_s)),
                    ("relocation_count", 2.0),
                    ("relocation_distance_m", relocation_distance),
                ),
            )
        )
    return TinyOracleProblem(
        f"B5-E3-buffer-{buffer_count}",
        tuple(candidates),
    )


def all_b5_problems() -> tuple[TinyOracleProblem, ...]:
    """Return every frozen B5 problem/configuration in stable order."""

    return (
        e1_independent_problem(),
        e2_tandem_problem(RecoverabilityPolicy.STRICT_RECOVERABLE),
        e2_tandem_problem(RecoverabilityPolicy.RISK_ACCEPTING),
        e3_blocked_departure_problem(0),
        e3_blocked_departure_problem(1),
        e3_blocked_departure_problem(2),
    )


__all__ = [
    "all_b5_problems",
    "e1_independent_problem",
    "e2_tandem_problem",
    "e3_blocked_departure_problem",
]
