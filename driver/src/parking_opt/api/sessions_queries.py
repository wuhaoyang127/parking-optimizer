"""Query and snapshot mixin for the session store."""

from __future__ import annotations

from parking_opt.api.sessions_types import (
    AvailabilityScopeSnapshot,
    JourneyRecord,
    ResourceClaim,
    SessionAvailabilitySnapshot,
    SessionEvent,
    SessionNamespace,
)


class QuerySnapshotMixin:
    def claimed_space_ids(
        self,
        *,
        session_id: str,
        namespace: SessionNamespace,
        scenario_id: str,
        parking_lot_id: str,
    ) -> frozenset[str]:
        with self._lock:
            return frozenset(
                item.space_id
                for item in self._claims.values()
                if item.session_id == session_id
                and item.namespace is namespace
                and item.scenario_id == scenario_id
                and item.parking_lot_id == parking_lot_id
            )

    def active_claims(self) -> tuple[ResourceClaim, ...]:
        with self._lock:
            return tuple(
                sorted(
                    self._claims.values(),
                    key=lambda item: (item.session_id, item.namespace, item.scenario_id, item.parking_lot_id, item.space_id),
                )
            )

    def unavailable_space_reasons(
        self,
        *,
        session_id: str,
        namespace: SessionNamespace,
        scenario_id: str,
        parking_lot_id: str,
    ) -> dict[str, str]:
        with self._lock:
            return {
                space_id: reason
                for (stored_session, stored_namespace, stored_scenario, stored_lot, space_id), reason in self._unavailable_spaces.items()
                if stored_session == session_id and stored_namespace is namespace and stored_scenario == scenario_id and stored_lot == parking_lot_id
            }

    def availability_snapshot(
        self,
        *,
        session_id: str,
        namespace: SessionNamespace,
        scopes: tuple[tuple[str, str], ...],
    ) -> SessionAvailabilitySnapshot:
        if not session_id:
            raise ValueError("session_id is required")
        if len(set(scopes)) != len(scopes):
            raise ValueError("availability scopes must be unique")
        with self._lock:
            self._expire_due_scope(session_id=session_id, namespace=namespace)
            self._collect_idle_scope(session_id=session_id, namespace=namespace)
            self._collect_idle_unavailable_scope(session_id=session_id, namespace=namespace)
            items = tuple(
                AvailabilityScopeSnapshot(
                    scenario_id=scenario_id,
                    parking_lot_id=parking_lot_id,
                    claimed_space_ids=frozenset(
                        claim.space_id
                        for claim in self._claims.values()
                        if claim.session_id == session_id and claim.namespace is namespace and claim.scenario_id == scenario_id and claim.parking_lot_id == parking_lot_id
                    ),
                    unavailable_space_reasons=tuple(
                        sorted(
                            (space_id, reason)
                            for (stored_session, stored_namespace, stored_scenario, stored_lot, space_id), reason in self._unavailable_spaces.items()
                            if stored_session == session_id and stored_namespace is namespace and stored_scenario == scenario_id and stored_lot == parking_lot_id
                        )
                    ),
                )
                for scenario_id, parking_lot_id in scopes
            )
            return SessionAvailabilitySnapshot(session_id=session_id, namespace=namespace, observed_at=self._aware_utc_now(), scopes=items)

    def events(self) -> tuple[SessionEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def session_journeys(
        self, session_id: str, namespace: SessionNamespace
    ) -> tuple[JourneyRecord, ...]:
        with self._lock:
            return tuple(
                sorted(
                    (item for item in self._journeys.values() if item.session_id == session_id and item.namespace is namespace),
                    key=lambda item: (item.updated_at, item.created_at, item.journey_id),
                    reverse=True,
                )
            )
