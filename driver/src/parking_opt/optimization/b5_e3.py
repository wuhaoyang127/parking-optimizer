"""Frozen B5 E3 blocked-departure tiny cases."""

from __future__ import annotations

from parking_opt.optimization.tiny_exhaustive import (
    TinyCandidate,
    TinyObjective,
    TinyOracleProblem,
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
