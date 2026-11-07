from __future__ import annotations

import tracemalloc
from datetime import UTC, datetime
from time import perf_counter

from parking_opt.api.scenarios import built_in_scenarios
from parking_opt.api.simulation import DeterministicSimulation, generate_stress_commands


def test_replay_100_vehicles_10000_events_meets_frozen_budget() -> None:
    layout = built_in_scenarios()["school-demo"].layout
    origin = datetime(2026, 8, 13, tzinfo=UTC)
    commands = generate_stress_commands(
        seed=2026,
        vehicle_count=100,
        event_count=10_000,
    )
    run = DeterministicSimulation(
        layout=layout,
        seed=2026,
        wall_time_origin=origin,
    ).run(commands)
    tracemalloc.start()
    started = perf_counter()
    summary = DeterministicSimulation(
        layout=layout,
        seed=2026,
        wall_time_origin=origin,
    ).replay(run.events)
    elapsed_s = perf_counter() - started
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert len(run.events) == 10_000
    assert summary.final_state_sha256 == run.summary.final_state_sha256
    assert elapsed_s <= 2.0
    assert peak_bytes <= 256 * 1024 * 1024
