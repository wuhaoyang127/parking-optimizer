"""Internal transition and persistence mixin for the session store."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from parking_opt.api.sessions_types import (
    IdempotencyConflictError,
    IllegalTransitionError,
    JourneyNotFoundError,
    JourneyRecord,
    JourneyState,
    SessionEvent,
    VersionConflictError,
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
            if from_state in {JourneyState.SESSION_RESERVED, JourneyState.NAVIGATING} and self._is_expired(journey):
                result = self._expire(journey, f"{from_state.upper()}_EXPIRED")
                self._remember(journey.session_id, command, idempotency_key, payload, result)
                return result
            result = self._transition(journey, to_state, preserve_expiry=preserve_expiry, event_type=to_state.upper())
            self._remember(journey.session_id, command, idempotency_key, payload, result)
            return result

    def _terminal_command(
        self,
        *,
        command: str,
        journey_id: str,
        expected_version: int,
        idempotency_key: str,
        allowed_states: frozenset[JourneyState] | set[JourneyState],
        state: JourneyState,
        reason: str,
    ) -> JourneyRecord:
        payload = {"journey_id": journey_id, "expected_version": expected_version, "reason": reason}
        with self._lock:
            journey = self._require(journey_id)
            replay = self._replay(journey.session_id, command, idempotency_key, payload)
            if replay is not None:
                return replay
            self._require_version(journey, expected_version)
            if journey.state not in allowed_states:
                raise IllegalTransitionError(f"journey state {journey.state} does not allow {command}")
            result = self._terminal(journey, state, reason)
            self._remember(journey.session_id, command, idempotency_key, payload, result)
            return result

    def _transition(
        self,
        journey: JourneyRecord,
        state: JourneyState,
        *,
        event_type: str,
        expires_in_s: int | None = None,
        preserve_expiry: bool = False,
        reason: str | None = None,
        event_reason: str | None = None,
        replace_space: bool = False,
        space_id: str | None = None,
    ) -> JourneyRecord:
        now_mono = self._monotonic()
        now_utc = self._aware_utc_now()
        expires_mono: float | None = None
        expires_at: datetime | None = None
        if preserve_expiry:
            expires_mono = journey.expires_mono_s
            expires_at = journey.expires_at
        elif expires_in_s is not None:
            expires_mono = now_mono + expires_in_s
            expires_at = now_utc + timedelta(seconds=expires_in_s)
        result = replace(
            journey,
            state=state,
            version=journey.version + 1,
            updated_at=now_utc,
            expires_at=expires_at,
            expires_mono_s=expires_mono,
            last_activity_mono_s=now_mono,
            terminal_reason=reason,
            space_id=space_id if replace_space else journey.space_id,
        )
        self._journeys[journey.journey_id] = result
        self._append_event(journey, result, event_type, reason if event_reason is None else event_reason)
        return result

    def _terminal(self, journey: JourneyRecord, state: JourneyState, reason: str) -> JourneyRecord:
        result = self._transition(journey, state, event_type=state.upper(), reason=reason)
        self._release_claim(journey)
        self._tandem_coordination_records.pop(journey.journey_id, None)
        return result

    def _expire(self, journey: JourneyRecord, reason: str) -> JourneyRecord:
        return self._terminal(journey, JourneyState.EXPIRED, reason)

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
        reason: str | None,
    ) -> None:
        self._events.append(
            SessionEvent(
                sequence_no=len(self._events) + 1,
                journey_id=after.journey_id,
                event_type=event_type,
                reason_code=reason,
                wall_time=after.updated_at,
                before_sha256=_journey_sha256(before),
                after_sha256=_journey_sha256(after),
            )
        )

    def _replay(
        self,
        session_id: str,
        command: str,
        key: str,
        payload: object,
    ) -> JourneyRecord | None:
        previous = self._idempotency.get((session_id, command, key))
        if previous is None:
            return None
        payload_hash = _sha256(payload)
        if previous.payload_sha256 != payload_hash:
            raise IdempotencyConflictError(f"idempotency key {key} was reused with a different payload")
        return previous.result

    def _remember(
        self,
        session_id: str,
        command: str,
        key: str,
        payload: object,
        result: JourneyRecord,
    ) -> None:
        self._idempotency[(session_id, command, key)] = _IdempotencyResult(payload_sha256=_sha256(payload), result=result)

    def _require(self, journey_id: str) -> JourneyRecord:
        try:
            return self._journeys[journey_id]
        except KeyError as exc:
            raise JourneyNotFoundError(f"unknown journey: {journey_id}") from exc

    @staticmethod
    def _require_version(journey: JourneyRecord, expected: int) -> None:
        if journey.version != expected:
            raise VersionConflictError(f"journey version is {journey.version}, expected {expected}")

    @staticmethod
    def _require_state(journey: JourneyRecord, expected: JourneyState) -> None:
        if journey.state is not expected:
            raise IllegalTransitionError(f"journey state is {journey.state}, expected {expected}")

    def _is_expired(self, journey: JourneyRecord) -> bool:
        return journey.expires_mono_s is not None and self._monotonic() >= journey.expires_mono_s

    def _aware_utc_now(self) -> datetime:
        value = self._utc()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("utc clock must return an aware datetime")
        return value.astimezone(UTC)
