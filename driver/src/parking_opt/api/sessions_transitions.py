"""Internal transition and persistence mixin for the session store."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC

from parking_opt.api.sessions_types import (
    IdempotencyConflictError,
    JourneyNotFoundError,
    JourneyRecord,
    JourneyState,
    SessionEvent,
    _IdempotencyResult,
    _journey_sha256,
    _sha256,
)


class TransitionPersistenceMixin:
    def _command_transition(
        self,
        *,
        command: str,
        journey_id: str,
        expected_version: int,
        idempotency_key: str,
        from_state: JourneyState,
        to_state: JourneyState,
        preserve_expiry: bool,
    ) -> JourneyRecord:
        payload = {"journey_id": journey_id, "expected_version": expected_version}
        with self._lock:
            journey = self._require(journey_id)
            replay = self._replay(journey.session_id, command, idempotency_key, payload)
            if replay is not None:
                return replay
            self._require_version(journey, expected_version)
            self._require_state(journey, from_state)
            if self._is_expired(journey) and from_state is not JourneyState.SOFT_HELD:
                result = self._expire(journey, f"{from_state.value.upper()}_EXPIRED")
            else:
                result = self._transition(journey, to_state, preserve_expiry=preserve_expiry, event_type=to_state.value.upper(), event_reason=None)
            self._remember(journey.session_id, command, idempotency_key, payload, result)
            return result

    def _terminal_command(
        self,
        *,
        command: str,
        journey_id: str,
        expected_version: int,
        idempotency_key: str,
        allowed_states: set[JourneyState],
        state: JourneyState,
        reason: str,
    ) -> JourneyRecord:
        payload = {"journey_id": journey_id, "expected_version": expected_version}
        with self._lock:
            journey = self._require(journey_id)
            replay = self._replay(journey.session_id, command, idempotency_key, payload)
            if replay is not None:
                return replay
            self._require_version(journey, expected_version)
            if journey.state not in allowed_states:
                raise IdempotencyConflictError(f"{command} is not legal from {journey.state}")
            result = self._terminal(journey, state, reason)
            self._remember(journey.session_id, command, idempotency_key, payload, result)
            return result

    def _transition(
        self,
        journey: JourneyRecord,
        state: JourneyState,
        *,
        preserve_expiry: bool,
        event_type: str,
        event_reason: str | None,
    ) -> JourneyRecord:
        updated = replace(
            journey,
            state=state,
            version=journey.version + 1,
            updated_at=self._aware_utc_now(),
            expires_at=journey.expires_at if preserve_expiry else None,
            expires_mono_s=journey.expires_mono_s if preserve_expiry else None,
        )
        self._journeys[journey.journey_id] = updated
        self._append_event(journey, updated, event_type, event_reason)
        return updated

    def _terminal(self, journey: JourneyRecord, state: JourneyState, reason: str) -> JourneyRecord:
        updated = replace(
            journey,
            state=state,
            version=journey.version + 1,
            updated_at=self._aware_utc_now(),
            expires_at=None,
            expires_mono_s=None,
            terminal_reason=reason,
        )
        self._journeys[journey.journey_id] = updated
        self._release_claim(journey)
        self._append_event(journey, updated, state.value.upper(), reason)
        return updated

    def _expire(self, journey: JourneyRecord, reason: str) -> JourneyRecord:
        updated = replace(
            journey,
            state=JourneyState.EXPIRED,
            version=journey.version + 1,
            updated_at=self._aware_utc_now(),
            expires_at=None,
            expires_mono_s=None,
            terminal_reason=reason,
        )
        self._journeys[journey.journey_id] = updated
        self._release_claim(journey)
        self._append_event(journey, updated, "EXPIRED", reason)
        return updated

    def _release_claim(self, journey: JourneyRecord) -> None:
        if journey.space_id is None:
            return
        key = (journey.session_id, journey.namespace, journey.scenario_id, journey.parking_lot_id, journey.space_id)
        self._claims.pop(key, None)

    def _append_event(
        self,
        before: JourneyRecord | None,
        after: JourneyRecord,
        event_type: str,
        reason_code: str | None,
    ) -> None:
        self._events.append(
            SessionEvent(
                sequence_no=len(self._events) + 1,
                journey_id=after.journey_id,
                event_type=event_type,
                reason_code=reason_code,
                wall_time=self._aware_utc_now(),
                before_sha256=_journey_sha256(before),
                after_sha256=_journey_sha256(after),
            )
        )

    def _replay(
        self,
        session_id: str,
        command: str,
        idempotency_key: str,
        payload: object,
    ) -> JourneyRecord | None:
        key = (session_id, command, idempotency_key)
        replay = self._idempotency.get(key)
        if replay is None:
            return None
        if replay.payload_sha256 != _sha256(payload):
            raise IdempotencyConflictError("idempotency key was reused with different input")
        return replay.result

    def _remember(
        self,
        session_id: str,
        command: str,
        idempotency_key: str,
        payload: object,
        result: JourneyRecord,
    ) -> None:
        key = (session_id, command, idempotency_key)
        if key in self._idempotency:
            raise IdempotencyConflictError("idempotency key is already recorded")
        self._idempotency[key] = _IdempotencyResult(payload_sha256=_sha256(payload), result=result)

    def _require(self, journey_id: str) -> JourneyRecord:
        journey = self._journeys.get(journey_id)
        if journey is None:
            raise JourneyNotFoundError(f"journey not found: {journey_id}")
        return journey

    def _require_version(self, journey: JourneyRecord, expected: int) -> None:
        if journey.version != expected:
            raise IdempotencyConflictError(f"journey version is {journey.version}, expected {expected}")

    @staticmethod
    def _require_state(journey: JourneyRecord, expected: JourneyState) -> None:
        if journey.state is not expected:
            raise IdempotencyConflictError(f"journey state is {journey.state}, expected {expected}")

    def _is_expired(self, journey: JourneyRecord) -> bool:
        return journey.expires_mono_s is not None and self._monotonic() >= journey.expires_mono_s

    def _aware_utc_now(self):
        value = self._utc()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("utc clock must return an aware datetime")
        return value.astimezone(UTC)
