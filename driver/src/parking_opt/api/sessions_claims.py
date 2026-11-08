"""Claim-creation commands for the session store."""
from __future__ import annotations
from dataclasses import replace
from datetime import timedelta
from parking_opt.api.sessions_types import (
    ACTIVE_STATES,
    ActiveJourneyConflictError,
    JourneyRecord,
    JourneyState,
    ResourceClaim,
    ResourceClaimConflictError,
    SessionNamespace,
    _sha256,
)
class ClaimCommandMixin:
    def soft_hold(
        self,
        *,
        session_id: str,
        namespace: SessionNamespace,
        scenario_id: str,
        parking_lot_id: str,
        journey_id: str,
        attempt_id: str,
        space_id: str,
        idempotency_key: str,
    ) -> JourneyRecord:
        payload = {"session_id": session_id, "namespace": namespace, "scenario_id": scenario_id, "parking_lot_id": parking_lot_id, "journey_id": journey_id, "attempt_id": attempt_id, "space_id": space_id}
        with self._lock:
            replay = self._replay(session_id, "soft_hold", idempotency_key, payload)
            if replay is not None:
                return replay
            if journey_id in self._journeys:
                raise ActiveJourneyConflictError(f"journey already exists: {journey_id}")
            if namespace is SessionNamespace.DRIVER and any(
                item.session_id == session_id and item.namespace is namespace and item.state in ACTIVE_STATES
                for item in self._journeys.values()
            ):
                raise ActiveJourneyConflictError("driver session already has an active journey")
            claim_key = (session_id, namespace, scenario_id, parking_lot_id, space_id)
            if claim_key in self._unavailable_spaces:
                raise ResourceClaimConflictError(f"space is unavailable: {space_id}")
            if claim_key in self._claims:
                raise ResourceClaimConflictError(f"space already claimed: {space_id}")
            now_mono = self._monotonic()
            now_utc = self._aware_utc_now()
            expires_mono = now_mono + self._timing.soft_hold_ttl_s
            journey = JourneyRecord(journey_id=journey_id, attempt_id=attempt_id, session_id=session_id, namespace=namespace, scenario_id=scenario_id, parking_lot_id=parking_lot_id, state=JourneyState.SOFT_HELD, version=1, space_id=space_id, created_at=now_utc, updated_at=now_utc, expires_at=now_utc + timedelta(seconds=self._timing.soft_hold_ttl_s), expires_mono_s=expires_mono, last_activity_mono_s=now_mono)
            self._journeys[journey_id] = journey
            self._claims[claim_key] = ResourceClaim(
                session_id=session_id,
                namespace=namespace,
                scenario_id=scenario_id,
                parking_lot_id=parking_lot_id,
                space_id=space_id,
                journey_id=journey_id,
            )
            self._append_event(None, journey, "SOFT_HELD", None)
            self._remember(session_id, "soft_hold", idempotency_key, payload, journey)
            return journey
    def start_waiting(
        self,
        *,
        session_id: str,
        namespace: SessionNamespace,
        scenario_id: str,
        parking_lot_id: str,
        journey_id: str,
        attempt_id: str,
        idempotency_key: str,
    ) -> JourneyRecord:
        payload = {"session_id": session_id, "namespace": namespace, "scenario_id": scenario_id, "parking_lot_id": parking_lot_id, "journey_id": journey_id, "attempt_id": attempt_id}
        with self._lock:
            replay = self._replay(session_id, "start_waiting", idempotency_key, payload)
            if replay is not None:
                return replay
            if journey_id in self._journeys:
                raise ActiveJourneyConflictError(f"journey already exists: {journey_id}")
            if namespace is SessionNamespace.DRIVER and any(
                item.session_id == session_id and item.namespace is namespace and item.state in ACTIVE_STATES
                for item in self._journeys.values()
            ):
                raise ActiveJourneyConflictError("driver session already has an active journey")
            now_mono = self._monotonic()
            now_utc = self._aware_utc_now()
            journey = JourneyRecord(
                journey_id=journey_id,
                attempt_id=attempt_id,
                session_id=session_id,
                namespace=namespace,
                scenario_id=scenario_id,
                parking_lot_id=parking_lot_id,
                state=JourneyState.WAITING,
                version=1,
                space_id=None,
                created_at=now_utc,
                updated_at=now_utc,
                expires_at=None,
                expires_mono_s=None,
                last_activity_mono_s=now_mono,
            )
            self._journeys[journey_id] = journey
            self._append_event(None, journey, "STARTED_WAITING", None)
            self._remember(session_id, "start_waiting", idempotency_key, payload, journey)
            return journey
    def retry_waiting(
        self,
        *,
        journey_id: str,
        expected_version: int,
        space_id: str | None,
        idempotency_key: str,
    ) -> JourneyRecord:
        payload = {"journey_id": journey_id, "expected_version": expected_version, "space_id": space_id}
        with self._lock:
            journey = self._require(journey_id)
            replay = self._replay(journey.session_id, "retry_waiting", idempotency_key, payload)
            if replay is not None:
                return replay
            self._require_version(journey, expected_version)
            self._require_state(journey, JourneyState.WAITING)
            result = self._transition(journey, JourneyState.WAITING, preserve_expiry=False, event_type="WAITING_RETRIED", event_reason="WAITING_RETRIED")
            if space_id is not None:
                claim_key = (result.session_id, result.namespace, result.scenario_id, result.parking_lot_id, space_id)
                if claim_key in self._unavailable_spaces:
                    raise ResourceClaimConflictError(f"space is unavailable: {space_id}")
                if claim_key in self._claims:
                    raise ResourceClaimConflictError(f"space already claimed: {space_id}")
                now_mono = self._monotonic()
                expires_mono = now_mono + self._timing.soft_hold_ttl_s
                result = replace(
                    result,
                    state=JourneyState.SOFT_HELD,
                    space_id=space_id,
                    expires_mono_s=expires_mono,
                    expires_at=self._aware_utc_now() + timedelta(seconds=self._timing.soft_hold_ttl_s),
                )
                self._claims[claim_key] = ResourceClaim(
                    session_id=result.session_id,
                    namespace=result.namespace,
                    scenario_id=result.scenario_id,
                    parking_lot_id=result.parking_lot_id,
                    space_id=space_id,
                    journey_id=result.journey_id,
                )
                self._journeys[journey_id] = result
                self._append_event(journey, result, "SOFT_HELD", None)
            self._remember(journey.session_id, "retry_waiting", idempotency_key, payload, result)
            return result
    def switch_soft_hold(
        self,
        *,
        journey_id: str,
        expected_version: int,
        space_id: str,
        idempotency_key: str,
    ) -> JourneyRecord:
        payload = {"journey_id": journey_id, "expected_version": expected_version, "space_id": space_id}
        with self._lock:
            journey = self._require(journey_id)
            replay = self._replay(journey.session_id, "switch_soft_hold", idempotency_key, payload)
            if replay is not None:
                return replay
            self._require_version(journey, expected_version)
            self._require_state(journey, JourneyState.SOFT_HELD)
            old_space = journey.space_id
            assert old_space is not None
            old_key = (journey.session_id, journey.namespace, journey.scenario_id, journey.parking_lot_id, old_space)
            new_key = (journey.session_id, journey.namespace, journey.scenario_id, journey.parking_lot_id, space_id)
            if new_key in self._unavailable_spaces:
                raise ResourceClaimConflictError(f"space is unavailable: {space_id}")
            if new_key in self._claims:
                raise ResourceClaimConflictError(f"space already claimed: {space_id}")
            result = replace(journey, space_id=space_id)
            self._journeys[journey_id] = result
            self._claims.pop(old_key, None)
            self._claims[new_key] = ResourceClaim(
                session_id=result.session_id,
                namespace=result.namespace,
                scenario_id=result.scenario_id,
                parking_lot_id=result.parking_lot_id,
                space_id=space_id,
                journey_id=result.journey_id,
            )
            self._append_event(journey, result, "SOFT_HOLD_SWITCHED", None)
            self._remember(journey.session_id, "switch_soft_hold", idempotency_key, payload, result)
            return result
