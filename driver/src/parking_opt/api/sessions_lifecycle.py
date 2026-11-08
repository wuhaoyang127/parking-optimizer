"""Lifecycle, runtime, and terminal commands for the session store."""
from __future__ import annotations
from dataclasses import replace
from datetime import datetime
from parking_opt.api.sessions_types import (
    ACTIVE_STATES,
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
        payload = {"journey_id": journey_id, "accepted": accepted, "expected_version": expected_version}
        with self._lock:
            journey = self._require(journey_id)
            replay = self._replay(journey.session_id, "confirm", idempotency_key, payload)
            if replay is not None:
                return replay
            self._require_version(journey, expected_version)
            self._require_state(journey, JourneyState.SOFT_HELD)
            if self._is_expired(journey):
                result = self._expire(journey, "SOFT_HOLD_EXPIRED")
                self._remember(journey.session_id, "confirm", idempotency_key, payload, result)
                return result
            if not accepted:
                result = self._terminal(journey, JourneyState.CANCELLED, "USER_REJECTED")
            else:
                ttl = (
                    self._timing.driver_reservation_ttl_s
                    if journey.namespace is SessionNamespace.DRIVER
                    else self._timing.defense_reservation_ttl_s
                )
                result = self._transition(
                    journey,
                    JourneyState.SESSION_RESERVED,
                    expires_in_s=ttl,
                    event_type="SESSION_RESERVED",
                )
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
                return 0.0
            return max(0.0, journey.expires_mono_s - self._monotonic())
    def current_wall_time(self) -> datetime:
        with self._lock:
            return self._aware_utc_now()
    def fail(
        self,
        *,
        journey_id: str,
        expected_version: int,
        idempotency_key: str,
        reason: str,
    ) -> JourneyRecord:
        if not reason:
            raise ValueError("failure reason is required")
        return self._terminal_command(
            command="fail",
            journey_id=journey_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            allowed_states=ACTIVE_STATES,
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
            if journey.state in {JourneyState.SESSION_RESERVED, JourneyState.NAVIGATING} and self._is_expired(journey):
                result = self._expire(journey, f"{journey.state.upper()}_EXPIRED")
                self._remember(journey.session_id, "report_external_occupancy", idempotency_key, payload, result)
                return result
            if journey.state not in {JourneyState.SOFT_HELD, JourneyState.SESSION_RESERVED, JourneyState.NAVIGATING} or journey.space_id is None:
                raise IllegalTransitionError("external occupancy requires a claimed pre-occupancy journey")
            unavailable_key = (journey.session_id, journey.namespace, journey.scenario_id, journey.parking_lot_id, journey.space_id)
            self._unavailable_spaces[unavailable_key] = "EXTERNAL_SPACE_OCCUPIED"
            result = self._terminal(journey, JourneyState.FAILED, "EXTERNAL_SPACE_OCCUPIED")
            self._remember(journey.session_id, "report_external_occupancy", idempotency_key, payload, result)
            return result
    def touch_session(self, session_id: str, namespace: SessionNamespace) -> None:
        with self._lock:
            self.expire_due()
            now = self._monotonic()
            for journey in tuple(self._journeys.values()):
                if journey.session_id == session_id and journey.namespace is namespace and journey.state in ACTIVE_STATES:
                    self._journeys[journey.journey_id] = replace(journey, last_activity_mono_s=now)
    def expire_due(self) -> tuple[JourneyRecord, ...]:
        with self._lock:
            return self._expire_due_scope()
    def collect_idle_sessions(self) -> tuple[JourneyRecord, ...]:
        with self._lock:
            self.expire_due()
            collected = self._collect_idle_scope()
            self._collect_idle_unavailable_scope()
            return collected
