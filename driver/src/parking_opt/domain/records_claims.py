"""Immutable claim, action, and relocation-transaction records."""

from dataclasses import dataclass

from parking_opt.domain.enums import (
    ActionStatus,
    ActionType,
    ExecutorType,
    PositionConfirmation,
    TransactionStatus,
)
from parking_opt.domain.records import _require_id, _require_non_negative


@dataclass(frozen=True, slots=True)
class PositionReservation:
    """Vehicle-owned position-capacity claim."""

    reservation_id: str
    position_id: str
    owner_vehicle_id: str
    transaction_id: str | None
    purpose: str
    created_at_s: int

    def __post_init__(self) -> None:
        for name, value in (
            ("reservation_id", self.reservation_id),
            ("position_id", self.position_id),
            ("owner_vehicle_id", self.owner_vehicle_id),
        ):
            _require_id(name, value)
        _require_non_negative("created_at_s", self.created_at_s)
        if self.purpose not in {
            "admitted_assignment",
            "buffer_destination",
            "restore_original",
        }:
            raise ValueError("purpose must be an approved position-reservation purpose")


@dataclass(frozen=True, slots=True)
class ResourceLock:
    """Transaction-owned access lock that does not consume position capacity."""

    lock_id: str
    resource_type: str
    resource_id: str
    transaction_id: str
    created_at_s: int

    def __post_init__(self) -> None:
        for name, value in (
            ("lock_id", self.lock_id),
            ("resource_id", self.resource_id),
            ("transaction_id", self.transaction_id),
        ):
            _require_id(name, value)
        _require_non_negative("created_at_s", self.created_at_s)
        if self.resource_type not in {
            "vehicle",
            "position",
            "stack_group",
            "channel_zone",
        }:
            raise ValueError("resource_type must be an approved lock resource type")


@dataclass(frozen=True, slots=True)
class Action:
    """Validated immutable action record, not an execution command."""

    action_id: str
    transaction_id: str | None
    anonymous_vehicle_id: str
    action_type: ActionType
    status: ActionStatus
    origin_position_id: str | None
    destination_position_id: str | None
    destination_exit_id: str | None
    distance_m: float
    modeled_duration_s: int
    executor_type: ExecutorType
    executor_units: int
    channel_zone_ids: tuple[str, ...]
    reason: str = "confirmed movement"
    distance_value_source: str = "modeled"
    duration_value_source: str = "modeled"
    recommended_at_s: int = 0
    accepted_at_s: int | None = None
    started_at_s: int | None = None
    ended_at_s: int | None = None
    failure_reason: str | None = None
    position_confirmation: PositionConfirmation = PositionConfirmation.NOT_REQUIRED

    def __post_init__(self) -> None:
        _require_id("action_id", self.action_id)
        _require_id("anonymous_vehicle_id", self.anonymous_vehicle_id)
        _require_non_negative("distance_m", self.distance_m)
        _require_non_negative("modeled_duration_s", self.modeled_duration_s)
        _require_non_negative("executor_units", self.executor_units)
        _require_non_negative("recommended_at_s", self.recommended_at_s)
        for field_name, value in (
            ("accepted_at_s", self.accepted_at_s),
            ("started_at_s", self.started_at_s),
            ("ended_at_s", self.ended_at_s),
        ):
            if value is not None:
                _require_non_negative(field_name, value)
        if not self.reason:
            raise ValueError("reason must be non-empty")
        if self.distance_value_source not in {"modeled", "measured"}:
            raise ValueError("distance_value_source must be modeled or measured")
        if self.duration_value_source not in {"modeled", "measured"}:
            raise ValueError("duration_value_source must be modeled or measured")
        if len(set(self.channel_zone_ids)) != len(self.channel_zone_ids):
            raise ValueError("channel_zone_ids must be unique")
        if self.status is ActionStatus.FAILED and self.failure_reason is None:
            raise ValueError("FAILED action requires failure_reason")
        if self.status is not ActionStatus.FAILED and self.failure_reason is not None:
            raise ValueError("only FAILED action may contain failure_reason")


@dataclass(frozen=True, slots=True)
class BufferAssignment:
    """One blocker, its original normal position, and its dedicated buffer."""

    blocker_vehicle_id: str
    original_position_id: str
    buffer_position_id: str

    def __post_init__(self) -> None:
        for name, value in (
            ("blocker_vehicle_id", self.blocker_vehicle_id),
            ("original_position_id", self.original_position_id),
            ("buffer_position_id", self.buffer_position_id),
        ):
            _require_id(name, value)


@dataclass(frozen=True, slots=True)
class PrecedenceEdge:
    """Immediate physical predecessor relation between transaction actions."""

    before_action_id: str
    after_action_id: str


@dataclass(frozen=True, slots=True)
class RelocationTransaction:
    """Passive relocation transaction value."""

    transaction_id: str
    target_vehicle_id: str
    status: TransactionStatus
    blocker_vehicle_ids: tuple[str, ...]
    buffer_assignments: tuple[BufferAssignment, ...]
    action_ids: tuple[str, ...]
    precedence_edges: tuple[PrecedenceEdge, ...]
    created_at_s: int
    ended_at_s: int | None

    def __post_init__(self) -> None:
        _require_id("transaction_id", self.transaction_id)
        _require_id("target_vehicle_id", self.target_vehicle_id)
        if not self.blocker_vehicle_ids:
            raise ValueError("a passive relocation transaction requires blockers")
        if len(set(self.blocker_vehicle_ids)) != len(self.blocker_vehicle_ids):
            raise ValueError("blocker_vehicle_ids must be unique")
        if tuple(item.blocker_vehicle_id for item in self.buffer_assignments) != (
            self.blocker_vehicle_ids
        ):
            raise ValueError("buffer assignments must follow blocker order")
