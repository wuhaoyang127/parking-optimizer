"""Discovery, coordinate, and layout models for the web-v2 contract."""
from __future__ import annotations
from typing import Annotated, Literal
from pydantic import AwareDatetime, Field, model_validator
from parking_opt.api.models import (
    SCHEMA_VERSION,
    ContractModel,
    DataMode,
    HealthStatus,
    Identifier,
    SpaceStatus,
)
class DiscoveryPosition(ContractModel):
    x_pct: Annotated[float, Field(ge=0, le=100, description="Horizontal percentage from the area canvas left edge.")]
    y_pct: Annotated[float, Field(ge=0, le=100, description="Vertical percentage from the area canvas top edge.")]
class OffsiteEstimate(ContractModel):
    reference_id: Identifier
    distance_m: Annotated[int, Field(ge=0, description="Source-provided offsite summary distance in metres; not an indoor route.")]
    eta_s: Annotated[int, Field(ge=0, description="Source-provided offsite summary ETA in seconds; not real-road navigation.")]
class DiscoveryReferencePoint(ContractModel):
    reference_id: Identifier
    label: str = Field(min_length=1, max_length=40)
    position: DiscoveryPosition
class DiscoveryLotSummary(ContractModel):
    parking_lot_id: Identifier
    opening_hours_label: str = Field(min_length=1, max_length=80, description="Display-only opening-hours label; clients must not derive opening status from it.")
    position: DiscoveryPosition
    offsite_estimates: tuple[OffsiteEstimate, ...] = Field(min_length=1)
    @model_validator(mode="after")
    def require_unique_reference_estimates(self) -> DiscoveryLotSummary:
        references = [item.reference_id for item in self.offsite_estimates]
        if len(references) != len(set(references)):
            raise ValueError("discovery lot contains duplicate reference estimates")
        return self
class DiscoveryArea(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    area_id: Identifier
    display_version: Identifier
    coordinate_system: Literal["percentage_top_left"] = "percentage_top_left"
    synthetic: bool
    source_mode: DataMode
    source_health: HealthStatus
    default_reference_id: Identifier
    references: tuple[DiscoveryReferencePoint, ...] = Field(min_length=1)
    lots: tuple[DiscoveryLotSummary, ...] = ()
    updated_at: AwareDatetime
    @model_validator(mode="after")
    def verify_discovery_scope(self) -> DiscoveryArea:
        reference_ids = [item.reference_id for item in self.references]
        if len(reference_ids) != len(set(reference_ids)):
            raise ValueError("discovery area contains duplicate reference points")
        if self.default_reference_id not in reference_ids:
            raise ValueError("default discovery reference does not exist")
        lot_ids = [item.parking_lot_id for item in self.lots]
        if len(lot_ids) != len(set(lot_ids)):
            raise ValueError("discovery area contains duplicate parking lots")
        expected_references = set(reference_ids)
        if any({estimate.reference_id for estimate in lot.offsite_estimates} != expected_references for lot in self.lots):
            raise ValueError("every discovery lot must cover every reference point exactly once")
        if self.synthetic != (self.source_mode is DataMode.SYNTHETIC):
            raise ValueError("discovery synthetic flag must agree with source_mode")
        return self
class Coordinate(ContractModel):
    x_m: float
    y_m: float
class RoadNode(ContractModel):
    node_id: Identifier
    coordinate: Coordinate
    kind: Literal["entrance", "exit", "junction", "space_access", "buffer_access"]
    label: str = Field(min_length=1, max_length=80)
class RoadEdge(ContractModel):
    edge_id: Identifier
    from_node_id: Identifier
    to_node_id: Identifier
    distance_m: Annotated[float, Field(gt=0)]
    base_travel_time_s: Annotated[float, Field(gt=0)]
    directed: bool = False
    channel_zone_ids: tuple[Identifier, ...] = ()
class ChannelZone(ContractModel):
    channel_zone_id: Identifier
    capacity: Annotated[int, Field(ge=1)]
class ParkingSpace(ContractModel):
    parking_lot_id: Identifier
    space_id: Identifier
    coordinate: Coordinate
    access_node_id: Identifier
    status: SpaceStatus
    charging: bool = False
    stack_group_id: Identifier
    depth: Annotated[int, Field(ge=1)] = 1
    assignable: bool
    assignability_reasons: tuple[str, ...] = ()
    @model_validator(mode="after")
    def verify_assignability(self) -> ParkingSpace:
        if self.assignable and self.status is not SpaceStatus.AVAILABLE:
            raise ValueError("only available spaces can be assignable")
        if self.assignable and self.assignability_reasons:
            raise ValueError("assignable spaces cannot contain rejection reasons")
        if not self.assignable and not self.assignability_reasons:
            raise ValueError("non-assignable spaces require at least one reason")
        return self
class BufferSpace(ContractModel):
    parking_lot_id: Identifier
    buffer_id: Identifier
    coordinate: Coordinate
    access_node_id: Identifier
    available: bool
    channel_zone_ids: tuple[Identifier, ...] = ()
class TandemGroup(ContractModel):
    stack_group_id: Identifier
    space_ids_near_to_deep: tuple[Identifier, ...] = Field(min_length=2)
