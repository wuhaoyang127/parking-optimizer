from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from parking_opt.api.scenarios import built_in_scenarios
from parking_opt.api.simulation import (
    DeterministicSimulation,
    ReplayMismatchError,
    SimulationCommand,
)

ORIGIN = datetime(2026, 8, 13, tzinfo=UTC)


def _command(
    sequence: int,
    event_type: str,
    *,
    vehicle_id: str = "vehicle-new",
    payload: dict[str, object] | None = None,
) -> SimulationCommand:
    return SimulationCommand(
        simulation_time_s=sequence,
        priority=sequence,
        sequence_hint=sequence,
        event_type=event_type,
        vehicle_id=vehicle_id,
        payload={} if payload is None else payload,
    )


def _park_in_b02() -> tuple[SimulationCommand, ...]:
    return (
        _command(1, "ARRIVAL"),
        _command(2, "SOFT_HELD", payload={"space_id": "B-02"}),
        _command(3, "SESSION_RESERVED"),
        _command(4, "NAVIGATING"),
        _command(5, "MOVEMENT_TICK", payload={"progress_step": 1}),
        _command(6, "OCCUPIED"),
    )


def test_tandem_departure_relocates_blocker_to_buffer_then_restores_it() -> None:
    layout = built_in_scenarios()["school-demo"].layout
    run = DeterministicSimulation(layout=layout, seed=11, wall_time_origin=ORIGIN).run(
        (*_park_in_b02(), _command(7, "DEPARTURE_REQUEST"))
    )
    event_types = tuple(item.event_type for item in run.events)
    assert event_types[-3:] == (
        "RELOCATION_TO_BUFFER",
        "DEPARTED",
        "RELOCATION_RESTORED",
    )
    assert run.summary.relocation_count == 1
    assert run.summary.failure_count == 0
    assert run.events[-3].payload["from_space_id"] == "B-01"
    assert run.events[-3].payload["to_buffer_id"] == "BUF-01"


def test_buffer_shortage_records_failure_without_moving_any_vehicle() -> None:
    base = built_in_scenarios()["school-demo"].layout
    no_buffer = base.model_copy(update={"buffers": ()})
    engine = DeterministicSimulation(layout=no_buffer, seed=11, wall_time_origin=ORIGIN)
    parked = engine.run(_park_in_b02())
    before = parked.summary.final_state_sha256
    failed = engine.run((_command(7, "DEPARTURE_REQUEST"),))
    event = failed.events[-1]
    assert event.event_type == "SIMULATION_FAILURE"
    assert event.payload["reason_code"] == "BUFFER_CAPACITY_INSUFFICIENT"
    assert event.before_sha256 != event.after_sha256
    assert failed.summary.failure_count == 1
    assert before != failed.summary.final_state_sha256


def test_same_commands_replay_to_identical_event_and_final_hashes() -> None:
    layout = built_in_scenarios()["school-demo"].layout
    commands = (*_park_in_b02(), _command(7, "DEPARTURE_REQUEST"))
    first = DeterministicSimulation(layout=layout, seed=2026, wall_time_origin=ORIGIN).run(
        commands
    )
    second = DeterministicSimulation(layout=layout, seed=2026, wall_time_origin=ORIGIN).run(
        commands
    )
    assert second == first
    replayed = DeterministicSimulation(
        layout=layout, seed=2026, wall_time_origin=ORIGIN
    ).replay(first.events)
    assert replayed == first.summary


def test_replay_detects_tampered_state_hash() -> None:
    layout = built_in_scenarios()["school-demo"].layout
    run = DeterministicSimulation(layout=layout, seed=1, wall_time_origin=ORIGIN).run(
        (_command(1, "ARRIVAL"),)
    )
    tampered = run.events[0].model_copy(update={"after_sha256": "0" * 64})
    with pytest.raises(ReplayMismatchError, match="after hash mismatch"):
        DeterministicSimulation(layout=layout, seed=1, wall_time_origin=ORIGIN).replay(
            (tampered,)
        )


def test_replay_binds_seed_layout_scope_and_wall_time_origin() -> None:
    layout = built_in_scenarios()["school-demo"].layout
    run = DeterministicSimulation(layout=layout, seed=1, wall_time_origin=ORIGIN).run(
        (_command(1, "ARRIVAL"),)
    )
    with pytest.raises(ReplayMismatchError, match="before hash mismatch"):
        DeterministicSimulation(layout=layout, seed=2, wall_time_origin=ORIGIN).replay(
            run.events
        )
    wrong_lot = run.events[0].model_copy(update={"parking_lot_id": "lot-other"})
    with pytest.raises(ReplayMismatchError, match="parking lot mismatch"):
        DeterministicSimulation(layout=layout, seed=1, wall_time_origin=ORIGIN).replay(
            (wrong_lot,)
        )
    wrong_time = run.events[0].model_copy(
        update={"wall_time": run.events[0].wall_time + timedelta(seconds=1)}
    )
    with pytest.raises(ReplayMismatchError, match="wall time mismatch"):
        DeterministicSimulation(layout=layout, seed=1, wall_time_origin=ORIGIN).replay(
            (wrong_time,)
        )


def test_stable_order_uses_time_priority_hint_and_vehicle_id() -> None:
    layout = built_in_scenarios()["school-demo"].layout
    commands = (
        SimulationCommand(0, 1, 0, "ARRIVAL", "vehicle-b", {}),
        SimulationCommand(0, 0, 1, "ARRIVAL", "vehicle-c", {}),
        SimulationCommand(0, 1, 0, "ARRIVAL", "vehicle-a", {}),
    )
    run = DeterministicSimulation(layout=layout, seed=1, wall_time_origin=ORIGIN).run(
        commands
    )
    assert tuple(event.subject_id for event in run.events) == (
        "vehicle-c",
        "vehicle-a",
        "vehicle-b",
    )
