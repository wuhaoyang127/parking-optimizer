"""Facility state, route, and request models for the web-v2 contract."""
from __future__ import annotations
from datetime import UTC, datetime
from itertools import pairwise
from typing import Annotated, Any, Literal
from pydantic import AwareDatetime, Field, model_validator
from parking_opt.api.models import (
    SCHEMA_VERSION,
    ContractModel,
    DataMode,
    FacilityClaimStatus,
    FacilityObservationSource,
    FacilitySourceKind,
    HealthStatus,
    Identifier,
    NonNegativeMeters,
    NonNegativeSeconds,
    SpaceStatus,
)
from parking_opt.api.models_facility import FacilitySourceStatus
from parking_opt.api.models_facility_layout import ParkingFacilityLayout
class FacilitySpaceState(ContractModel):
    space_id: Identifier
    observed_status: SpaceStatus
    observation_source: FacilityObservationSource
    claim_status: FacilityClaimStatus = FacilityClaimStatus.NONE
    effective_status: SpaceStatus
    assignable: bool
    reason_codes: tuple[Identifier, ...] = ()
    @model_validator(mode="after")
    def verify_effective_state(self) -> FacilitySpaceState:
        if self.observed_status is SpaceStatus.UNKNOWN:
            if self.effective_status is not SpaceStatus.UNKNOWN or self.assignable:
                raise ValueError("unknown observation must fail closed")
        elif self.observed_status in {SpaceStatus.OCCUPIED, SpaceStatus.UNAVAILABLE}:
            if self.effective_status is not self.observed_status or self.assignable:
                raise ValueError("occupied or unavailable observation cannot be overridden")
        if self.claim_status is not FacilityClaimStatus.NONE:
            if self.observed_status is not SpaceStatus.AVAILABLE:
                raise ValueError("claims require an available observation")
            if self.effective_status is not SpaceStatus.UNAVAILABLE or self.assignable:
                raise ValueError("claimed spaces must be effectively unavailable")
        elif self.observed_status is SpaceStatus.AVAILABLE and self.effective_status is not SpaceStatus.AVAILABLE:
            raise ValueError("unclaimed available observation must remain effectively available")
        if self.assignable:
            if self.observed_status is not SpaceStatus.AVAILABLE or self.effective_status is not SpaceStatus.AVAILABLE or self.claim_status is not FacilityClaimStatus.NONE or self.reason_codes:
                raise ValueError("assignable state must be unclaimed, available, and reason-free")
        elif not self.reason_codes:
            raise ValueError("non-assignable state requires at least one reason code")
        return self
class FacilityBufferState(ContractModel):
    buffer_id: Identifier
    status: SpaceStatus
    observation_source: FacilityObservationSource
    reason_codes: tuple[Identifier, ...] = ()
    @model_validator(mode="after")
    def require_unavailable_reason(self) -> FacilityBufferState:
        if self.status in {SpaceStatus.UNAVAILABLE, SpaceStatus.UNKNOWN} and not self.reason_codes:
            raise ValueError("unavailable or unknown buffer requires a reason code")
        return self
class DriverDemoProfile(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    profile_id: Identifier
    label: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=200)
    ordinal: Annotated[int, Field(ge=1)]
    total: Annotated[int, Field(ge=1)]
    @model_validator(mode="after")
    def verify_position(self) -> DriverDemoProfile:
        if self.ordinal > self.total:
            raise ValueError("demo profile ordinal cannot exceed total")
        return self
class ParkingFacilityStateSnapshot(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    parking_lot_id: Identifier
    layout_version: Identifier
    scenario_id: Identifier
    scenario_version: Identifier
    state_version: Identifier
    observed_at: AwareDatetime
    source: FacilitySourceStatus
    demo_profile: DriverDemoProfile | None = None
    spaces: tuple[FacilitySpaceState, ...] = Field(min_length=1)
    buffers: tuple[FacilityBufferState, ...] = ()
    @model_validator(mode="after")
    def verify_state_identity(self) -> ParkingFacilityStateSnapshot:
        space_ids = [item.space_id for item in self.spaces]
        if len(space_ids) != len(set(space_ids)):
            raise ValueError("facility state repeats a space")
        buffer_ids = [item.buffer_id for item in self.buffers]
        if len(buffer_ids) != len(set(buffer_ids)):
            raise ValueError("facility state repeats a buffer")
        if set(space_ids) & set(buffer_ids):
            raise ValueError("facility state space and buffer ids must not overlap")
        if self.source.health is HealthStatus.UNAVAILABLE:
            raise ValueError("unavailable facility source cannot produce a state snapshot")
        if self.demo_profile is not None and self.source.source_kind is not FacilitySourceKind.SYNTHETIC:
            raise ValueError("demo profile requires a synthetic facility source")
        observations: tuple[FacilityObservationSource, ...] = (
            *(item.observation_source for item in self.spaces),
            *(item.observation_source for item in self.buffers),
        )
        if self.source.source_kind is FacilitySourceKind.REAL:
            if self.source.health is not HealthStatus.HEALTHY:
                raise ValueError("real facility source must be healthy")
            if any(item is not FacilityObservationSource.OBSERVATION for item in observations):
                raise ValueError("real facility state cannot contain synthetic or override truth")
        if self.source.source_kind is FacilitySourceKind.IMPORTED and any(item is FacilityObservationSource.SYNTHETIC_TRUTH for item in observations):
            raise ValueError("imported facility state cannot contain synthetic truth")
        return self
    def require_layout(self, layout: ParkingFacilityLayout) -> ParkingFacilityStateSnapshot:
        if self.parking_lot_id != layout.parking_lot_id:
            raise ValueError("facility state belongs to another parking lot")
        if self.layout_version != layout.layout_version:
            raise ValueError("facility state layout version mismatch")
        if {item.space_id for item in self.spaces} != {item.space_id for item in layout.spaces}:
            raise ValueError("facility state must cover layout spaces exactly")
        if {item.buffer_id for item in self.buffers} != {item.buffer_id for item in layout.buffers}:
            raise ValueError("facility state must cover layout buffers exactly")
        return self


class RoutePreviewRequest(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    layout_version: Identifier
    scenario_version: Identifier
    state_version: Identifier
    entrance_id: Identifier
    target_space_id: Identifier
class CostSnapshot(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    parking_lot_id: Identifier
    layout_version: Identifier
    cost_version: Identifier
    observed_at: AwareDatetime
    edge_travel_time_s: dict[Identifier, Annotated[float, Field(gt=0)]]
    unavailable_edge_ids: tuple[Identifier, ...] = ()
    @model_validator(mode="after")
    def verify_unavailable_edges(self) -> CostSnapshot:
        if len(set(self.unavailable_edge_ids)) != len(self.unavailable_edge_ids):
            raise ValueError("unavailable_edge_ids must be unique")
        unknown = set(self.unavailable_edge_ids) - set(self.edge_travel_time_s)
        if unknown:
            raise ValueError(f"unavailable edges lack travel-time values: {sorted(unknown)}")
        return self
class ChannelLoadSnapshot(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    parking_lot_id: Identifier
    layout_version: Identifier
    observed_at: AwareDatetime
    active_units_by_zone: dict[Identifier, Annotated[int, Field(ge=0)]]
class DriverRequest(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    request_id: Identifier
    idempotency_key: Identifier
    session_id: Identifier
    parking_lot_id: Identifier
    entrance_node_id: Identifier
    requires_charging: bool = False
    requested_at: AwareDatetime
    expected_departure_at: AwareDatetime | None = None
    @model_validator(mode="after")
    def verify_departure_time(self) -> DriverRequest:
        if self.requested_at < datetime(1970, 1, 1, tzinfo=UTC):
            raise ValueError("requested_at cannot be earlier than the Unix epoch")
        if self.expected_departure_at is not None and self.expected_departure_at <= self.requested_at:
            raise ValueError("expected_departure_at must be later than requested_at")
        return self
class RecommendationRequest(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    algorithm_id: Identifier = "online-rule-v2"
    driver: DriverRequest
class HealthResponse(ContractModel):
    status: Literal["ok"] = "ok"
    api_version: Literal["2.0.0"] = SCHEMA_VERSION
    data_mode: DataMode
class ErrorResponse(ContractModel):
    code: Identifier
    message: str = Field(min_length=1, max_length=300)
    details: tuple[dict[str, Any], ...] = ()
    request_id: Identifier
class RouteInstruction(ContractModel):
    sequence: Annotated[int, Field(ge=1)]
    edge_id: Identifier
    text: str = Field(min_length=1, max_length=160)
    distance_m: NonNegativeMeters
    travel_time_s: NonNegativeSeconds
class Route(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    parking_lot_id: Identifier
    layout_version: Identifier
    cost_version: Identifier
    from_node_id: Identifier
    to_node_id: Identifier
    node_ids: tuple[Identifier, ...] = Field(min_length=1)
    edge_ids: tuple[Identifier, ...]
    distance_m: NonNegativeMeters
    dynamic_eta_s: NonNegativeSeconds
    instructions: tuple[RouteInstruction, ...]
