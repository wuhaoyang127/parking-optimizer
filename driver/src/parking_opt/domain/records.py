"""Immutable v1 domain records.

These values model contract data only. State transition behavior starts in C2.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from parking_opt.domain.enums import (
    ActionStatus,
    ActionType,
    ArrivalStatus,
    DepartureInformationSource,
    DepartureStatus,
    ExecutorType,
    LocationKind,
    ManualStatus,
    PositionConfirmation,
    PositionKind,
    PrimaryDecision,
    ReservationStatus,
    SolverStatus,
    TransactionStatus,
    ValidationStatus,
)


def _require_id(field_name: str, value: str) -> None:
    if not value or len(value) > 128:
        raise ValueError(f"{field_name} must be a non-empty ID of at most 128 characters")


def _require_non_negative(field_name: str, value: int | float) -> None:
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")


def freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    """Recursively copy JSON-like mappings into immutable containers."""

    def freeze(item: Any) -> Any:
        if isinstance(item, Mapping):
            return MappingProxyType({str(key): freeze(child) for key, child in item.items()})
        if isinstance(item, list | tuple):
            return tuple(freeze(child) for child in item)
        return item

    return MappingProxyType({str(key): freeze(child) for key, child in value.items()})


@dataclass(frozen=True, slots=True)
class DepartureInformation:
    """Expected departure information with explicit provenance and visibility time."""

    expected_departure_time_s: int | None
    source: DepartureInformationSource
    known_at_time_s: int
    source_record_id: str | None = None
    model_id: str | None = None
    generated_at_time_s: int | None = None
    training_data_cutoff_s: int | None = None
    feature_window_end_s: int | None = None

    def __post_init__(self) -> None:
        _require_non_negative("known_at_time_s", self.known_at_time_s)
        if self.expected_departure_time_s is not None:
            _require_non_negative("expected_departure_time_s", self.expected_departure_time_s)
        if self.source is DepartureInformationSource.UNKNOWN:
            if self.expected_departure_time_s is not None:
                raise ValueError("unknown departure information must not contain an expected time")
        if self.source is DepartureInformationSource.MODEL_PREDICTION:
            values = (
                self.training_data_cutoff_s,
                self.feature_window_end_s,
                self.generated_at_time_s,
            )
            if self.model_id is None or any(value is None for value in values):
                raise ValueError("model_prediction requires model and generation lineage")
            cutoff, window_end, generated = values
            assert cutoff is not None and window_end is not None and generated is not None
            if not cutoff <= window_end <= generated <= self.known_at_time_s:
                raise ValueError("model_prediction lineage times are not monotonic")


@dataclass(frozen=True, slots=True)
class LocationState:
    """Exactly one physical vehicle location state."""

    kind: LocationKind
    position_id: str | None = None
    action_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind is LocationKind.AT_POSITION:
            if self.position_id is None or self.action_id is not None:
                raise ValueError("AT_POSITION requires only position_id")
            _require_id("position_id", self.position_id)
        elif self.kind in {LocationKind.IN_TRANSIT, LocationKind.POSITION_UNCERTAIN}:
            if self.action_id is None or self.position_id is not None:
                raise ValueError(f"{self.kind} requires only action_id")
            _require_id("action_id", self.action_id)
        elif self.position_id is not None or self.action_id is not None:
            raise ValueError(f"{self.kind} must not contain position_id or action_id")


@dataclass(frozen=True, slots=True)
class VehicleState:
    """Vehicle location and orthogonal service states."""

    anonymous_vehicle_id: str
    location_state: LocationState
    arrival_status: ArrivalStatus
    departure_status: DepartureStatus
    manual_status: ManualStatus
    ever_admitted: bool
    admitted_at_s: int | None
    waiting_since_s: int | None
    action_context_id: str | None
    active_transaction_id: str | None
    reservation_status: ReservationStatus
    departure_information: DepartureInformation

    def __post_init__(self) -> None:
        _require_id("anonymous_vehicle_id", self.anonymous_vehicle_id)
        if self.ever_admitted and self.arrival_status is ArrivalStatus.REJECTED:
            raise ValueError("an admitted vehicle cannot later be rejected")
        if self.location_state.kind is LocationKind.REJECTED:
            if self.arrival_status is not ArrivalStatus.REJECTED:
                raise ValueError("REJECTED location requires REJECTED arrival status")
        elif self.arrival_status is ArrivalStatus.REJECTED:
            raise ValueError("REJECTED arrival status requires REJECTED location")
        if self.departure_status is DepartureStatus.COMPLETED:
            if self.location_state.kind is not LocationKind.EXITED:
                raise ValueError("completed departure requires EXITED location")


@dataclass(frozen=True, slots=True)
class PositionState:
    """Physical and business availability for one normal or buffer position."""

    position_id: str
    position_kind: PositionKind
    physically_available: bool
    assignable: bool
    planned_closure: bool
    occupant_vehicle_id: str | None

    def __post_init__(self) -> None:
        _require_id("position_id", self.position_id)
        if self.position_kind is PositionKind.BUFFER and self.assignable:
            raise ValueError("buffer positions cannot be assignable to arriving vehicles")


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


@dataclass(frozen=True, slots=True)
class DecisionRequest:
    """Immutable policy boundary with no path back to simulator truth."""

    request_id: str
    algorithm_id: str
    algorithm_version: str
    trigger_event_id: str
    trigger_event_type: str
    trigger_request_id: str | None
    trigger_anonymous_vehicle_id: str | None
    decision_time_s: int
    layout: Mapping[str, Any]
    approved_config: Mapping[str, Any]
    observed_snapshot: ObservedSnapshot
    config_sha256: str
    layout_sha256: str
    visible_snapshot_sha256: str
    decision_target_s: float
    decision_deadline_s: float

    def __post_init__(self) -> None:
        for field_name, value in (
            ("request_id", self.request_id),
            ("algorithm_id", self.algorithm_id),
            ("algorithm_version", self.algorithm_version),
            ("trigger_event_id", self.trigger_event_id),
        ):
            _require_id(field_name, value)
        _require_non_negative("decision_time_s", self.decision_time_s)
        object.__setattr__(self, "layout", freeze_mapping(self.layout))
        object.__setattr__(self, "approved_config", freeze_mapping(self.approved_config))
        if not 0 < self.decision_target_s <= self.decision_deadline_s:
            raise ValueError("decision target must be positive and no greater than deadline")


@dataclass(frozen=True, slots=True)
class DecisionTiming:
    """Separated timing fields required by the v1 decision result."""

    end_to_end_s: float
    validation_and_modeling_s: float
    solver_s: float
    postsolve_validation_s: float
    minimum_logging_s: float
    solver_time_limit_s: float

    def __post_init__(self) -> None:
        for field_name, value in (
            ("end_to_end_s", self.end_to_end_s),
            ("validation_and_modeling_s", self.validation_and_modeling_s),
            ("solver_s", self.solver_s),
            ("postsolve_validation_s", self.postsolve_validation_s),
            ("minimum_logging_s", self.minimum_logging_s),
            ("solver_time_limit_s", self.solver_time_limit_s),
        ):
            _require_non_negative(field_name, value)


@dataclass(frozen=True, slots=True)
class FallbackRecord:
    """Explicit provenance for a deterministic fallback result."""

    original_method: str
    original_solver_status: SolverStatus
    reason: str
    used_strategy: str
    elapsed_s: float
    result_validation_status: ValidationStatus

    def __post_init__(self) -> None:
        _require_id("original_method", self.original_method)
        _require_id("used_strategy", self.used_strategy)
        if not self.reason:
            raise ValueError("fallback reason must be non-empty")
        _require_non_negative("elapsed_s", self.elapsed_s)


@dataclass(frozen=True, slots=True)
class CandidateGenerationRecord:
    """Bounded rolling-candidate counts and explicit truncation provenance."""

    requests_seen: int
    requests_kept: int
    positions_seen: int
    positions_kept: int
    buffer_matchings_seen: int
    buffer_matchings_kept: int
    action_plans_kept: int
    truncation_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name, value in (
            ("requests_seen", self.requests_seen),
            ("requests_kept", self.requests_kept),
            ("positions_seen", self.positions_seen),
            ("positions_kept", self.positions_kept),
            ("buffer_matchings_seen", self.buffer_matchings_seen),
            ("buffer_matchings_kept", self.buffer_matchings_kept),
            ("action_plans_kept", self.action_plans_kept),
        ):
            _require_non_negative(field_name, value)
        if len(set(self.truncation_reasons)) != len(self.truncation_reasons):
            raise ValueError("truncation_reasons must be unique")
        if any(not item or len(item) > 128 for item in self.truncation_reasons):
            raise ValueError("truncation reasons must contain 1 to 128 characters")


@dataclass(frozen=True, slots=True)
class DecisionResult:
    """Immutable candidate result; it never changes authoritative state."""

    decision_id: str
    request_id: str
    algorithm_id: str
    algorithm_version: str
    config_sha256: str
    layout_sha256: str
    visible_snapshot_sha256: str
    input_model_sha256: str | None
    target_request_id: str
    target_anonymous_vehicle_id: str
    primary_decision: PrimaryDecision
    recommended_actions: tuple[Action, ...]
    candidate_transaction: RelocationTransaction | None
    solver_status: SolverStatus
    fallback_record: FallbackRecord | None
    validation_status: ValidationStatus
    explanation_codes: tuple[str, ...]
    timing: DecisionTiming
    candidate_generation: CandidateGenerationRecord | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("decision_id", self.decision_id),
            ("request_id", self.request_id),
            ("algorithm_id", self.algorithm_id),
            ("algorithm_version", self.algorithm_version),
            ("target_request_id", self.target_request_id),
            ("target_anonymous_vehicle_id", self.target_anonymous_vehicle_id),
        ):
            _require_id(field_name, value)
        if self.primary_decision is PrimaryDecision.RECOMMEND_ACTIONS:
            if not self.recommended_actions:
                raise ValueError("RECOMMEND_ACTIONS requires at least one action")
        elif self.recommended_actions or self.candidate_transaction is not None:
            raise ValueError("non-action decisions cannot contain actions or a transaction")


# Compatibility alias retained for C1 callers that only imported the old name.
DecisionResultStatus = DecisionResult
