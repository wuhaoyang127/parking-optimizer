"""State mutation and fingerprinting for the deterministic simulation."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any

from parking_opt.api.models import SimulationEvent
from parking_opt.api.simulation_types import (
    ReplayMismatchError,
    SimulationCommand,
    SimulationSummary,
)


class SimulationStateMixin:
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
