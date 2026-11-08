"""Query and snapshot mixin for the session store."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from parking_opt.api.sessions_types import (
    CLAIM_STATES,
    ActiveJourneyConflictError,
    AvailabilityScopeSnapshot,
    JourneyRecord,
    JourneyState,
    ResourceClaim,
    SessionAvailabilitySnapshot,
    SessionEvent,
    SessionNamespace,
)


class QuerySnapshotMixin:
    @contextmanager
    def atomic(self) -> Iterator[None]:
        with self._lock:
            yield

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
                claim.space_id
                for claim in self._claims.values()
                if claim.session_id == session_id
                and claim.namespace is namespace
                and claim.scenario_id == scenario_id
                and claim.parking_lot_id == parking_lot_id
            )

    def active_claims(self) -> tuple[ResourceClaim, ...]:
        with self._lock:
            return tuple(sorted(self._claims.values(), key=lambda item: (item.session_id, item.space_id, item.journey_id)))

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
                key[4]: reason
                for key, reason in self._unavailable_spaces.items()
                if key[:4] == (session_id, namespace, scenario_id, parking_lot_id)
            }

    def availability_snapshot(
        self,
        *,
        session_id: str,
        namespace: SessionNamespace,
        scopes: tuple[tuple[str, str], ...],
    ) -> SessionAvailabilitySnapshot:
        with self._lock:
            now = self._aware_utc_now()
            snapshots = []
            for scenario_id, parking_lot_id in scopes:
                claimed = self.claimed_space_ids(
                    session_id=session_id,
                    namespace=namespace,
                    scenario_id=scenario_id,
                    parking_lot_id=parking_lot_id,
                )
                reasons = tuple(
                    sorted(
                        self.unavailable_space_reasons(
                            session_id=session_id,
                            namespace=namespace,
                            scenario_id=scenario_id,
                            parking_lot_id=parking_lot_id,
                        ).items()
                    )
                )
                snapshots.append(
                    AvailabilityScopeSnapshot(
                        scenario_id=scenario_id,
                        parking_lot_id=parking_lot_id,
                        claimed_space_ids=claimed,
                        unavailable_space_reasons=reasons,
                    )
                )
            return SessionAvailabilitySnapshot(
                session_id=session_id,
                namespace=namespace,
                observed_at=now,
                scopes=tuple(snapshots),
            )

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
