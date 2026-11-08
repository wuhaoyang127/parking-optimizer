"""Driver demo profile rotation mixin for the session store."""

from __future__ import annotations

from parking_opt.api.sessions_types import (
    ACTIVE_STATES,
    ActiveJourneyConflictError,
    IdempotencyConflictError,
    IllegalTransitionError,
    JourneyState,
    SessionNamespace,
    VersionConflictError,
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
            if any(
                journey.session_id == session_id
                and journey.namespace is SessionNamespace.DRIVER
                and journey.parking_lot_id == parking_lot_id
                and journey.state in ACTIVE_STATES
                for journey in self._journeys.values()
            ):
                raise ActiveJourneyConflictError("driver demo profile cannot change during an active journey")
            if current_state_version != expected_state_version:
                raise VersionConflictError("driver demo facility state is stale")
            current = self.driver_demo_profile_index(session_id=session_id, parking_lot_id=parking_lot_id, profile_count=profile_count)
            if current != expected_profile_index:
                raise VersionConflictError("driver demo profile is stale")
            result = (current + 1) % profile_count
            self._driver_demo_profile_indexes[(session_id, parking_lot_id)] = result
            self._clear_driver_demo_unavailable(session_id, parking_lot_id)
            self._driver_demo_profile_idempotency[(session_id, idempotency_key)] = _DemoProfileIdempotencyResult(payload_sha256=payload_sha256, profile_index=result)
            return result

    def advance_driver_demo_profile_after_terminal(
        self, *, journey_id: str, profile_count: int
    ) -> int:
        with self._lock:
            journey = self._require(journey_id)
            current = self.driver_demo_profile_index(session_id=journey.session_id, parking_lot_id=journey.parking_lot_id, profile_count=profile_count)
            if journey_id in self._driver_demo_processed_terminal_journeys:
                return current
            if (
                journey.namespace is not SessionNamespace.DRIVER
                or journey.state is not JourneyState.DEPARTED
                or journey.terminal_reason not in {"NORMAL_DEPARTURE", "DEMO_RESET"}
            ):
                raise IllegalTransitionError("demo profile auto-advance requires a completed driver journey")
            if any(
                item.session_id == journey.session_id
                and item.namespace is SessionNamespace.DRIVER
                and item.parking_lot_id == journey.parking_lot_id
                and item.state in ACTIVE_STATES
                for item in self._journeys.values()
            ):
                raise ActiveJourneyConflictError("driver demo profile cannot advance while another journey is active")
            result = (current + 1) % profile_count
            self._driver_demo_profile_indexes[(journey.session_id, journey.parking_lot_id)] = result
            self._clear_driver_demo_unavailable(journey.session_id, journey.parking_lot_id)
            self._driver_demo_processed_terminal_journeys.add(journey_id)
            return result

    def _clear_driver_demo_unavailable(self, session_id: str, parking_lot_id: str) -> None:
        for key in tuple(self._unavailable_spaces):
            if key[0] == session_id and key[1] is SessionNamespace.DRIVER and key[3] == parking_lot_id:
                self._unavailable_spaces.pop(key, None)
