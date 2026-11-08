"""Atomic single-process session state for the web-v2 M3 synthetic prototype."""
from __future__ import annotations
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
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
        if not (len(self.blocker_space_ids) == len(self.blocker_vehicle_ids) == len(self.buffer_ids)):
            raise ValueError("tandem coordination blocker and buffer counts differ")
@dataclass(frozen=True, slots=True)
class AvailabilityScopeSnapshot:
    scenario_id: str
    parking_lot_id: str
    claimed_space_ids: frozenset[str]
    unavailable_space_reasons: tuple[tuple[str, str], ...]
    @property
    def unavailable_space_ids(self) -> frozenset[str]:
        return frozenset(space_id for space_id, _reason in self.unavailable_space_reasons)
@dataclass(frozen=True, slots=True)
class SessionAvailabilitySnapshot:
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
    payload = json.dumps(value, default=default, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
def _journey_sha256(journey: JourneyRecord | None) -> str:
    return ZERO_SHA256 if journey is None else _sha256(asdict(journey))
