"""Expiry and idle-collection mixin for the session store."""

from __future__ import annotations

from parking_opt.api.sessions_types import (
    ACTIVE_STATES,
    JourneyRecord,
    JourneyState,
    SessionNamespace,
)


class RuntimeCollectionMixin:
    def _expire_due_scope(
        self,
        *,
        session_id: str | None = None,
        namespace: SessionNamespace | None = None,
    ) -> tuple[JourneyRecord, ...]:
        expired: list[JourneyRecord] = []
        for journey in tuple(self._journeys.values()):
            if session_id is not None and journey.session_id != session_id:
                continue
            if namespace is not None and journey.namespace is not namespace:
                continue
            if journey.state in {JourneyState.SOFT_HELD, JourneyState.SESSION_RESERVED, JourneyState.NAVIGATING} and self._is_expired(journey):
                expired.append(self._expire(journey, f"{journey.state.upper()}_EXPIRED"))
        return tuple(expired)

    def _collect_idle_scope(
        self,
        *,
        session_id: str | None = None,
        namespace: SessionNamespace | None = None,
    ) -> tuple[JourneyRecord, ...]:
        with self._lock:
            now = self._monotonic()
            collected: list[JourneyRecord] = []
            for journey in tuple(self._journeys.values()):
                if session_id is not None and journey.session_id != session_id:
                    continue
                if namespace is not None and journey.namespace is not namespace:
                    continue
                if journey.state not in ACTIVE_STATES:
                    continue
                ttl = self._timing.driver_idle_ttl_s if journey.namespace is SessionNamespace.DRIVER else self._timing.defense_idle_ttl_s
                if now - journey.last_activity_mono_s >= ttl:
                    collected.append(self._terminal(journey, JourneyState.FAILED, "DEMO_SESSION_GC"))
            return tuple(collected)

    def _collect_idle_unavailable_scope(
        self,
        *,
        session_id: str | None = None,
        namespace: SessionNamespace | None = None,
    ) -> None:
        now = self._monotonic()
        scopes = {
            (sid, ns)
            for (sid, ns, _scenario_id, _parking_lot_id, _space_id) in self._unavailable_spaces
        }
        for stored_session_id, stored_namespace in scopes:
            if session_id is not None and stored_session_id != session_id:
                continue
            if namespace is not None and stored_namespace is not namespace:
                continue
            journeys = tuple(
                item
                for item in self._journeys.values()
                if item.session_id == stored_session_id and item.namespace is stored_namespace
            )
            if not journeys or any(item.state in ACTIVE_STATES for item in journeys):
                continue
            ttl = self._timing.driver_idle_ttl_s if stored_namespace is SessionNamespace.DRIVER else self._timing.defense_idle_ttl_s
            if now - max(item.last_activity_mono_s for item in journeys) < ttl:
                continue
            for key in tuple(self._unavailable_spaces):
                if key[0] == stored_session_id and key[1] is stored_namespace:
                    del self._unavailable_spaces[key]
