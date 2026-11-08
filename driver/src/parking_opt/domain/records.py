"""Immutable v1 domain records.

These values model contract data only. State transition behavior starts in C2.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from parking_opt.domain.enums import (
    ArrivalStatus,
    DepartureInformationSource,
    DepartureStatus,
    LocationKind,
    ManualStatus,
    PositionKind,
    ReservationStatus,
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


from parking_opt.domain.records_claims import (  # noqa: E402
    Action,
    BufferAssignment,
    PositionReservation,
    PrecedenceEdge,
    RelocationTransaction,
    ResourceLock,
)
from parking_opt.domain.records_decision import (  # noqa: E402
    CandidateGenerationRecord,
    DecisionRequest,
    DecisionResult,
    DecisionResultStatus,
    DecisionTiming,
    FallbackRecord,
)
from parking_opt.domain.records_resources import (  # noqa: E402
    ChannelZoneResourceState,
    ExecutorResourceState,
    ObservedSnapshot,
    PendingRequest,
)
