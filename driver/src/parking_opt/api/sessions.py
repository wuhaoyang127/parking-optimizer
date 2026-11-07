"""Atomic single-process session state for the web-v2 M3 synthetic prototype."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from threading import RLock
from time import monotonic
from typing import Protocol


class SessionStateError(RuntimeError):
    """Base error for rejected state commands."""


class JourneyNotFoundError(SessionStateError):
    """The requested journey does not exist."""


class IllegalTransitionError(SessionStateError):
    """The command is not legal from the authoritative journey state."""


class VersionConflictError(SessionStateError):
    """The command was based on a stale journey version."""


class IdempotencyConflictError(SessionStateError):
    """An idempotency key was reused with a different canonical input."""


class ActiveJourneyConflictError(SessionStateError):
    """A driver namespace already has an active journey."""


class ResourceClaimConflictError(SessionStateError):
    """A space already has an active claim in the same synthetic scene copy."""


class SessionNamespace(StrEnum):
    DRIVER = "driver"
    DEFENSE = "defense"


class JourneyState(StrEnum):
    IDLE = "idle"
    WAITING = "waiting"
    SOFT_HELD = "soft_held"
    SESSION_RESERVED = "session_reserved"
    NAVIGATING = "navigating"
    OCCUPIED = "occupied"
    DEPARTED = "departed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    FAILED = "failed"


ACTIVE_STATES = frozenset(
    {
        JourneyState.WAITING,
        JourneyState.SOFT_HELD,
        JourneyState.SESSION_RESERVED,
        JourneyState.NAVIGATING,
        JourneyState.OCCUPIED,
    }
)
CLAIM_STATES = frozenset(
    {
        JourneyState.SOFT_HELD,
        JourneyState.SESSION_RESERVED,
        JourneyState.NAVIGATING,
        JourneyState.OCCUPIED,
    }
)
ZERO_SHA256 = "0" * 64


@dataclass(frozen=True, slots=True)
class SessionTiming:
    driver_idle_ttl_s: int
    defense_idle_ttl_s: int
    soft_hold_ttl_s: int
    driver_reservation_ttl_s: int
    defense_reservation_ttl_s: int

    def __post_init__(self) -> None:
        if min(asdict(self).values()) <= 0:
            raise ValueError("all session timing values must be positive")


@dataclass(frozen=True, slots=True)
class JourneyRecord:
    journey_id: str
    attempt_id: str
    session_id: str
    namespace: SessionNamespace
    scenario_id: str
    parking_lot_id: str
    state: JourneyState
    version: int
    space_id: str | None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None
    expires_mono_s: float | None
    last_activity_mono_s: float
    terminal_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ResourceClaim:
    session_id: str
    namespace: SessionNamespace
    scenario_id: str
    parking_lot_id: str
    space_id: str
    journey_id: str


@dataclass(frozen=True, slots=True)
class TandemCoordinationRecord:
    session_id: str
    scenario_id: str
    parking_lot_id: str
    journey_id: str
    stack_group_id: str
    target_space_id: str
    blocker_space_ids: tuple[str, ...]
    blocker_vehicle_ids: tuple[str, ...]
    buffer_ids: tuple[str, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.blocker_space_ids:
            raise ValueError("tandem coordination requires at least one blocker")
        if not (
            len(self.blocker_space_ids)
            == len(self.blocker_vehicle_ids)
            == len(self.buffer_ids)
        ):
            raise ValueError("tandem coordination blocker and buffer counts differ")


@dataclass(frozen=True, slots=True)
class AvailabilityScopeSnapshot:
    """One session-scene parking-lot view captured under the store lock."""

    scenario_id: str
    parking_lot_id: str
    claimed_space_ids: frozenset[str]
    unavailable_space_reasons: tuple[tuple[str, str], ...]

    @property
    def unavailable_space_ids(self) -> frozenset[str]:
        return frozenset(space_id for space_id, _reason in self.unavailable_space_reasons)


@dataclass(frozen=True, slots=True)
class SessionAvailabilitySnapshot:
    """Atomic availability exclusions for one synthetic session namespace."""

    session_id: str
    namespace: SessionNamespace
    observed_at: datetime
    scopes: tuple[AvailabilityScopeSnapshot, ...]


@dataclass(frozen=True, slots=True)
class SessionEvent:
    sequence_no: int
    journey_id: str
    event_type: str
    reason_code: str | None
    wall_time: datetime
    before_sha256: str
    after_sha256: str


@dataclass(frozen=True, slots=True)
class _IdempotencyResult:
    payload_sha256: str
    result: JourneyRecord


@dataclass(frozen=True, slots=True)
class _DemoProfileIdempotencyResult:
    payload_sha256: str
    profile_index: int


@dataclass(frozen=True, slots=True)
class _TandemReplayIdempotencyResult:
    payload_sha256: str
    replay: object


class SessionStore(Protocol):
    """Replaceable persistence boundary for M3 journey state."""

    def get_journey(self, journey_id: str) -> JourneyRecord | None: ...


def _sha256(value: object) -> str:
    def default(item: object) -> str:
        if isinstance(item, (datetime, StrEnum)):
            return str(item)
        raise TypeError(f"unsupported canonical value: {type(item).__name__}")

    payload = json.dumps(
        value,
        default=default,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _journey_sha256(journey: JourneyRecord | None) -> str:
    return ZERO_SHA256 if journey is None else _sha256(asdict(journey))


class InMemorySessionStore:
    """Thread-safe M3 store for one application process and isolated synthetic scenes."""

    def __init__(
        self,
        *,
        timing: SessionTiming,
        monotonic_clock: Callable[[], float] = monotonic,
        utc_clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._timing = timing
        self._monotonic = monotonic_clock
        self._utc = utc_clock or (lambda: datetime.now(UTC))
        self._lock = RLock()
        self._journeys: dict[str, JourneyRecord] = {}
        self._claims: dict[tuple[str, SessionNamespace, str, str, str], ResourceClaim] = {}
        self._unavailable_spaces: dict[
            tuple[str, SessionNamespace, str, str, str], str
        ] = {}
        self._idempotency: dict[tuple[str, str, str], _IdempotencyResult] = {}
        self._driver_demo_profile_indexes: dict[tuple[str, str], int] = {}
        self._driver_demo_profile_idempotency: dict[
            tuple[str, str], _DemoProfileIdempotencyResult
        ] = {}
        self._driver_demo_processed_terminal_journeys: set[str] = set()
        self._tandem_arrival_replays: dict[str, object] = {}
        self._tandem_arrival_idempotency: dict[
            tuple[str, str], _TandemReplayIdempotencyResult
        ] = {}
        self._tandem_coordination_records: dict[str, TandemCoordinationRecord] = {}
        self._tandem_departure_replays: dict[str, object] = {}
        self._tandem_replay_idempotency: dict[
            tuple[str, str], _TandemReplayIdempotencyResult
        ] = {}
        self._events: list[SessionEvent] = []

    def get_journey(self, journey_id: str) -> JourneyRecord | None:
        with self._lock:
            return self._journeys.get(journey_id)

    def tandem_arrival_replay(self, journey_id: str) -> object | None:
        with self._lock:
            return self._tandem_arrival_replays.get(journey_id)

    def tandem_coordination(self, journey_id: str) -> TandemCoordinationRecord | None:
        with self._lock:
            return self._tandem_coordination_records.get(journey_id)

    def tandem_coordination_records(
        self,
        *,
        session_id: str,
        scenario_id: str,
        parking_lot_id: str,
    ) -> tuple[TandemCoordinationRecord, ...]:
        with self._lock:
            return tuple(
                sorted(
                    (
                        item
                        for item in self._tandem_coordination_records.values()
                        if item.session_id == session_id
                        and item.scenario_id == scenario_id
                        and item.parking_lot_id == parking_lot_id
                    ),
                    key=lambda item: item.journey_id,
                )
            )

    def replay_tandem_arrival_command(
        self,
        *,
        session_id: str,
        idempotency_key: str,
        payload: object,
    ) -> object | None:
        with self._lock:
            remembered = self._tandem_arrival_idempotency.get(
                (session_id, idempotency_key)
            )
            if remembered is None:
                return None
            if remembered.payload_sha256 != _sha256(payload):
                raise IdempotencyConflictError(
                    "tandem arrival idempotency key was reused with different input"
                )
            return remembered.replay

    def remember_tandem_coordination(self, record: TandemCoordinationRecord) -> None:
        with self._lock:
            if record.journey_id in self._tandem_coordination_records:
                raise IdempotencyConflictError(
                    "journey already has an active tandem coordination"
                )
            self._tandem_coordination_records[record.journey_id] = record

    def remember_tandem_arrival_replay(
        self,
        *,
        journey_id: str,
        session_id: str,
        idempotency_key: str,
        payload: object,
        replay: object,
    ) -> None:
        with self._lock:
            if journey_id in self._tandem_arrival_replays:
                raise IdempotencyConflictError(
                    "journey already has a tandem arrival replay"
                )
            key = (session_id, idempotency_key)
            if key in self._tandem_arrival_idempotency:
                raise IdempotencyConflictError(
                    "tandem arrival idempotency key is already recorded"
                )
            self._tandem_arrival_replays[journey_id] = replay
            self._tandem_arrival_idempotency[key] = _TandemReplayIdempotencyResult(
                payload_sha256=_sha256(payload),
                replay=replay,
            )

    def tandem_departure_replay(self, journey_id: str) -> object | None:
        with self._lock:
            return self._tandem_departure_replays.get(journey_id)

    def replay_tandem_departure_command(
        self,
        *,
        session_id: str,
        idempotency_key: str,
        payload: object,
    ) -> object | None:
        with self._lock:
            remembered = self._tandem_replay_idempotency.get(
                (session_id, idempotency_key)
            )
            if remembered is None:
                return None
            if remembered.payload_sha256 != _sha256(payload):
                raise IdempotencyConflictError(
                    "tandem departure idempotency key was reused with different input"
                )
            return remembered.replay

    def remember_tandem_departure_replay(
        self,
        *,
        journey_id: str,
        session_id: str,
        idempotency_key: str,
        payload: object,
        replay: object,
    ) -> None:
        with self._lock:
            if journey_id in self._tandem_departure_replays:
                raise IdempotencyConflictError(
                    "journey already has a tandem departure replay"
                )
            key = (session_id, idempotency_key)
            if key in self._tandem_replay_idempotency:
                raise IdempotencyConflictError(
                    "tandem departure idempotency key is already recorded"
                )
            self._tandem_departure_replays[journey_id] = replay
            self._tandem_replay_idempotency[key] = _TandemReplayIdempotencyResult(
                payload_sha256=_sha256(payload),
                replay=replay,
            )

    def refresh_journey(self, journey_id: str) -> JourneyRecord | None:
        """Return one journey after applying its authoritative deadlines without renewal."""

        with self._lock:
            journey = self._journeys.get(journey_id)
            if journey is None:
                return None
            self._expire_due_scope(
                session_id=journey.session_id,
                namespace=journey.namespace,
            )
            self._collect_idle_scope(
                session_id=journey.session_id,
                namespace=journey.namespace,
            )
            self._collect_idle_unavailable_scope(
                session_id=journey.session_id,
                namespace=journey.namespace,
            )
            return self._journeys[journey_id]

    def current_driver_journey(self, session_id: str) -> JourneyRecord | None:
        """Return the active driver journey, or the latest terminal attempt for recovery."""

        if not session_id:
            raise ValueError("session_id is required")
        with self._lock:
            self._expire_due_scope(
                session_id=session_id,
                namespace=SessionNamespace.DRIVER,
            )
            self._collect_idle_scope(
                session_id=session_id,
                namespace=SessionNamespace.DRIVER,
            )
            self._collect_idle_unavailable_scope(
                session_id=session_id,
                namespace=SessionNamespace.DRIVER,
            )
            candidates = [
                item
                for item in self._journeys.values()
                if item.session_id == session_id
                and item.namespace is SessionNamespace.DRIVER
            ]
            if not candidates:
                return None
            active = [item for item in candidates if item.state in ACTIVE_STATES]
            pool = active or candidates
            return max(pool, key=lambda item: (item.updated_at, item.created_at, item.journey_id))

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
        """Advance one idle synthetic driver lot exactly once per idempotency key."""

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
            replay = self._driver_demo_profile_idempotency.get(
                (session_id, idempotency_key)
            )
            if replay is not None:
                if replay.payload_sha256 != payload_sha256:
                    raise IdempotencyConflictError(
                        "demo profile idempotency key was reused with different input"
                    )
                return replay.profile_index
            if any(
                journey.session_id == session_id
                and journey.namespace is SessionNamespace.DRIVER
                and journey.parking_lot_id == parking_lot_id
                and journey.state in ACTIVE_STATES
                for journey in self._journeys.values()
            ):
                raise ActiveJourneyConflictError(
                    "driver demo profile cannot change during an active journey"
                )
            if current_state_version != expected_state_version:
                raise VersionConflictError("driver demo facility state is stale")
            current = self.driver_demo_profile_index(
                session_id=session_id,
                parking_lot_id=parking_lot_id,
                profile_count=profile_count,
            )
            if current != expected_profile_index:
                raise VersionConflictError("driver demo profile is stale")
            result = (current + 1) % profile_count
            self._driver_demo_profile_indexes[(session_id, parking_lot_id)] = result
            self._clear_driver_demo_unavailable(session_id, parking_lot_id)
            self._driver_demo_profile_idempotency[(session_id, idempotency_key)] = (
                _DemoProfileIdempotencyResult(
                    payload_sha256=payload_sha256,
                    profile_index=result,
                )
            )
            return result

    def advance_driver_demo_profile_after_terminal(
        self, *, journey_id: str, profile_count: int
    ) -> int:
        """Advance once after a normal departure or explicit synthetic demo reset."""

        with self._lock:
            journey = self._require(journey_id)
            current = self.driver_demo_profile_index(
                session_id=journey.session_id,
                parking_lot_id=journey.parking_lot_id,
                profile_count=profile_count,
            )
            if journey_id in self._driver_demo_processed_terminal_journeys:
                return current
            if (
                journey.namespace is not SessionNamespace.DRIVER
                or journey.state is not JourneyState.DEPARTED
                or journey.terminal_reason not in {"NORMAL_DEPARTURE", "DEMO_RESET"}
            ):
                raise IllegalTransitionError(
                    "demo profile auto-advance requires a completed driver journey"
                )
            if any(
                item.session_id == journey.session_id
                and item.namespace is SessionNamespace.DRIVER
                and item.parking_lot_id == journey.parking_lot_id
                and item.state in ACTIVE_STATES
                for item in self._journeys.values()
            ):
                raise ActiveJourneyConflictError(
                    "driver demo profile cannot advance while another journey is active"
                )
            result = (current + 1) % profile_count
            self._driver_demo_profile_indexes[
                (journey.session_id, journey.parking_lot_id)
            ] = result
            self._clear_driver_demo_unavailable(
                journey.session_id, journey.parking_lot_id
            )
            self._driver_demo_processed_terminal_journeys.add(journey_id)
            return result

    def _clear_driver_demo_unavailable(
        self, session_id: str, parking_lot_id: str
    ) -> None:
        for key in tuple(self._unavailable_spaces):
            if (
                key[0] == session_id
                and key[1] is SessionNamespace.DRIVER
                and key[3] == parking_lot_id
            ):
                self._unavailable_spaces.pop(key, None)

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
                    key=lambda item: (
                        item.session_id,
                        item.namespace,
                        item.scenario_id,
                        item.parking_lot_id,
                        item.space_id,
                    ),
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
                for (
                    stored_session,
                    stored_namespace,
                    stored_scenario,
                    stored_lot,
                    space_id,
                ), reason in self._unavailable_spaces.items()
                if stored_session == session_id
                and stored_namespace is namespace
                and stored_scenario == scenario_id
                and stored_lot == parking_lot_id
            }

    def availability_snapshot(
        self,
        *,
        session_id: str,
        namespace: SessionNamespace,
        scopes: tuple[tuple[str, str], ...],
    ) -> SessionAvailabilitySnapshot:
        """Expire due state and capture all requested exclusions in one critical section."""

        if not session_id:
            raise ValueError("session_id is required")
        if len(set(scopes)) != len(scopes):
            raise ValueError("availability scopes must be unique")
        with self._lock:
            self._expire_due_scope(session_id=session_id, namespace=namespace)
            self._collect_idle_scope(session_id=session_id, namespace=namespace)
            self._collect_idle_unavailable_scope(
                session_id=session_id, namespace=namespace
            )
            items = tuple(
                AvailabilityScopeSnapshot(
                    scenario_id=scenario_id,
                    parking_lot_id=parking_lot_id,
                    claimed_space_ids=frozenset(
                        claim.space_id
                        for claim in self._claims.values()
                        if claim.session_id == session_id
                        and claim.namespace is namespace
                        and claim.scenario_id == scenario_id
                        and claim.parking_lot_id == parking_lot_id
                    ),
                    unavailable_space_reasons=tuple(
                        sorted(
                            (space_id, reason)
                            for (
                                stored_session,
                                stored_namespace,
                                stored_scenario,
                                stored_lot,
                                space_id,
                            ), reason in self._unavailable_spaces.items()
                            if stored_session == session_id
                            and stored_namespace is namespace
                            and stored_scenario == scenario_id
                            and stored_lot == parking_lot_id
                        )
                    ),
                )
                for scenario_id, parking_lot_id in scopes
            )
            return SessionAvailabilitySnapshot(
                session_id=session_id,
                namespace=namespace,
                observed_at=self._aware_utc_now(),
                scopes=items,
            )

    def events(self) -> tuple[SessionEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def session_journeys(
        self, session_id: str, namespace: SessionNamespace
    ) -> tuple[JourneyRecord, ...]:
        """Return one session's journeys in deterministic recency order."""

        with self._lock:
            return tuple(
                sorted(
                    (
                        item
                        for item in self._journeys.values()
                        if item.session_id == session_id and item.namespace is namespace
                    ),
                    key=lambda item: (
                        item.updated_at,
                        item.created_at,
                        item.journey_id,
                    ),
                    reverse=True,
                )
            )

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
        payload = {
            "session_id": session_id,
            "namespace": namespace,
            "scenario_id": scenario_id,
            "parking_lot_id": parking_lot_id,
            "journey_id": journey_id,
            "attempt_id": attempt_id,
            "space_id": space_id,
        }
        with self._lock:
            replay = self._replay(session_id, "soft_hold", idempotency_key, payload)
            if replay is not None:
                return replay
            if journey_id in self._journeys:
                raise ActiveJourneyConflictError(f"journey already exists: {journey_id}")
            if namespace is SessionNamespace.DRIVER and any(
                item.session_id == session_id
                and item.namespace is namespace
                and item.state in ACTIVE_STATES
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
            journey = JourneyRecord(
                journey_id=journey_id,
                attempt_id=attempt_id,
                session_id=session_id,
                namespace=namespace,
                scenario_id=scenario_id,
                parking_lot_id=parking_lot_id,
                state=JourneyState.SOFT_HELD,
                version=1,
                space_id=space_id,
                created_at=now_utc,
                updated_at=now_utc,
                expires_at=now_utc + timedelta(seconds=self._timing.soft_hold_ttl_s),
                expires_mono_s=expires_mono,
                last_activity_mono_s=now_mono,
            )
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
        payload = {
            "session_id": session_id,
            "namespace": namespace,
            "scenario_id": scenario_id,
            "parking_lot_id": parking_lot_id,
            "journey_id": journey_id,
            "attempt_id": attempt_id,
        }
        with self._lock:
            replay = self._replay(session_id, "start_waiting", idempotency_key, payload)
            if replay is not None:
                return replay
            if journey_id in self._journeys:
                raise ActiveJourneyConflictError(f"journey already exists: {journey_id}")
            if namespace is SessionNamespace.DRIVER and any(
                item.session_id == session_id
                and item.namespace is namespace
                and item.state in ACTIVE_STATES
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
            self._append_event(None, journey, "WAITING", None)
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
        """Record an explicit waiting retry and atomically claim a recovered space."""

        payload = {
            "journey_id": journey_id,
            "expected_version": expected_version,
            "space_id": space_id,
        }
        with self._lock:
            journey = self._require(journey_id)
            replay = self._replay(
                journey.session_id, "retry_waiting", idempotency_key, payload
            )
            if replay is not None:
                return replay
            self._require_version(journey, expected_version)
            self._require_state(journey, JourneyState.WAITING)
            if space_id is None:
                result = self._transition(
                    journey,
                    JourneyState.WAITING,
                    event_type="WAITING_RETRY_NO_SPACE",
                )
            else:
                claim_key = (
                    journey.session_id,
                    journey.namespace,
                    journey.scenario_id,
                    journey.parking_lot_id,
                    space_id,
                )
                if claim_key in self._unavailable_spaces:
                    raise ResourceClaimConflictError(f"space is unavailable: {space_id}")
                if claim_key in self._claims:
                    raise ResourceClaimConflictError(f"space already claimed: {space_id}")
                self._claims[claim_key] = ResourceClaim(
                    session_id=journey.session_id,
                    namespace=journey.namespace,
                    scenario_id=journey.scenario_id,
                    parking_lot_id=journey.parking_lot_id,
                    space_id=space_id,
                    journey_id=journey.journey_id,
                )
                result = self._transition(
                    journey,
                    JourneyState.SOFT_HELD,
                    expires_in_s=self._timing.soft_hold_ttl_s,
                    event_type="WAITING_RECOVERED",
                    replace_space=True,
                    space_id=space_id,
                )
            self._remember(
                journey.session_id, "retry_waiting", idempotency_key, payload, result
            )
            return result

    def switch_soft_hold(
        self,
        *,
        journey_id: str,
        expected_version: int,
        space_id: str,
        idempotency_key: str,
    ) -> JourneyRecord:
        """Claim an alternative before releasing the valid original soft hold."""

        payload = {
            "journey_id": journey_id,
            "expected_version": expected_version,
            "space_id": space_id,
        }
        with self._lock:
            journey = self._require(journey_id)
            replay = self._replay(
                journey.session_id, "switch_soft_hold", idempotency_key, payload
            )
            if replay is not None:
                return replay
            self._require_version(journey, expected_version)
            self._require_state(journey, JourneyState.SOFT_HELD)
            if self._is_expired(journey):
                result = self._expire(journey, "SOFT_HOLD_EXPIRED")
                self._remember(
                    journey.session_id,
                    "switch_soft_hold",
                    idempotency_key,
                    payload,
                    result,
                )
                return result
            if journey.space_id == space_id:
                raise ValueError("alternative space must differ from the current space")
            new_key = (
                journey.session_id,
                journey.namespace,
                journey.scenario_id,
                journey.parking_lot_id,
                space_id,
            )
            if new_key in self._unavailable_spaces:
                raise ResourceClaimConflictError(f"space is unavailable: {space_id}")
            if new_key in self._claims:
                raise ResourceClaimConflictError(f"space already claimed: {space_id}")
            self._claims[new_key] = ResourceClaim(
                session_id=journey.session_id,
                namespace=journey.namespace,
                scenario_id=journey.scenario_id,
                parking_lot_id=journey.parking_lot_id,
                space_id=space_id,
                journey_id=journey.journey_id,
            )
            self._release_claim(journey)
            result = self._transition(
                journey,
                JourneyState.SOFT_HELD,
                preserve_expiry=True,
                event_type="SOFT_HOLD_SWITCHED",
                replace_space=True,
                space_id=space_id,
            )
            self._remember(
                journey.session_id,
                "switch_soft_hold",
                idempotency_key,
                payload,
                result,
            )
            return result

    def confirm(
        self,
        *,
        journey_id: str,
        accepted: bool,
        expected_version: int,
        idempotency_key: str,
    ) -> JourneyRecord:
        payload = {
            "journey_id": journey_id,
            "accepted": accepted,
            "expected_version": expected_version,
        }
        with self._lock:
            journey = self._require(journey_id)
            replay = self._replay(
                journey.session_id, "confirm", idempotency_key, payload
            )
            if replay is not None:
                return replay
            self._require_version(journey, expected_version)
            self._require_state(journey, JourneyState.SOFT_HELD)
            if self._is_expired(journey):
                result = self._expire(journey, "SOFT_HOLD_EXPIRED")
                self._remember(
                    journey.session_id, "confirm", idempotency_key, payload, result
                )
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
            self._remember(
                journey.session_id, "confirm", idempotency_key, payload, result
            )
            return result

    def start_navigation(
        self,
        *,
        journey_id: str,
        expected_version: int,
        idempotency_key: str,
    ) -> JourneyRecord:
        return self._command_transition(
            command="start_navigation",
            journey_id=journey_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            from_state=JourneyState.SESSION_RESERVED,
            to_state=JourneyState.NAVIGATING,
            preserve_expiry=True,
        )

    def occupy(
        self,
        *,
        journey_id: str,
        expected_version: int,
        idempotency_key: str,
    ) -> JourneyRecord:
        return self._command_transition(
            command="occupy",
            journey_id=journey_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            from_state=JourneyState.NAVIGATING,
            to_state=JourneyState.OCCUPIED,
            preserve_expiry=False,
        )

    def cancel(
        self,
        *,
        journey_id: str,
        expected_version: int,
        idempotency_key: str,
    ) -> JourneyRecord:
        return self._terminal_command(
            command="cancel",
            journey_id=journey_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            allowed_states={
                JourneyState.WAITING,
                JourneyState.SOFT_HELD,
                JourneyState.SESSION_RESERVED,
                JourneyState.NAVIGATING,
            },
            state=JourneyState.CANCELLED,
            reason="USER_CANCELLED",
        )

    def depart(
        self,
        *,
        journey_id: str,
        expected_version: int,
        idempotency_key: str,
    ) -> JourneyRecord:
        return self._terminal_command(
            command="depart",
            journey_id=journey_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            allowed_states={JourneyState.OCCUPIED},
            state=JourneyState.DEPARTED,
            reason="NORMAL_DEPARTURE",
        )

    def reset_demo(
        self,
        *,
        journey_id: str,
        expected_version: int,
        idempotency_key: str,
    ) -> JourneyRecord:
        """End one synthetic driver trip and clear its scoped demo exclusions."""

        payload = {"journey_id": journey_id, "expected_version": expected_version}
        with self._lock:
            journey = self._require(journey_id)
            replay = self._replay(
                journey.session_id, "reset_demo", idempotency_key, payload
            )
            if replay is not None:
                return replay
            self._require_version(journey, expected_version)
            if journey.namespace is not SessionNamespace.DRIVER:
                raise IllegalTransitionError("demo reset requires a driver journey")
            self._require_state(journey, JourneyState.OCCUPIED)
            result = self._terminal(journey, JourneyState.DEPARTED, "DEMO_RESET")
            scoped_keys = tuple(
                key
                for key in self._unavailable_spaces
                if key[:4]
                == (
                    journey.session_id,
                    journey.namespace,
                    journey.scenario_id,
                    journey.parking_lot_id,
                )
            )
            for key in scoped_keys:
                self._unavailable_spaces.pop(key, None)
            self._remember(
                journey.session_id, "reset_demo", idempotency_key, payload, result
            )
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
        payload = {
            "journey_id": journey_id,
            "expected_version": expected_version,
            "outcome": outcome,
            "reason": reason,
        }
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
                result = self._transition(
                    journey,
                    JourneyState.NAVIGATING,
                    preserve_expiry=True,
                    event_type=f"REPLAN_{outcome.upper()}",
                    event_reason=reason,
                )
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
            replay = self._replay(
                journey.session_id, "report_external_occupancy", idempotency_key, payload
            )
            if replay is not None:
                return replay
            self._require_version(journey, expected_version)
            if journey.state in {
                JourneyState.SESSION_RESERVED,
                JourneyState.NAVIGATING,
            } and self._is_expired(journey):
                result = self._expire(journey, f"{journey.state.upper()}_EXPIRED")
                self._remember(
                    journey.session_id,
                    "report_external_occupancy",
                    idempotency_key,
                    payload,
                    result,
                )
                return result
            if journey.state not in {
                JourneyState.SOFT_HELD,
                JourneyState.SESSION_RESERVED,
                JourneyState.NAVIGATING,
            } or journey.space_id is None:
                raise IllegalTransitionError(
                    "external occupancy requires a claimed pre-occupancy journey"
                )
            unavailable_key = (
                journey.session_id,
                journey.namespace,
                journey.scenario_id,
                journey.parking_lot_id,
                journey.space_id,
            )
            self._unavailable_spaces[unavailable_key] = "EXTERNAL_SPACE_OCCUPIED"
            result = self._terminal(
                journey, JourneyState.FAILED, "EXTERNAL_SPACE_OCCUPIED"
            )
            self._remember(
                journey.session_id,
                "report_external_occupancy",
                idempotency_key,
                payload,
                result,
            )
            return result

    def touch_session(self, session_id: str, namespace: SessionNamespace) -> None:
        """Record authenticated session activity without extending hold/reservation deadlines."""

        with self._lock:
            self.expire_due()
            now = self._monotonic()
            for journey in tuple(self._journeys.values()):
                if (
                    journey.session_id == session_id
                    and journey.namespace is namespace
                    and journey.state in ACTIVE_STATES
                ):
                    self._journeys[journey.journey_id] = replace(
                        journey, last_activity_mono_s=now
                    )

    def expire_due(self) -> tuple[JourneyRecord, ...]:
        with self._lock:
            return self._expire_due_scope()

    def collect_idle_sessions(self) -> tuple[JourneyRecord, ...]:
        with self._lock:
            self.expire_due()
            collected = self._collect_idle_scope()
            self._collect_idle_unavailable_scope()
            return collected

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
            if journey.state in {
                JourneyState.SOFT_HELD,
                JourneyState.SESSION_RESERVED,
                JourneyState.NAVIGATING,
            } and self._is_expired(journey):
                expired.append(self._expire(journey, f"{journey.state.upper()}_EXPIRED"))
        return tuple(expired)

    def _collect_idle_scope(
        self,
        *,
        session_id: str | None = None,
        namespace: SessionNamespace | None = None,
    ) -> tuple[JourneyRecord, ...]:
        """Collect active journeys only inside the requested synthetic session scope."""

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
                ttl = (
                    self._timing.driver_idle_ttl_s
                    if journey.namespace is SessionNamespace.DRIVER
                    else self._timing.defense_idle_ttl_s
                )
                if now - journey.last_activity_mono_s >= ttl:
                    collected.append(
                        self._terminal(journey, JourneyState.FAILED, "DEMO_SESSION_GC")
                    )
            return tuple(collected)

    def _collect_idle_unavailable_scope(
        self,
        *,
        session_id: str | None = None,
        namespace: SessionNamespace | None = None,
    ) -> None:
        """Release synthetic scene exclusions after their owning session becomes idle."""

        now = self._monotonic()
        scopes = {
            (session_id, namespace)
            for (
                session_id,
                namespace,
                _scenario_id,
                _parking_lot_id,
                _space_id,
            ) in self._unavailable_spaces
        }
        for stored_session_id, stored_namespace in scopes:
            if session_id is not None and stored_session_id != session_id:
                continue
            if namespace is not None and stored_namespace is not namespace:
                continue
            journeys = tuple(
                item
                for item in self._journeys.values()
                if item.session_id == stored_session_id
                and item.namespace is stored_namespace
            )
            if not journeys or any(item.state in ACTIVE_STATES for item in journeys):
                continue
            ttl = (
                self._timing.driver_idle_ttl_s
                if stored_namespace is SessionNamespace.DRIVER
                else self._timing.defense_idle_ttl_s
            )
            if now - max(item.last_activity_mono_s for item in journeys) < ttl:
                continue
            for key in tuple(self._unavailable_spaces):
                if key[0] == stored_session_id and key[1] is stored_namespace:
                    del self._unavailable_spaces[key]

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
            if from_state in {
                JourneyState.SESSION_RESERVED,
                JourneyState.NAVIGATING,
            } and self._is_expired(journey):
                result = self._expire(journey, f"{from_state.upper()}_EXPIRED")
                self._remember(
                    journey.session_id, command, idempotency_key, payload, result
                )
                return result
            result = self._transition(
                journey,
                to_state,
                preserve_expiry=preserve_expiry,
                event_type=to_state.upper(),
            )
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
        payload = {
            "journey_id": journey_id,
            "expected_version": expected_version,
            "reason": reason,
        }
        with self._lock:
            journey = self._require(journey_id)
            replay = self._replay(journey.session_id, command, idempotency_key, payload)
            if replay is not None:
                return replay
            self._require_version(journey, expected_version)
            if journey.state not in allowed_states:
                raise IllegalTransitionError(
                    f"journey state {journey.state} does not allow {command}"
                )
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
        self._append_event(
            journey,
            result,
            event_type,
            reason if event_reason is None else event_reason,
        )
        return result

    def _terminal(
        self, journey: JourneyRecord, state: JourneyState, reason: str
    ) -> JourneyRecord:
        result = self._transition(
            journey,
            state,
            event_type=state.upper(),
            reason=reason,
        )
        self._release_claim(journey)
        self._tandem_coordination_records.pop(journey.journey_id, None)
        return result

    def _expire(self, journey: JourneyRecord, reason: str) -> JourneyRecord:
        return self._terminal(journey, JourneyState.EXPIRED, reason)

    def _release_claim(self, journey: JourneyRecord) -> None:
        if journey.space_id is None:
            return
        key = (
            journey.session_id,
            journey.namespace,
            journey.scenario_id,
            journey.parking_lot_id,
            journey.space_id,
        )
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
            raise IdempotencyConflictError(
                f"idempotency key {key} was reused with a different payload"
            )
        return previous.result

    def _remember(
        self,
        session_id: str,
        command: str,
        key: str,
        payload: object,
        result: JourneyRecord,
    ) -> None:
        self._idempotency[(session_id, command, key)] = _IdempotencyResult(
            payload_sha256=_sha256(payload), result=result
        )

    def _require(self, journey_id: str) -> JourneyRecord:
        try:
            return self._journeys[journey_id]
        except KeyError as exc:
            raise JourneyNotFoundError(f"unknown journey: {journey_id}") from exc

    @staticmethod
    def _require_version(journey: JourneyRecord, expected: int) -> None:
        if journey.version != expected:
            raise VersionConflictError(
                f"journey version is {journey.version}, expected {expected}"
            )

    @staticmethod
    def _require_state(journey: JourneyRecord, expected: JourneyState) -> None:
        if journey.state is not expected:
            raise IllegalTransitionError(
                f"journey state is {journey.state}, expected {expected}"
            )

    def _is_expired(self, journey: JourneyRecord) -> bool:
        return (
            journey.expires_mono_s is not None
            and self._monotonic() >= journey.expires_mono_s
        )

    def _aware_utc_now(self) -> datetime:
        value = self._utc()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("utc clock must return an aware datetime")
        return value.astimezone(UTC)
