"""Lifecycle, runtime, and terminal commands for the session store."""
from __future__ import annotations
from dataclasses import replace
from datetime import timedelta
from parking_opt.api.sessions_types import (
    IllegalTransitionError,
    JourneyRecord,
    JourneyState,
    SessionNamespace,
)
class LifecycleCommandMixin:
    def confirm(
        self,
        *,
        journey_id: str,
        accepted: bool,
        expected_version: int,
        idempotency_key: str,
    ) -> JourneyRecord:
        payload = {"journey_id": journey_id, "expected_version": expected_version, "accepted": accepted}
        with self._lock:
            journey = self._require(journey_id)
            replay = self._replay(journey.session_id, "confirm", idempotency_key, payload)
            if replay is not None:
                return replay
            self._require_version(journey, expected_version)
            self._require_state(journey, JourneyState.SOFT_HELD)
            if self._is_expired(journey):
                result = self._expire(journey, "SOFT_HOLD_EXPIRED")
            elif not accepted:
                result = self._terminal(journey, JourneyState.CANCELLED, "USER_REJECTED")
            else:
                ttl = (
                    self._timing.driver_reservation_ttl_s
                    if journey.namespace is SessionNamespace.DRIVER
                    else self._timing.defense_reservation_ttl_s
                )
                now_mono = self._monotonic()
                now_utc = self._aware_utc_now()
                result = replace(
                    journey,
                    state=JourneyState.SESSION_RESERVED,
                    expires_mono_s=now_mono + ttl,
                    expires_at=now_utc + timedelta(seconds=ttl),
                )
                self._journeys[journey_id] = result
                self._append_event(journey, result, "SESSION_RESERVED", None)
            self._remember(journey.session_id, "confirm", idempotency_key, payload, result)
            return result
    def start_navigation(
        self,
        *,
        journey_id: str,
        expected_version: int,
        idempotency_key: str,
    ) -> JourneyRecord:
        return self._command_transition(command="start_navigation", journey_id=journey_id, expected_version=expected_version, idempotency_key=idempotency_key, from_state=JourneyState.SESSION_RESERVED, to_state=JourneyState.NAVIGATING, preserve_expiry=True)
    def occupy(
        self,
        *,
        journey_id: str,
        expected_version: int,
        idempotency_key: str,
    ) -> JourneyRecord:
        return self._command_transition(command="occupy", journey_id=journey_id, expected_version=expected_version, idempotency_key=idempotency_key, from_state=JourneyState.NAVIGATING, to_state=JourneyState.OCCUPIED, preserve_expiry=False)
    def cancel(
        self,
        *,
        journey_id: str,
        expected_version: int,
        idempotency_key: str,
    ) -> JourneyRecord:
        return self._terminal_command(command="cancel", journey_id=journey_id, expected_version=expected_version, idempotency_key=idempotency_key, allowed_states={JourneyState.WAITING, JourneyState.SOFT_HELD, JourneyState.SESSION_RESERVED, JourneyState.NAVIGATING}, state=JourneyState.CANCELLED, reason="USER_CANCELLED")
    def depart(
        self,
        *,
        journey_id: str,
        expected_version: int,
        idempotency_key: str,
    ) -> JourneyRecord:
        return self._terminal_command(command="depart", journey_id=journey_id, expected_version=expected_version, idempotency_key=idempotency_key, allowed_states={JourneyState.OCCUPIED}, state=JourneyState.DEPARTED, reason="NORMAL_DEPARTURE")
    def reset_demo(
        self,
        *,
        journey_id: str,
        expected_version: int,
        idempotency_key: str,
    ) -> JourneyRecord:
        payload = {"journey_id": journey_id, "expected_version": expected_version}
        with self._lock:
            journey = self._require(journey_id)
            replay = self._replay(journey.session_id, "reset_demo", idempotency_key, payload)
            if replay is not None:
                return replay
            self._require_version(journey, expected_version)
            if journey.namespace is not SessionNamespace.DRIVER:
                raise IllegalTransitionError("demo reset requires a driver journey")
            self._require_state(journey, JourneyState.OCCUPIED)
            result = self._terminal(journey, JourneyState.DEPARTED, "DEMO_RESET")
            scoped_keys = tuple(key for key in self._unavailable_spaces if key[:4] == (journey.session_id, journey.namespace, journey.scenario_id, journey.parking_lot_id))
            for key in scoped_keys:
                self._unavailable_spaces.pop(key, None)
            self._remember(journey.session_id, "reset_demo", idempotency_key, payload, result)
            return result
    def record_replan(
        self,
        *,
        journey_id: str,
        expected_version: int,
        outcome: str,
        reason: str,
        idempotency_key: str,
    ) -> JourneyRecord:
        if outcome not in {"success", "warning", "failed"}:
            raise ValueError("unsupported replan outcome")
        if not reason:
            raise ValueError("replan reason is required")
        payload = {"journey_id": journey_id, "expected_version": expected_version, "outcome": outcome, "reason": reason}
        with self._lock:
            journey = self._require(journey_id)
            replay = self._replay(journey.session_id, "replan", idempotency_key, payload)
            if replay is not None:
                return replay
            self._require_version(journey, expected_version)
            self._require_state(journey, JourneyState.NAVIGATING)
            if self._is_expired(journey):
                result = self._expire(journey, "NAVIGATING_EXPIRED")
            else:
                result = self._transition(journey, JourneyState.NAVIGATING, preserve_expiry=True, event_type=f"REPLAN_{outcome.upper()}", event_reason=reason)
            self._remember(journey.session_id, "replan", idempotency_key, payload, result)
            return result
    def remaining_deadline_s(self, journey_id: str) -> float:
        with self._lock:
            journey = self._require(journey_id)
            if journey.expires_mono_s is None:
                return float("inf")
            return journey.expires_mono_s - self._monotonic()
    def current_wall_time(self) -> object:
        return self._aware_utc_now()
    def fail(
        self,
        *,
        journey_id: str,
        expected_version: int,
        reason: str,
        idempotency_key: str,
    ) -> JourneyRecord:
        return self._terminal_command(
            command="fail",
            journey_id=journey_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            allowed_states={JourneyState.WAITING, JourneyState.SOFT_HELD, JourneyState.SESSION_RESERVED, JourneyState.NAVIGATING},
            state=JourneyState.FAILED,
            reason=reason,
        )
    def report_external_occupancy(
        self,
        *,
        journey_id: str,
        expected_version: int,
        idempotency_key: str,
    ) -> JourneyRecord:
        payload = {"journey_id": journey_id, "expected_version": expected_version}
        with self._lock:
            journey = self._require(journey_id)
            replay = self._replay(journey.session_id, "report_external_occupancy", idempotency_key, payload)
            if replay is not None:
                return replay
            self._require_version(journey, expected_version)
            self._require_state(journey, JourneyState.NAVIGATING)
            if self._is_expired(journey):
                result = self._expire(journey, "NAVIGATING_EXPIRED")
            else:
                space_id = journey.space_id
                assert space_id is not None
                claim_key = (journey.session_id, journey.namespace, journey.scenario_id, journey.parking_lot_id, space_id)
                result = self._terminal(journey, JourneyState.FAILED, "EXTERNAL_SPACE_OCCUPIED")
                self._unavailable_spaces[claim_key] = "EXTERNAL_SPACE_OCCUPIED"
            self._remember(journey.session_id, "report_external_occupancy", idempotency_key, payload, result)
            return result
    def touch_session(self, session_id: str, namespace: SessionNamespace) -> None:
        with self._lock:
            for journey in self._journeys.values():
                if journey.session_id == session_id and journey.namespace is namespace:
                    self._journeys[journey.journey_id] = replace(journey, last_activity_mono_s=self._monotonic())
    def expire_due(self) -> tuple[JourneyRecord, ...]:
        with self._lock:
            for journey in tuple(self._journeys.values()):
                self._expire_due_scope(session_id=journey.session_id, namespace=journey.namespace)
            return tuple(journey for journey in self._journeys.values() if journey.state is JourneyState.EXPIRED)
    def collect_idle_sessions(self) -> tuple[JourneyRecord, ...]:
        with self._lock:
            results = []
            for journey in tuple(self._journeys.values()):
                results.extend(self._collect_idle_scope(session_id=journey.session_id, namespace=journey.namespace))
                results.extend(self._collect_idle_unavailable_scope(session_id=journey.session_id, namespace=journey.namespace))
            return tuple(results)
