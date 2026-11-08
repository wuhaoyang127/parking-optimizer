"""Deterministic management-level multi-vehicle simulation and event replay."""

from __future__ import annotations

from datetime import datetime, timedelta

from parking_opt.api.models import Layout
from parking_opt.api.simulation_handlers import SimulationHandlersMixin
from parking_opt.api.simulation_state import SimulationStateMixin
from parking_opt.api.simulation_types import (
    ReplayMismatchError,
    SimulationCommand,
    SimulationRun,
    SimulationSummary,
)


class DeterministicSimulation(SimulationHandlersMixin, SimulationStateMixin):
    """Small 2D management-state engine; no vehicle dynamics or collision model."""

    def __init__(self, *, layout: Layout, seed: int, wall_time_origin: datetime) -> None:
        if seed < 0:
            raise ValueError("seed must be non-negative")
        if wall_time_origin.tzinfo is None or wall_time_origin.utcoffset() is None:
            raise ValueError("wall_time_origin must be timezone-aware")
        self._layout = layout
        self._seed = seed
        self._origin = wall_time_origin
        self._vehicles: dict[str, dict[str, Any]] = {}
        self._space_owners: dict[str, str | None] = {
            space.space_id: (
                f"fixture-{space.space_id}" if space.status.value == "occupied" else None
            )
            for space in layout.spaces
        }
        self._buffer_owners: dict[str, str | None] = {
            buffer.buffer_id: None for buffer in layout.buffers
        }
        self._relocation_count = 0
        self._failure_count = 0
        self._events: list[SimulationEvent] = []
        self._spaces = {space.space_id: space for space in layout.spaces}
        self._groups = {
            group.stack_group_id: group.space_ids_near_to_deep
            for group in layout.tandem_groups
        }
        for space_id, owner in self._space_owners.items():
            if owner is not None:
                self._vehicles[owner] = {
                    "state": "occupied",
                    "space_id": space_id,
                    "buffer_id": None,
                    "progress_step": 0,
                }
        self._fingerprint = 0
        for vehicle_id, vehicle in self._vehicles.items():
            self._fingerprint ^= self._component_hash("vehicle", vehicle_id, vehicle)
        for space_id, owner in self._space_owners.items():
            self._fingerprint ^= self._component_hash("space", space_id, owner)
        for buffer_id, owner in self._buffer_owners.items():
            self._fingerprint ^= self._component_hash("buffer", buffer_id, owner)

    def run(self, commands: tuple[SimulationCommand, ...]) -> SimulationRun:
        ordered = sorted(
            commands,
            key=lambda item: (
                item.simulation_time_s,
                item.priority,
                item.sequence_hint,
                item.vehicle_id,
                item.event_type,
            ),
        )
        for command in ordered:
            if command.simulation_time_s < 0:
                raise ValueError("simulation_time_s must be non-negative")
            self._dispatch(command)
        return SimulationRun(
            seed=self._seed,
            events=tuple(self._events),
            summary=self._summary(),
        )

    def replay(self, events: tuple[SimulationEvent, ...]) -> SimulationSummary:
        previous_time = -1
        for expected_sequence, event in enumerate(events, start=1):
            if event.sequence_no != expected_sequence:
                raise ReplayMismatchError("event sequence is not contiguous")
            if event.simulation_time_s < previous_time:
                raise ReplayMismatchError("event time moved backwards")
            previous_time = event.simulation_time_s
            if event.parking_lot_id != self._layout.parking_lot_id:
                raise ReplayMismatchError(
                    f"parking lot mismatch at event {expected_sequence}"
                )
            expected_wall_time = self._origin + timedelta(
                seconds=event.simulation_time_s
            )
            if event.wall_time != expected_wall_time:
                raise ReplayMismatchError(
                    f"wall time mismatch at event {expected_sequence}"
                )
            if event.before_sha256 != self._state_sha256():
                raise ReplayMismatchError(f"before hash mismatch at event {expected_sequence}")
            changes = event.payload.get("changes")
            if not isinstance(changes, list):
                raise ReplayMismatchError("event changes are missing")
            self._apply_changes(changes)
            if event.after_sha256 != self._state_sha256():
                raise ReplayMismatchError(f"after hash mismatch at event {expected_sequence}")
            self._events.append(event)
        return self._summary()

    def _dispatch(self, command: SimulationCommand) -> None:
        handlers = {
            "ARRIVAL": self._arrival,
            "WAITING": self._waiting,
            "SOFT_HELD": self._soft_hold,
            "SESSION_RESERVED": self._reserve,
            "NAVIGATING": self._navigate,
            "MOVEMENT_TICK": self._movement_tick,
            "OCCUPIED": self._occupy,
            "DEPARTURE_REQUEST": self._departure,
        }
        try:
            handler = handlers[command.event_type]
        except KeyError as exc:
            raise ValueError(f"unsupported simulation command: {command.event_type}") from exc
        handler(command)


def generate_stress_commands(
    *, seed: int, vehicle_count: int, event_count: int
) -> tuple[SimulationCommand, ...]:
    """Generate deterministic management-level arrival/movement inputs for replay budgets."""

    if vehicle_count <= 0 or event_count < vehicle_count:
        raise ValueError("event_count must cover at least one arrival per vehicle")
    commands: list[SimulationCommand] = []
    for index in range(event_count):
        vehicle_index = index % vehicle_count
        vehicle_id = f"stress-{vehicle_index:03d}"
        cycle = index // vehicle_count
        event_type = "ARRIVAL" if cycle == 0 else "MOVEMENT_TICK"
        commands.append(
            SimulationCommand(
                simulation_time_s=index // 10,
                priority=0 if event_type == "ARRIVAL" else 5,
                sequence_hint=index,
                event_type=event_type,
                vehicle_id=vehicle_id,
                payload={
                    "progress_step": cycle,
                    "seed": seed,
                },
            )
        )
    return tuple(commands)
