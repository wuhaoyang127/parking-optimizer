"""Immutable resource and snapshot records."""

from dataclasses import dataclass

from parking_opt.domain.records import (
    PositionState,
    VehicleState,
    _require_id,
    _require_non_negative,
)
from parking_opt.domain.records_claims import (
    Action,
    PositionReservation,
    RelocationTransaction,
    ResourceLock,
)


@dataclass(frozen=True, slots=True)
class ExecutorResourceState:
    """Current aggregate relocation-executor resource state."""

    capacity: int
    used: int
    active_action_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.capacity < 1 or not 0 <= self.used <= self.capacity:
            raise ValueError("executor resource use must be within capacity")


@dataclass(frozen=True, slots=True)
class ChannelZoneResourceState:
    """Current aggregate state of one coarse channel resource."""

    channel_zone_id: str
    capacity: int
    used: int
    active_action_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_id("channel_zone_id", self.channel_zone_id)
        if self.capacity < 1 or not 0 <= self.used <= self.capacity:
            raise ValueError("channel-zone use must be within capacity")


@dataclass(frozen=True, slots=True)
class PendingRequest:
    """Visible pending request with replay-stable ordering fields."""

    request_id: str
    anonymous_vehicle_id: str
    request_type: str
    requested_at_s: int
    event_sequence_no: int
    entrance_node_id: str | None

    def __post_init__(self) -> None:
        _require_id("request_id", self.request_id)
        _require_id("anonymous_vehicle_id", self.anonymous_vehicle_id)
        _require_non_negative("requested_at_s", self.requested_at_s)
        if self.event_sequence_no < 1:
            raise ValueError("event_sequence_no must be at least 1")


@dataclass(frozen=True, slots=True)
class ObservedSnapshot:
    """Immutable allow-list projection supplied to a decision policy."""

    schema_version: str
    snapshot_id: str
    snapshot_content_sha256: str
    run_id: str
    scenario_id: str
    layout_id: str
    decision_time_s: int
    vehicles: tuple[VehicleState, ...]
    positions: tuple[PositionState, ...]
    reservations: tuple[PositionReservation, ...]
    locks: tuple[ResourceLock, ...]
    actions: tuple[Action, ...]
    transactions: tuple[RelocationTransaction, ...]
    executor_resource: ExecutorResourceState
    channel_zone_resources: tuple[ChannelZoneResourceState, ...]
    pending_requests: tuple[PendingRequest, ...]

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise ValueError("ObservedSnapshot requires schema_version 1.0.0")
        for field_name, value in (
            ("snapshot_id", self.snapshot_id),
            ("run_id", self.run_id),
            ("scenario_id", self.scenario_id),
            ("layout_id", self.layout_id),
        ):
            _require_id(field_name, value)
        _require_non_negative("decision_time_s", self.decision_time_s)
