"""Command handlers for the deterministic management-level simulation."""

from __future__ import annotations

from typing import Any

from parking_opt.api.simulation_types import SimulationCommand


class SimulationHandlersMixin:
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
