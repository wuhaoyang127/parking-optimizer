"""Deterministic management-level multi-vehicle simulation and event replay."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from parking_opt.api.models import Layout, SimulationEvent


@dataclass(frozen=True, slots=True)
class SimulationCommand:
    simulation_time_s: int
    priority: int
    sequence_hint: int
    event_type: str
    vehicle_id: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SimulationSummary:
    vehicle_count: int
    occupied_space_count: int
    waiting_vehicle_count: int
    relocation_count: int
    failure_count: int
    final_state_sha256: str


@dataclass(frozen=True, slots=True)
class SimulationRun:
    seed: int
    events: tuple[SimulationEvent, ...]
    summary: SimulationSummary


class ReplayMismatchError(ValueError):
    """Recorded event hashes or ordering do not reproduce the same state."""


class DeterministicSimulation:
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

    def _arrival(self, command: SimulationCommand) -> None:
        if command.vehicle_id in self._vehicles:
            self._failure(command, "VEHICLE_ALREADY_EXISTS")
            return
        self._emit(
            command,
            "ARRIVAL",
            [self._vehicle_change(command.vehicle_id, "waiting")],
        )

    def _waiting(self, command: SimulationCommand) -> None:
        self._require_state(command, {"waiting"})
        self._emit(command, "WAITING", [self._vehicle_change(command.vehicle_id, "waiting")])

    def _soft_hold(self, command: SimulationCommand) -> None:
        self._require_state(command, {"waiting"})
        space_id = self._space_from(command)
        if self._space_owners[space_id] is not None or not self._spaces[space_id].assignable:
            self._failure(command, "NO_FEASIBLE_SPACE")
            return
        self._emit(
            command,
            "SOFT_HELD",
            [self._vehicle_change(command.vehicle_id, "soft_held", space_id=space_id)],
        )

    def _reserve(self, command: SimulationCommand) -> None:
        self._require_state(command, {"soft_held"})
        self._emit(
            command,
            "SESSION_RESERVED",
            [self._vehicle_change(command.vehicle_id, "session_reserved")],
        )

    def _navigate(self, command: SimulationCommand) -> None:
        self._require_state(command, {"session_reserved"})
        self._emit(
            command,
            "NAVIGATING",
            [self._vehicle_change(command.vehicle_id, "navigating")],
        )

    def _movement_tick(self, command: SimulationCommand) -> None:
        vehicle = self._vehicles.get(command.vehicle_id)
        if vehicle is None:
            self._failure(command, "VEHICLE_NOT_FOUND")
            return
        step = int(command.payload.get("progress_step", vehicle["progress_step"] + 1))
        self._emit(
            command,
            "MOVEMENT_TICK",
            [self._vehicle_change(command.vehicle_id, vehicle["state"], progress_step=step)],
        )

    def _occupy(self, command: SimulationCommand) -> None:
        self._require_state(command, {"navigating"})
        vehicle = self._vehicles[command.vehicle_id]
        space_id = vehicle["space_id"]
        if space_id is None or self._space_owners[space_id] is not None:
            self._failure(command, "TARGET_SPACE_UNAVAILABLE")
            return
        self._emit(
            command,
            "OCCUPIED",
            [
                self._vehicle_change(command.vehicle_id, "occupied"),
                {"op": "set_space_owner", "space_id": space_id, "owner": command.vehicle_id},
            ],
        )

    def _departure(self, command: SimulationCommand) -> None:
        self._require_state(command, {"occupied"})
        vehicle = self._vehicles[command.vehicle_id]
        target_space_id = vehicle["space_id"]
        assert target_space_id is not None
        target = self._spaces[target_space_id]
        group = self._groups.get(target.stack_group_id, (target_space_id,))
        target_index = group.index(target_space_id)
        blocker_spaces = group[:target_index]
        blockers = [
            (space_id, self._space_owners[space_id])
            for space_id in blocker_spaces
            if self._space_owners[space_id] is not None
        ]
        free_buffers = [
            buffer_id
            for buffer_id, owner in sorted(self._buffer_owners.items())
            if owner is None
        ]
        if len(free_buffers) < len(blockers):
            self._failure(command, "BUFFER_CAPACITY_INSUFFICIENT")
            return
        relocations: list[tuple[str, str, str]] = []
        for (space_id, blocker_id), buffer_id in zip(blockers, free_buffers, strict=True):
            assert blocker_id is not None
            relocations.append((blocker_id, space_id, buffer_id))
            self._emit(
                command,
                "RELOCATION_TO_BUFFER",
                [
                    self._vehicle_change(
                        blocker_id, "relocating_buffer", space_id=None, buffer_id=buffer_id
                    ),
                    {"op": "set_space_owner", "space_id": space_id, "owner": None},
                    {"op": "set_buffer_owner", "buffer_id": buffer_id, "owner": blocker_id},
                    {"op": "increment_relocation"},
                ],
                subject_id=blocker_id,
                extra={"from_space_id": space_id, "to_buffer_id": buffer_id},
            )
        self._emit(
            command,
            "DEPARTED",
            [
                self._vehicle_change(command.vehicle_id, "departed"),
                {"op": "set_space_owner", "space_id": target_space_id, "owner": None},
            ],
        )
        for blocker_id, original_space, buffer_id in reversed(relocations):
            self._emit(
                command,
                "RELOCATION_RESTORED",
                [
                    self._vehicle_change(
                        blocker_id, "occupied", space_id=original_space, buffer_id=None
                    ),
                    {"op": "set_buffer_owner", "buffer_id": buffer_id, "owner": None},
                    {
                        "op": "set_space_owner",
                        "space_id": original_space,
                        "owner": blocker_id,
                    },
                ],
                subject_id=blocker_id,
                extra={"from_buffer_id": buffer_id, "to_space_id": original_space},
            )

    def _failure(self, command: SimulationCommand, reason: str) -> None:
        self._emit(
            command,
            "SIMULATION_FAILURE",
            [{"op": "increment_failure"}],
            extra={"reason_code": reason},
        )

    def _require_state(self, command: SimulationCommand, allowed: set[str]) -> None:
        vehicle = self._vehicles.get(command.vehicle_id)
        if vehicle is None or vehicle["state"] not in allowed:
            current = None if vehicle is None else vehicle["state"]
            raise ValueError(
                f"vehicle {command.vehicle_id} state {current} does not allow {command.event_type}"
            )

    def _space_from(self, command: SimulationCommand) -> str:
        space_id = command.payload.get("space_id")
        if not isinstance(space_id, str) or space_id not in self._spaces:
            raise ValueError("simulation command requires a known space_id")
        return space_id

    @staticmethod
    def _vehicle_change(
        vehicle_id: str,
        state: str,
        *,
        space_id: str | object | None = ...,
        buffer_id: str | object | None = ...,
        progress_step: int | object = ...,
    ) -> dict[str, Any]:
        change: dict[str, Any] = {"op": "set_vehicle", "vehicle_id": vehicle_id, "state": state}
        if space_id is not ...:
            change["space_id"] = space_id
        if buffer_id is not ...:
            change["buffer_id"] = buffer_id
        if progress_step is not ...:
            change["progress_step"] = progress_step
        return change

    def _emit(
        self,
        command: SimulationCommand,
        event_type: str,
        changes: list[dict[str, Any]],
        *,
        subject_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        before = self._state_sha256()
        self._apply_changes(changes)
        after = self._state_sha256()
        payload = {} if extra is None else dict(extra)
        payload["changes"] = changes
        self._events.append(
            SimulationEvent(
                parking_lot_id=self._layout.parking_lot_id,
                sequence_no=len(self._events) + 1,
                simulation_time_s=command.simulation_time_s,
                wall_time=self._origin + timedelta(seconds=command.simulation_time_s),
                event_type=event_type,
                subject_id=command.vehicle_id if subject_id is None else subject_id,
                payload=payload,
                before_sha256=before,
                after_sha256=after,
            )
        )

    def _apply_changes(self, changes: list[dict[str, Any]]) -> None:
        for change in changes:
            operation = change["op"]
            if operation == "set_vehicle":
                vehicle_id = change["vehicle_id"]
                previous_vehicle = self._vehicles.get(vehicle_id)
                current = previous_vehicle or {
                    "state": "waiting",
                    "space_id": None,
                    "buffer_id": None,
                    "progress_step": 0,
                }
                updated = {
                    **current,
                    **{
                        key: value
                        for key, value in change.items()
                        if key not in {"op", "vehicle_id"}
                    },
                }
                if previous_vehicle is not None:
                    self._fingerprint ^= self._component_hash(
                        "vehicle", vehicle_id, previous_vehicle
                    )
                self._vehicles[vehicle_id] = updated
                self._fingerprint ^= self._component_hash("vehicle", vehicle_id, updated)
            elif operation == "set_space_owner":
                space_id = change["space_id"]
                previous_space_owner = self._space_owners[space_id]
                self._fingerprint ^= self._component_hash(
                    "space", space_id, previous_space_owner
                )
                self._space_owners[space_id] = change["owner"]
                self._fingerprint ^= self._component_hash(
                    "space", space_id, change["owner"]
                )
            elif operation == "set_buffer_owner":
                buffer_id = change["buffer_id"]
                previous_buffer_owner = self._buffer_owners[buffer_id]
                self._fingerprint ^= self._component_hash(
                    "buffer", buffer_id, previous_buffer_owner
                )
                self._buffer_owners[buffer_id] = change["owner"]
                self._fingerprint ^= self._component_hash(
                    "buffer", buffer_id, change["owner"]
                )
            elif operation == "increment_relocation":
                self._relocation_count += 1
            elif operation == "increment_failure":
                self._failure_count += 1
            else:
                raise ReplayMismatchError(f"unknown state change operation: {operation}")

    def _state_sha256(self) -> str:
        state = {
            "parking_lot_id": self._layout.parking_lot_id,
            "layout_version": self._layout.layout_version,
            "seed": self._seed,
            "wall_time_origin": self._origin.isoformat(),
            "component_fingerprint": f"{self._fingerprint:064x}",
            "relocation_count": self._relocation_count,
            "failure_count": self._failure_count,
        }
        return hashlib.sha256(
            json.dumps(state, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _component_hash(kind: str, key: str, value: object) -> int:
        payload = json.dumps(
            [kind, key, value], sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return int.from_bytes(hashlib.sha256(payload).digest(), "big")

    def _summary(self) -> SimulationSummary:
        return SimulationSummary(
            vehicle_count=len(self._vehicles),
            occupied_space_count=sum(owner is not None for owner in self._space_owners.values()),
            waiting_vehicle_count=sum(
                item["state"] == "waiting" for item in self._vehicles.values()
            ),
            relocation_count=self._relocation_count,
            failure_count=self._failure_count,
            final_state_sha256=self._state_sha256(),
        )


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
