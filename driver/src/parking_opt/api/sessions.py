"""Atomic single-process session state for the web-v2 M3 synthetic prototype."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from threading import RLock
from time import monotonic

from parking_opt.api.sessions_claims import ClaimCommandMixin
from parking_opt.api.sessions_lifecycle import LifecycleCommandMixin
from parking_opt.api.sessions_profiles import DemoProfileMixin
from parking_opt.api.sessions_queries import QuerySnapshotMixin
from parking_opt.api.sessions_runtime import RuntimeCollectionMixin
from parking_opt.api.sessions_tandem import TandemStorageMixin
from parking_opt.api.sessions_transitions import TransitionPersistenceMixin
from parking_opt.api.sessions_types import (
    ACTIVE_STATES,
    CLAIM_STATES,
    ZERO_SHA256,
    JourneyRecord,
    JourneyState,
    SessionAvailabilitySnapshot,
    SessionEvent,
    SessionNamespace,
    SessionTiming,
    _DemoProfileIdempotencyResult,
    _IdempotencyResult,
    _TandemReplayIdempotencyResult,
    _journey_sha256,
    _sha256,
)
from parking_opt.api.sessions_types import (
    SessionStateError,
    JourneyNotFoundError,
    IllegalTransitionError,
    VersionConflictError,
    IdempotencyConflictError,
    ActiveJourneyConflictError,
    ResourceClaimConflictError,
    ResourceClaim,
    TandemCoordinationRecord,
    AvailabilityScopeSnapshot,
    SessionStore,
)


class InMemorySessionStore(
    TandemStorageMixin,
    DemoProfileMixin,
    QuerySnapshotMixin,
    ClaimCommandMixin,
    LifecycleCommandMixin,
    RuntimeCollectionMixin,
    TransitionPersistenceMixin,
):
    def __init__(
        self,
        *,
        timing: SessionTiming,
        monotonic_clock: Callable[[], float] = monotonic,
        utc_clock: Callable | None = None,
    ) -> None:
        self._timing = timing
        self._monotonic = monotonic_clock
        self._utc = utc_clock if utc_clock is not None else (lambda: datetime.now(UTC))
        self._lock = RLock()
        self._journeys: dict[str, JourneyRecord] = {}
        self._claims: dict[tuple, ResourceClaim] = {}
        self._unavailable_spaces: dict[tuple, str] = {}
        self._events: list[SessionEvent] = []
        self._idempotency: dict[tuple, _IdempotencyResult] = {}
        self._driver_demo_profile_idempotency: dict[tuple, _DemoProfileIdempotencyResult] = {}
        self._driver_demo_profile_indexes: dict[tuple, int] = {}
        self._driver_demo_processed_terminal_journeys: set[str] = set()
        self._tandem_arrival_replays: dict[str, object] = {}
        self._tandem_arrival_idempotency: dict[tuple, _TandemReplayIdempotencyResult] = {}
        self._tandem_coordination_records: dict[str, TandemCoordinationRecord] = {}
        self._tandem_departure_replays: dict[str, object] = {}
        self._tandem_replay_idempotency: dict[tuple, _TandemReplayIdempotencyResult] = {}
        self.ACTIVE_STATES = ACTIVE_STATES

    def get_journey(self, journey_id: str) -> JourneyRecord | None:
        with self._lock:
            return self._journeys.get(journey_id)

    @contextmanager
    def atomic(self) -> Iterator[InMemorySessionStore]:
        """Hold the lock and roll back all store mutations when a compound command fails."""

        with self._lock:
            snapshot = (
                self._journeys.copy(),
                self._claims.copy(),
                self._unavailable_spaces.copy(),
                self._idempotency.copy(),
                self._driver_demo_profile_indexes.copy(),
                self._driver_demo_profile_idempotency.copy(),
                self._driver_demo_processed_terminal_journeys.copy(),
                self._tandem_arrival_replays.copy(),
                self._tandem_arrival_idempotency.copy(),
                self._tandem_coordination_records.copy(),
                self._tandem_departure_replays.copy(),
                self._tandem_replay_idempotency.copy(),
                self._events.copy(),
            )
            try:
                yield self
            except BaseException:
                (
                    self._journeys,
                    self._claims,
                    self._unavailable_spaces,
                    self._idempotency,
                    self._driver_demo_profile_indexes,
                    self._driver_demo_profile_idempotency,
                    self._driver_demo_processed_terminal_journeys,
                    self._tandem_arrival_replays,
                    self._tandem_arrival_idempotency,
                    self._tandem_coordination_records,
                    self._tandem_departure_replays,
                    self._tandem_replay_idempotency,
                    self._events,
                ) = snapshot
                raise

    def refresh_journey(self, journey_id: str) -> JourneyRecord | None:
        """Return one journey after applying its authoritative deadlines without renewal."""

        with self._lock:
            journey = self._journeys.get(journey_id)
            if journey is None:
                return None
            self._expire_due_scope(session_id=journey.session_id, namespace=journey.namespace)
            self._collect_idle_scope(session_id=journey.session_id, namespace=journey.namespace)
            self._collect_idle_unavailable_scope(session_id=journey.session_id, namespace=journey.namespace)
            return self._journeys[journey_id]

    def current_driver_journey(self, session_id: str) -> JourneyRecord | None:
        """Return the active driver journey, or the latest terminal attempt for recovery."""

        if not session_id:
            raise ValueError("session_id is required")
        with self._lock:
            self._expire_due_scope(session_id=session_id, namespace=SessionNamespace.DRIVER)
            self._collect_idle_scope(session_id=session_id, namespace=SessionNamespace.DRIVER)
            self._collect_idle_unavailable_scope(session_id=session_id, namespace=SessionNamespace.DRIVER)
            candidates = [item for item in self._journeys.values() if item.session_id == session_id and item.namespace is SessionNamespace.DRIVER]
            if not candidates:
                return None
            active = [item for item in candidates if item.state in ACTIVE_STATES]
            pool = active or candidates
            return max(pool, key=lambda item: (item.updated_at, item.created_at, item.journey_id))
