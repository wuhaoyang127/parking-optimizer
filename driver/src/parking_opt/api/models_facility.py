"""Facility layout component models for the web-v2 contract."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from parking_opt.api.models import (
    ContractModel,
    FacilitySourceKind,
    HealthStatus,
    Identifier,
)
from parking_opt.api.models_discovery import Coordinate


class FacilityProvenance(ContractModel):
    source_kind: FacilitySourceKind
    source_name: str = Field(min_length=1, max_length=100)
    source_revision: Identifier
    published_at: AwareDatetime


class FacilitySourceStatus(ContractModel):
    source_kind: FacilitySourceKind
    health: HealthStatus
    source_name: str = Field(min_length=1, max_length=100)
    missing_fields: tuple[str, ...] = ()
    updated_at: AwareDatetime
    fail_reason: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def require_failure_evidence(self) -> FacilitySourceStatus:
        if self.health is HealthStatus.HEALTHY and (self.missing_fields or self.fail_reason):
            raise ValueError("healthy facility source cannot contain failure evidence")
        if self.health is not HealthStatus.HEALTHY and not (self.missing_fields or self.fail_reason):
            raise ValueError("non-healthy facility source requires failure evidence")
        return self


class FacilityBounds(ContractModel):
    min_x_m: float
    min_y_m: float
    max_x_m: float
    max_y_m: float

    @model_validator(mode="after")
    def require_positive_extent(self) -> FacilityBounds:
        if self.min_x_m >= self.max_x_m or self.min_y_m >= self.max_y_m:
            raise ValueError("facility bounds must have positive width and height")
        return self

    def contains(self, coordinate: Coordinate) -> bool:
        return self.min_x_m <= coordinate.x_m <= self.max_x_m and self.min_y_m <= coordinate.y_m <= self.max_y_m


class FacilityImageRegistration(ContractModel):
    pixel_width: Annotated[int, Field(ge=1)]
    pixel_height: Annotated[int, Field(ge=1)]
    meters_to_pixels_affine: tuple[float, float, float, float, float, float]


class FacilityFloor(ContractModel):
    floor_id: Identifier
    label: str = Field(min_length=1, max_length=80)
    elevation_m: float
    bounds: FacilityBounds


class FacilityZone(ContractModel):
    zone_id: Identifier
    floor_id: Identifier
    label: str = Field(min_length=1, max_length=80)
    kind: Literal["parking", "charging", "tandem", "buffer", "restricted", "service", "pedestrian"]
    polygon: tuple[Coordinate, ...] = Field(min_length=3)


class FacilityRestrictedArea(ContractModel):
    area_id: Identifier
    floor_id: Identifier
    label: str = Field(min_length=1, max_length=80)
    polygon: tuple[Coordinate, ...] = Field(min_length=3)


class FacilityNode(ContractModel):
    node_id: Identifier
    floor_id: Identifier
    coordinate: Coordinate
    kind: Literal["entrance", "exit", "junction", "space_access", "buffer_access", "inter_floor"]
    label: str = Field(min_length=1, max_length=80)


class FacilityEdge(ContractModel):
    edge_id: Identifier
    from_node_id: Identifier
    to_node_id: Identifier
    centerline: tuple[Coordinate, ...] = Field(min_length=2)
    width_m: Annotated[float, Field(gt=0)]
    distance_m: Annotated[float, Field(gt=0)]
    base_travel_time_s: Annotated[float, Field(gt=0)]
    directed: bool = False
    traversal_kind: Literal["drive", "ramp", "lift"] = "drive"
    channel_zone_ids: tuple[Identifier, ...] = ()


class FacilityEntrance(ContractModel):
    entrance_id: Identifier
    node_id: Identifier
    label: str = Field(min_length=1, max_length=80)
    initial_heading_deg: Annotated[float, Field(ge=0, lt=360)]


class FacilityExit(ContractModel):
    exit_id: Identifier
    node_id: Identifier
    label: str = Field(min_length=1, max_length=80)


class FacilityRectangle(ContractModel):
    center: Coordinate
    width_m: Annotated[float, Field(gt=0)]
    length_m: Annotated[float, Field(gt=0)]
    heading_deg: Annotated[float, Field(ge=0, lt=360)]


class FacilitySpace(ContractModel):
    parking_lot_id: Identifier
    space_id: Identifier
    floor_id: Identifier
    zone_id: Identifier
    geometry: FacilityRectangle
    access_node_id: Identifier
    charging: bool = False
    stack_group_id: Identifier | None = None
    depth: Annotated[int, Field(ge=1)] = 1

    @model_validator(mode="after")
    def require_stack_depth(self) -> FacilitySpace:
        if self.stack_group_id is None and self.depth != 1:
            raise ValueError("independent facility space must have depth 1")
        return self


class FacilityBuffer(ContractModel):
    parking_lot_id: Identifier
    buffer_id: Identifier
    floor_id: Identifier
    zone_id: Identifier
    geometry: FacilityRectangle
    access_node_id: Identifier
    purpose: Literal["tandem_recovery"] = "tandem_recovery"
    stack_group_ids: tuple[Identifier, ...] = Field(min_length=1)


class FacilityTandemGroup(ContractModel):
    stack_group_id: Identifier
    space_ids_near_to_deep: tuple[Identifier, ...] = Field(min_length=2)
    buffer_ids: tuple[Identifier, ...] = Field(min_length=1)


class FacilityInterFloorConnection(ContractModel):
    connection_id: Identifier
    from_floor_id: Identifier
    to_floor_id: Identifier
    kind: Literal["ramp", "lift"]
    edge_ids: tuple[Identifier, ...] = Field(min_length=1)
