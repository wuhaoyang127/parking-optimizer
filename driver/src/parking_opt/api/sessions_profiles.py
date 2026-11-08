"""Driver demo profile rotation mixin for the session store."""

from __future__ import annotations

from parking_opt.api.sessions_types import (
    IdempotencyConflictError,
    _DemoProfileIdempotencyResult,
    _sha256,
)


class DemoProfileMixin:
    def driver_demo_profile_index(
        self, *, session_id: str, parking_lot_id: str, profile_count: int
    ) -> int:
        if not session_id or not parking_lot_id:
            raise ValueError("session_id and parking_lot_id are required")
        if profile_count <= 0:
            raise ValueError("profile_count must be positive")
        with self._lock:
            index = self._driver_demo_profile_indexes.get((session_id, parking_lot_id), 0)
            if index >= profile_count:
                raise ValueError("stored demo profile index exceeds configured profiles")
            return index

    def advance_driver_demo_profile(
        self,
        *,
        session_id: str,
        parking_lot_id: str,
        expected_profile_index: int,
        expected_state_version: str,
        current_state_version: str,
        profile_count: int,
        idempotency_key: str,
    ) -> int:
        if profile_count <= 1:
            raise ValueError("demo profile rotation requires at least two profiles")
        payload = {
            "parking_lot_id": parking_lot_id,
            "expected_profile_index": expected_profile_index,
            "expected_state_version": expected_state_version,
            "profile_count": profile_count,
        }
        payload_sha256 = _sha256(payload)
        with self._lock:
            replay = self._driver_demo_profile_idempotency.get((session_id, idempotency_key))
            if replay is not None:
                if replay.payload_sha256 != payload_sha256:
                    raise IdempotencyConflictError("demo profile idempotency key was reused with different input")
                return replay.profile_index
            index = self._driver_demo_profile_indexes.get((session_id, parking_lot_id), 0)
            if index != expected_profile_index:
                raise IdempotencyConflictError("demo profile expected index is stale")
            next_index = (index + 1) % profile_count
            self._driver_demo_profile_indexes[(session_id, parking_lot_id)] = next_index
            self._driver_demo_profile_idempotency[(session_id, idempotency_key)] = _DemoProfileIdempotencyResult(
                payload_sha256=payload_sha256, profile_index=next_index
            )
            return next_index

    def advance_driver_demo_profile_after_terminal(
        self, *, journey_id: str, profile_count: int
    ) -> int:
        with self._lock:
            journey = self._require(journey_id)
            if profile_count <= 1:
                raise ValueError("demo profile rotation requires at least two profiles")
            key = (journey.session_id, journey.parking_lot_id)
            index = self._driver_demo_profile_indexes.get(key, 0)
            next_index = (index + 1) % profile_count
            self._driver_demo_profile_indexes[key] = next_index
            return next_index

    def _clear_driver_demo_unavailable(
        self, *, session_id: str, namespace, scenario_id: str, parking_lot_id: str
    ) -> None:
        scoped_keys = tuple(
            key
            for key in self._unavailable_spaces
            if key[:4] == (session_id, namespace, scenario_id, parking_lot_id)
        )
        for key in scoped_keys:
            self._unavailable_spaces.pop(key, None)
