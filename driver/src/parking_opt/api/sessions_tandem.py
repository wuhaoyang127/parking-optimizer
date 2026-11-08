"""Tandem coordination and replay storage mixin for the session store."""

from __future__ import annotations

from parking_opt.api.sessions_types import (
    IdempotencyConflictError,
    TandemCoordinationRecord,
    _TandemReplayIdempotencyResult,
    _sha256,
)


class TandemStorageMixin:
    def tandem_arrival_replay(self, journey_id: str) -> object | None:
        with self._lock:
            return self._tandem_arrival_replays.get(journey_id)

    def tandem_coordination(self, journey_id: str) -> TandemCoordinationRecord | None:
        with self._lock:
            return self._tandem_coordination_records.get(journey_id)

    def tandem_coordination_records(
        self, *, session_id: str, scenario_id: str, parking_lot_id: str
    ) -> tuple[TandemCoordinationRecord, ...]:
        with self._lock:
            return tuple(
                sorted(
                    (
                        item
                        for item in self._tandem_coordination_records.values()
                        if item.session_id == session_id and item.scenario_id == scenario_id and item.parking_lot_id == parking_lot_id
                    ),
                    key=lambda item: item.journey_id,
                )
            )

    def replay_tandem_arrival_command(
        self, *, session_id: str, idempotency_key: str, payload: object
    ) -> object | None:
        with self._lock:
            remembered = self._tandem_arrival_idempotency.get((session_id, idempotency_key))
            if remembered is None:
                return None
            if remembered.payload_sha256 != _sha256(payload):
                raise IdempotencyConflictError("tandem arrival idempotency key was reused with different input")
            return remembered.replay

    def remember_tandem_coordination(self, record: TandemCoordinationRecord) -> None:
        with self._lock:
            if record.journey_id in self._tandem_coordination_records:
                raise IdempotencyConflictError("journey already has an active tandem coordination")
            self._tandem_coordination_records[record.journey_id] = record

    def remember_tandem_arrival_replay(
        self,
        *,
        journey_id: str,
        session_id: str,
        idempotency_key: str,
        payload: object,
        replay: object,
    ) -> None:
        with self._lock:
            if journey_id in self._tandem_arrival_replays:
                raise IdempotencyConflictError("journey already has a tandem arrival replay")
            key = (session_id, idempotency_key)
            if key in self._tandem_arrival_idempotency:
                raise IdempotencyConflictError("tandem arrival idempotency key is already recorded")
            self._tandem_arrival_replays[journey_id] = replay
            self._tandem_arrival_idempotency[key] = _TandemReplayIdempotencyResult(payload_sha256=_sha256(payload), replay=replay)

    def tandem_departure_replay(self, journey_id: str) -> object | None:
        with self._lock:
            return self._tandem_departure_replays.get(journey_id)

    def replay_tandem_departure_command(
        self, *, session_id: str, idempotency_key: str, payload: object
    ) -> object | None:
        with self._lock:
            remembered = self._tandem_replay_idempotency.get((session_id, idempotency_key))
            if remembered is None:
                return None
            if remembered.payload_sha256 != _sha256(payload):
                raise IdempotencyConflictError("tandem departure idempotency key was reused with different input")
            return remembered.replay

    def remember_tandem_departure_replay(
        self,
        *,
        journey_id: str,
        session_id: str,
        idempotency_key: str,
        payload: object,
        replay: object,
    ) -> None:
        with self._lock:
            if journey_id in self._tandem_departure_replays:
                raise IdempotencyConflictError("journey already has a tandem departure replay")
            key = (session_id, idempotency_key)
            if key in self._tandem_replay_idempotency:
                raise IdempotencyConflictError("tandem departure idempotency key is already recorded")
            self._tandem_departure_replays[journey_id] = replay
            self._tandem_replay_idempotency[key] = _TandemReplayIdempotencyResult(payload_sha256=_sha256(payload), replay=replay)
