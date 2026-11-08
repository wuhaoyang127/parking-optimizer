"""Expiry and idle-collection mixin for the session store."""

from __future__ import annotations

from dataclasses import replace

from parking_opt.api.sessions_types import JourneyRecord, JourneyState, SessionNamespace


class RuntimeCollectionMixin:
    def _expire_due_scope(self, *, session_id: str, namespace: SessionNamespace) -> None:
        for journey in tuple(self._journeys.values()):
            if journey.session_id != session_id or journey.namespace is not namespace:
                continue
            if journey.state in {JourneyState.SOFT_HELD, JourneyState.SESSION_RESERVED, JourneyState.NAVIGATING} and self._is_expired(journey):
                reason = {
                    JourneyState.SOFT_HELD: "SOFT_HOLD_EXPIRED",
                    JourneyState.SESSION_RESERVED: "RESERVATION_EXPIRED",
                    JourneyState.NAVIGATING: "NAVIGATING_EXPIRED",
                }[journey.state]
                self._expire(journey, reason)

    def _collect_idle_scope(self, *, session_id: str, namespace: SessionNamespace) -> tuple[JourneyRecord, ...]:
        ttl = self._timing.driver_idle_ttl_s if namespace is SessionNamespace.DRIVER else self._timing.defense_idle_ttl_s
        results = []
        for journey in tuple(self._journeys.values()):
            if journey.session_id != session_id or journey.namespace is not namespace:
                continue
            if journey.state is JourneyState.OCCUPIED and self._monotonic() - journey.last_activity_mono_s >= ttl:
                results.append(self._terminal(journey, JourneyState.FAILED, "DEMO_SESSION_GC"))
        return tuple(results)

    def _collect_idle_unavailable_scope(self, *, session_id: str, namespace: SessionNamespace) -> tuple[JourneyRecord, ...]:
        ttl = self._timing.driver_idle_ttl_s if namespace is SessionNamespace.DRIVER else self._timing.defense_idle_ttl_s
        active_ids = {
            item.journey_id
            for item in self._journeys.values()
            if item.session_id == session_id and item.namespace is namespace and item.state in self.ACTIVE_STATES
        }
        if active_ids:
            return ()
        stale_keys = [
            key
            for key in self._unavailable_spaces
            if key[:2] == (session_id, namespace)
        ]
        if not stale_keys:
            return ()
        last_activity = max(
            (item.last_activity_mono_s for item in self._journeys.values() if item.session_id == session_id and item.namespace is namespace),
            default=self._monotonic(),
        )
        if self._monotonic() - last_activity < ttl:
            return ()
        for key in stale_keys:
            self._unavailable_spaces.pop(key, None)
        return ()
