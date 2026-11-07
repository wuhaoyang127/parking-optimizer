"""Pydantic source models for the frozen web-v2 transport contract."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from itertools import pairwise
from math import cos, hypot, radians, sin
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION: Literal["2.0.0"] = "2.0.0"

Identifier = Annotated[
    str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
]
VenueType = Literal["school", "hospital", "commercial", "transport_hub"]
NonNegativeSeconds = Annotated[float, Field(ge=0)]
NonNegativeMeters = Annotated[float, Field(ge=0)]


class ContractModel(BaseModel):
    """Immutable, fail-closed base for externally visible v2 values."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


class DataMode(StrEnum):
    SYNTHETIC = "synthetic"
    REAL = "real"


class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class SpaceStatus(StrEnum):
    AVAILABLE = "available"
    OCCUPIED = "occupied"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class FacilitySourceKind(StrEnum):
    SYNTHETIC = "synthetic"
    IMPORTED = "imported"
    REAL = "real"


class FacilityObservationSource(StrEnum):
    SYNTHETIC_TRUTH = "synthetic_truth"
    OBSERVATION = "observation"
    USER_OVERRIDE = "user_override"


class FacilityClaimStatus(StrEnum):
    NONE = "none"
    SOFT_HELD = "soft_held"
    SESSION_RESERVED = "session_reserved"
    NAVIGATING = "navigating"


class AlgorithmStatus(StrEnum):
    ONLINE = "online"
    PENDING = "pending"


class DataSourceStatus(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    parking_lot_id: Identifier
    mode: DataMode
    health: HealthStatus
    source_name: str = Field(min_length=1, max_length=100)
    missing_fields: tuple[str, ...] = ()
    updated_at: AwareDatetime
    fail_reason: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def require_failure_evidence(self) -> DataSourceStatus:
        if self.health is HealthStatus.HEALTHY and (self.missing_fields or self.fail_reason):
            raise ValueError("healthy data source cannot contain missing fields or fail_reason")
        if self.health is not HealthStatus.HEALTHY and not (
            self.missing_fields or self.fail_reason
        ):
            raise ValueError("non-healthy data source requires missing_fields or fail_reason")
        return self


class PricingSummary(ContractModel):
    currency: Literal["CNY"] = "CNY"
    first_hour_yuan: Annotated[float, Field(ge=0)]
    additional_hour_yuan: Annotated[float, Field(ge=0)]
    daily_cap_yuan: Annotated[float, Field(ge=0)] | None = None
    note: str = Field(min_length=1, max_length=160)


class ParkingLot(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    parking_lot_id: Identifier
    name: str = Field(min_length=1, max_length=80)
    region_label: str = Field(min_length=1, max_length=80)
    venue_type: VenueType
    synthetic: bool
    opening_status: Literal["open", "closed", "unknown"]
    total_spaces: Annotated[int, Field(ge=1)]
    available_spaces: Annotated[int, Field(ge=0)]
    charging_spaces: Annotated[int, Field(ge=0)]
    pricing: PricingSummary
    updated_at: AwareDatetime
    data_source: DataSourceStatus

    @model_validator(mode="after")
    def verify_scope_and_counts(self) -> ParkingLot:
        if self.parking_lot_id != self.data_source.parking_lot_id:
            raise ValueError("parking lot and data source scopes differ")
        if self.available_spaces > self.total_spaces:
            raise ValueError("available_spaces cannot exceed total_spaces")
        if self.charging_spaces > self.total_spaces:
            raise ValueError("charging_spaces cannot exceed total_spaces")
        if self.synthetic != (self.data_source.mode is DataMode.SYNTHETIC):
            raise ValueError("synthetic flag must agree with data source mode")
        return self


class DiscoveryPosition(ContractModel):
    x_pct: Annotated[
        float,
        Field(ge=0, le=100, description="Horizontal percentage from the area canvas left edge."),
    ]
    y_pct: Annotated[
        float,
        Field(ge=0, le=100, description="Vertical percentage from the area canvas top edge."),
    ]


class OffsiteEstimate(ContractModel):
    reference_id: Identifier
    distance_m: Annotated[
        int,
        Field(
            ge=0,
            description="Source-provided offsite summary distance in metres; not an indoor route.",
        ),
    ]
    eta_s: Annotated[
        int,
        Field(
            ge=0,
            description="Source-provided offsite summary ETA in seconds; not real-road navigation.",
        ),
    ]


class DiscoveryReferencePoint(ContractModel):
    reference_id: Identifier
    label: str = Field(min_length=1, max_length=40)
    position: DiscoveryPosition


class DiscoveryLotSummary(ContractModel):
    parking_lot_id: Identifier
    opening_hours_label: str = Field(
        min_length=1,
        max_length=80,
        description=(
            "Display-only opening-hours label; clients must not derive opening status from it."
        ),
    )
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
        if any(
            {estimate.reference_id for estimate in lot.offsite_estimates}
            != expected_references
            for lot in self.lots
        ):
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


class Layout(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    parking_lot_id: Identifier
    layout_version: Identifier
    coordinate_system: Literal["local_meters"] = "local_meters"
    coordinate_origin_note: str = Field(min_length=1, max_length=200)
    entrance_node_ids: tuple[Identifier, ...] = Field(min_length=1)
    exit_node_ids: tuple[Identifier, ...] = Field(min_length=1)
    nodes: tuple[RoadNode, ...] = Field(min_length=2)
    edges: tuple[RoadEdge, ...] = Field(min_length=1)
    channel_zones: tuple[ChannelZone, ...]
    spaces: tuple[ParkingSpace, ...] = Field(min_length=1)
    tandem_groups: tuple[TandemGroup, ...] = ()
    buffers: tuple[BufferSpace, ...] = ()

    @model_validator(mode="after")
    def verify_layout_references(self) -> Layout:
        nodes_by_id = {item.node_id: item for item in self.nodes}
        node_ids = set(nodes_by_id)
        if len(node_ids) != len(self.nodes):
            raise ValueError("node ids must be unique")
        if len(set(self.entrance_node_ids)) != len(self.entrance_node_ids):
            raise ValueError("entrance node ids must be unique")
        if len(set(self.exit_node_ids)) != len(self.exit_node_ids):
            raise ValueError("exit node ids must be unique")
        edge_ids = {item.edge_id for item in self.edges}
        if len(edge_ids) != len(self.edges):
            raise ValueError("edge ids must be unique")
        if not set(self.entrance_node_ids + self.exit_node_ids) <= node_ids:
            raise ValueError("entrance and exit nodes must exist")
        if any(nodes_by_id[item_id].kind != "entrance" for item_id in self.entrance_node_ids):
            raise ValueError("entrance_node_ids must reference entrance nodes")
        if any(nodes_by_id[item_id].kind != "exit" for item_id in self.exit_node_ids):
            raise ValueError("exit_node_ids must reference exit nodes")
        if set(self.entrance_node_ids) != {
            item.node_id for item in self.nodes if item.kind == "entrance"
        }:
            raise ValueError("all entrance nodes must be declared in entrance_node_ids")
        if set(self.exit_node_ids) != {
            item.node_id for item in self.nodes if item.kind == "exit"
        }:
            raise ValueError("all exit nodes must be declared in exit_node_ids")
        channel_zone_ids = {item.channel_zone_id for item in self.channel_zones}
        if len(channel_zone_ids) != len(self.channel_zones):
            raise ValueError("channel zone ids must be unique")
        for edge in self.edges:
            if edge.from_node_id not in node_ids or edge.to_node_id not in node_ids:
                raise ValueError(f"edge {edge.edge_id} references an unknown node")
            if len(set(edge.channel_zone_ids)) != len(edge.channel_zone_ids):
                raise ValueError(f"edge {edge.edge_id} repeats a channel zone")
            if not set(edge.channel_zone_ids) <= channel_zone_ids:
                raise ValueError(f"edge {edge.edge_id} references an unknown channel zone")
        space_ids = {item.space_id for item in self.spaces}
        if len(space_ids) != len(self.spaces):
            raise ValueError("space ids must be unique")
        if any(item.parking_lot_id != self.parking_lot_id for item in self.spaces):
            raise ValueError("space belongs to another parking lot")
        for space in self.spaces:
            if space.access_node_id not in node_ids:
                raise ValueError(f"space {space.space_id} references an unknown access node")
        buffer_ids = {item.buffer_id for item in self.buffers}
        if len(buffer_ids) != len(self.buffers):
            raise ValueError("buffer ids must be unique")
        if buffer_ids & space_ids:
            raise ValueError("buffer ids and space ids must not overlap")
        for buffer in self.buffers:
            if buffer.parking_lot_id != self.parking_lot_id:
                raise ValueError(f"buffer {buffer.buffer_id} belongs to another parking lot")
            if buffer.access_node_id not in node_ids:
                raise ValueError(f"buffer {buffer.buffer_id} references an unknown access node")
            if len(set(buffer.channel_zone_ids)) != len(buffer.channel_zone_ids):
                raise ValueError(f"buffer {buffer.buffer_id} repeats a channel zone")
            if not set(buffer.channel_zone_ids) <= channel_zone_ids:
                raise ValueError(f"buffer {buffer.buffer_id} references an unknown channel zone")

        tandem_ids = {item.stack_group_id for item in self.tandem_groups}
        if len(tandem_ids) != len(self.tandem_groups):
            raise ValueError("tandem group ids must be unique")
        grouped: set[str] = set()
        by_id = {item.space_id: item for item in self.spaces}
        spaces_by_group: dict[str, list[ParkingSpace]] = {}
        for space in self.spaces:
            spaces_by_group.setdefault(space.stack_group_id, []).append(space)
        for group in self.tandem_groups:
            if len(set(group.space_ids_near_to_deep)) != len(group.space_ids_near_to_deep):
                raise ValueError(f"tandem group {group.stack_group_id} repeats a space")
            unknown_ids = set(group.space_ids_near_to_deep) - space_ids
            if unknown_ids:
                raise ValueError(
                    f"tandem group {group.stack_group_id} references unknown spaces: "
                    f"{', '.join(sorted(unknown_ids))}"
                )
            if grouped & set(group.space_ids_near_to_deep):
                raise ValueError("a space cannot belong to more than one tandem group")
            declared_group = spaces_by_group.get(group.stack_group_id, [])
            if set(group.space_ids_near_to_deep) != {
                item.space_id for item in declared_group
            }:
                raise ValueError(f"tandem group {group.stack_group_id} membership is incomplete")
            depths = sorted(item.depth for item in declared_group)
            if depths != list(range(1, len(declared_group) + 1)):
                raise ValueError(f"tandem group {group.stack_group_id} depths must be contiguous")
            expected = tuple(
                item.space_id
                for item in sorted(
                    (by_id[item_id] for item_id in group.space_ids_near_to_deep),
                    key=lambda item: item.depth,
                )
            )
            if expected != group.space_ids_near_to_deep:
                raise ValueError(f"tandem group {group.stack_group_id} is not ordered by depth")
            if any(by_id[item_id].stack_group_id != group.stack_group_id for item_id in expected):
                raise ValueError("tandem group membership is inconsistent")
            grouped.update(expected)
        for group_id, members in spaces_by_group.items():
            if len(members) == 1 and members[0].depth != 1:
                raise ValueError(f"independent space group {group_id} must have depth 1")
            if len(members) > 1 and group_id not in tandem_ids:
                raise ValueError(f"stack group {group_id} lacks a tandem group declaration")
        return self


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
        if self.health is not HealthStatus.HEALTHY and not (
            self.missing_fields or self.fail_reason
        ):
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
        return (
            self.min_x_m <= coordinate.x_m <= self.max_x_m
            and self.min_y_m <= coordinate.y_m <= self.max_y_m
        )


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
    kind: Literal[
        "parking", "charging", "tandem", "buffer", "restricted", "service", "pedestrian"
    ]
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
    kind: Literal[
        "entrance", "exit", "junction", "space_access", "buffer_access", "inter_floor"
    ]
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


class ParkingFacilityLayout(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    parking_lot_id: Identifier
    layout_version: Identifier
    provenance: FacilityProvenance
    coordinate_system: Literal["local_meters"] = "local_meters"
    coordinate_origin_note: str = Field(min_length=1, max_length=200)
    bounds: FacilityBounds
    default_floor_id: Identifier
    floors: tuple[FacilityFloor, ...] = Field(min_length=1)
    inter_floor_connections: tuple[FacilityInterFloorConnection, ...] = ()
    zones: tuple[FacilityZone, ...]
    restricted_areas: tuple[FacilityRestrictedArea, ...] = ()
    nodes: tuple[FacilityNode, ...] = Field(min_length=2)
    edges: tuple[FacilityEdge, ...] = Field(min_length=1)
    channel_zones: tuple[ChannelZone, ...]
    entrances: tuple[FacilityEntrance, ...] = Field(min_length=1)
    exits: tuple[FacilityExit, ...] = Field(min_length=1)
    default_entrance_id: Identifier
    spaces: tuple[FacilitySpace, ...] = Field(min_length=1)
    tandem_groups: tuple[FacilityTandemGroup, ...] = ()
    buffers: tuple[FacilityBuffer, ...] = ()
    image_registration: FacilityImageRegistration | None = None

    @model_validator(mode="after")
    def verify_facility_references(self) -> ParkingFacilityLayout:
        def unique(values: tuple[str, ...], label: str) -> set[str]:
            result = set(values)
            if len(result) != len(values):
                raise ValueError(f"{label} ids must be unique")
            return result

        def rectangle_fits(rectangle: FacilityRectangle, bounds: FacilityBounds) -> bool:
            angle = radians(rectangle.heading_deg)
            cosine = cos(angle)
            sine = sin(angle)
            half_width = rectangle.width_m / 2
            half_length = rectangle.length_m / 2
            return all(
                bounds.contains(
                    Coordinate(
                        x_m=rectangle.center.x_m + dx * cosine - dy * sine,
                        y_m=rectangle.center.y_m + dx * sine + dy * cosine,
                    )
                )
                for dx in (-half_width, half_width)
                for dy in (-half_length, half_length)
            )

        floors_by_id = {item.floor_id: item for item in self.floors}
        floor_ids = unique(tuple(floors_by_id), "floor")
        if len(floors_by_id) != len(self.floors):
            raise ValueError("floor ids must be unique")
        if self.default_floor_id not in floor_ids:
            raise ValueError("default floor does not exist")
        for floor in self.floors:
            if not (
                self.bounds.min_x_m <= floor.bounds.min_x_m < floor.bounds.max_x_m
                <= self.bounds.max_x_m
                and self.bounds.min_y_m <= floor.bounds.min_y_m < floor.bounds.max_y_m
                <= self.bounds.max_y_m
            ):
                raise ValueError(f"floor {floor.floor_id} bounds exceed facility bounds")

        zones_by_id = {item.zone_id: item for item in self.zones}
        if len(zones_by_id) != len(self.zones):
            raise ValueError("zone ids must be unique")
        for zone in self.zones:
            if zone.floor_id not in floor_ids:
                raise ValueError(f"zone {zone.zone_id} references an unknown floor")
            if not all(
                floors_by_id[zone.floor_id].bounds.contains(point) for point in zone.polygon
            ):
                raise ValueError(f"zone {zone.zone_id} exceeds its floor bounds")

        area_ids = unique(tuple(item.area_id for item in self.restricted_areas), "area")
        if len(area_ids) != len(self.restricted_areas):
            raise ValueError("restricted area ids must be unique")
        for area in self.restricted_areas:
            if area.floor_id not in floor_ids:
                raise ValueError(f"restricted area {area.area_id} references an unknown floor")
            if not all(floors_by_id[area.floor_id].bounds.contains(p) for p in area.polygon):
                raise ValueError(f"restricted area {area.area_id} exceeds its floor bounds")

        nodes_by_id = {item.node_id: item for item in self.nodes}
        if len(nodes_by_id) != len(self.nodes):
            raise ValueError("facility node ids must be unique")
        for node in self.nodes:
            if node.floor_id not in floor_ids:
                raise ValueError(f"node {node.node_id} references an unknown floor")
            if not floors_by_id[node.floor_id].bounds.contains(node.coordinate):
                raise ValueError(f"node {node.node_id} exceeds its floor bounds")

        edges_by_id = {item.edge_id: item for item in self.edges}
        if len(edges_by_id) != len(self.edges):
            raise ValueError("facility edge ids must be unique")
        channel_zone_ids = unique(
            tuple(item.channel_zone_id for item in self.channel_zones), "channel zone"
        )
        for edge in self.edges:
            if edge.from_node_id not in nodes_by_id or edge.to_node_id not in nodes_by_id:
                raise ValueError(f"edge {edge.edge_id} references an unknown node")
            if len(set(edge.channel_zone_ids)) != len(edge.channel_zone_ids):
                raise ValueError(f"edge {edge.edge_id} repeats a channel zone")
            if not set(edge.channel_zone_ids) <= channel_zone_ids:
                raise ValueError(f"edge {edge.edge_id} references an unknown channel zone")
            if edge.centerline[0] != nodes_by_id[edge.from_node_id].coordinate:
                raise ValueError(f"edge {edge.edge_id} centerline does not start at from node")
            if edge.centerline[-1] != nodes_by_id[edge.to_node_id].coordinate:
                raise ValueError(f"edge {edge.edge_id} centerline does not end at to node")
            centerline_distance = sum(
                hypot(right.x_m - left.x_m, right.y_m - left.y_m)
                for left, right in pairwise(edge.centerline)
            )
            distance_tolerance = max(0.001, edge.distance_m * 0.001)
            if abs(centerline_distance - edge.distance_m) > distance_tolerance:
                raise ValueError(f"edge {edge.edge_id} distance differs from its centerline")
            edge_floors = {
                nodes_by_id[edge.from_node_id].floor_id,
                nodes_by_id[edge.to_node_id].floor_id,
            }
            for point in edge.centerline:
                if not any(
                    floors_by_id[floor_id].bounds.contains(point)
                    for floor_id in edge_floors
                ):
                    raise ValueError(f"edge {edge.edge_id} centerline exceeds connected floors")

        entrance_ids = unique(tuple(item.entrance_id for item in self.entrances), "entrance")
        if self.default_entrance_id not in entrance_ids:
            raise ValueError("default entrance does not exist")
        for entrance in self.entrances:
            entrance_node = nodes_by_id.get(entrance.node_id)
            if entrance_node is None or entrance_node.kind != "entrance":
                raise ValueError(f"entrance {entrance.entrance_id} must reference an entrance node")
        if {item.node_id for item in self.entrances} != {
            item.node_id for item in self.nodes if item.kind == "entrance"
        }:
            raise ValueError("facility entrances must cover entrance nodes exactly")
        if len({item.node_id for item in self.entrances}) != len(self.entrances):
            raise ValueError("facility entrances cannot repeat a node")
        unique(tuple(item.exit_id for item in self.exits), "exit")
        for facility_exit in self.exits:
            exit_node = nodes_by_id.get(facility_exit.node_id)
            if exit_node is None or exit_node.kind != "exit":
                raise ValueError(f"exit {facility_exit.exit_id} must reference an exit node")
        if {item.node_id for item in self.exits} != {
            item.node_id for item in self.nodes if item.kind == "exit"
        }:
            raise ValueError("facility exits must cover exit nodes exactly")
        if len({item.node_id for item in self.exits}) != len(self.exits):
            raise ValueError("facility exits cannot repeat a node")

        spaces_by_id = {item.space_id: item for item in self.spaces}
        if len(spaces_by_id) != len(self.spaces):
            raise ValueError("facility space ids must be unique")
        for space in self.spaces:
            if space.parking_lot_id != self.parking_lot_id:
                raise ValueError(f"space {space.space_id} belongs to another parking lot")
            if space.floor_id not in floor_ids or space.zone_id not in zones_by_id:
                raise ValueError(f"space {space.space_id} references an unknown floor or zone")
            if zones_by_id[space.zone_id].floor_id != space.floor_id:
                raise ValueError(f"space {space.space_id} zone belongs to another floor")
            if space.access_node_id not in nodes_by_id:
                raise ValueError(f"space {space.space_id} references an unknown access node")
            if nodes_by_id[space.access_node_id].kind != "space_access":
                raise ValueError(f"space {space.space_id} must reference a space access node")
            if nodes_by_id[space.access_node_id].floor_id != space.floor_id:
                raise ValueError(f"space {space.space_id} access node belongs to another floor")
            if not rectangle_fits(space.geometry, floors_by_id[space.floor_id].bounds):
                raise ValueError(f"space {space.space_id} exceeds its floor bounds")

        buffers_by_id = {item.buffer_id: item for item in self.buffers}
        if len(buffers_by_id) != len(self.buffers):
            raise ValueError("facility buffer ids must be unique")
        if set(buffers_by_id) & set(spaces_by_id):
            raise ValueError("facility space and buffer ids must not overlap")
        for buffer in self.buffers:
            if buffer.parking_lot_id != self.parking_lot_id:
                raise ValueError(f"buffer {buffer.buffer_id} belongs to another parking lot")
            if len(set(buffer.stack_group_ids)) != len(buffer.stack_group_ids):
                raise ValueError(f"buffer {buffer.buffer_id} repeats a stack group")
            if buffer.floor_id not in floor_ids or buffer.zone_id not in zones_by_id:
                raise ValueError(f"buffer {buffer.buffer_id} references an unknown floor or zone")
            if zones_by_id[buffer.zone_id].floor_id != buffer.floor_id:
                raise ValueError(f"buffer {buffer.buffer_id} zone belongs to another floor")
            buffer_node = nodes_by_id.get(buffer.access_node_id)
            if (
                buffer_node is None
                or buffer_node.kind != "buffer_access"
                or buffer_node.floor_id != buffer.floor_id
            ):
                raise ValueError(f"buffer {buffer.buffer_id} has an invalid access node")
            if not rectangle_fits(buffer.geometry, floors_by_id[buffer.floor_id].bounds):
                raise ValueError(f"buffer {buffer.buffer_id} exceeds its floor bounds")

        groups_by_id = {item.stack_group_id: item for item in self.tandem_groups}
        if len(groups_by_id) != len(self.tandem_groups):
            raise ValueError("facility tandem group ids must be unique")
        grouped_space_ids: set[str] = set()
        for group in self.tandem_groups:
            if len(set(group.space_ids_near_to_deep)) != len(group.space_ids_near_to_deep):
                raise ValueError(f"tandem group {group.stack_group_id} repeats a space")
            if len(set(group.buffer_ids)) != len(group.buffer_ids):
                raise ValueError(f"tandem group {group.stack_group_id} repeats a buffer")
            if not set(group.space_ids_near_to_deep) <= set(spaces_by_id):
                raise ValueError(f"tandem group {group.stack_group_id} references an unknown space")
            if not set(group.buffer_ids) <= set(buffers_by_id):
                raise ValueError(
                    f"tandem group {group.stack_group_id} references an unknown buffer"
                )
            members = [spaces_by_id[item_id] for item_id in group.space_ids_near_to_deep]
            if any(item.stack_group_id != group.stack_group_id for item in members):
                raise ValueError(f"tandem group {group.stack_group_id} membership is inconsistent")
            if [item.depth for item in members] != list(range(1, len(members) + 1)):
                raise ValueError(f"tandem group {group.stack_group_id} depths must be contiguous")
            if grouped_space_ids & set(group.space_ids_near_to_deep):
                raise ValueError("a facility space cannot belong to multiple tandem groups")
            grouped_space_ids.update(group.space_ids_near_to_deep)
            for buffer_id in group.buffer_ids:
                if group.stack_group_id not in buffers_by_id[buffer_id].stack_group_ids:
                    raise ValueError(f"buffer {buffer_id} does not declare tandem group")
        declared_grouped = {
            item.space_id for item in self.spaces if item.stack_group_id is not None
        }
        if grouped_space_ids != declared_grouped:
            raise ValueError("facility tandem declarations do not cover grouped spaces exactly")
        for buffer in self.buffers:
            if not set(buffer.stack_group_ids) <= set(groups_by_id):
                raise ValueError(f"buffer {buffer.buffer_id} references an unknown tandem group")
            if any(
                buffer.buffer_id not in groups_by_id[group_id].buffer_ids
                for group_id in buffer.stack_group_ids
            ):
                raise ValueError(
                    f"buffer {buffer.buffer_id} tandem declarations are not reciprocal"
                )

        connection_ids = unique(
            tuple(item.connection_id for item in self.inter_floor_connections),
            "inter-floor connection",
        )
        if len(connection_ids) != len(self.inter_floor_connections):
            raise ValueError("inter-floor connection ids must be unique")
        inter_floor_edge_ids: set[str] = set()
        for connection in self.inter_floor_connections:
            if (
                connection.from_floor_id not in floor_ids
                or connection.to_floor_id not in floor_ids
            ):
                raise ValueError(
                    f"connection {connection.connection_id} references an unknown floor"
                )
            if connection.from_floor_id == connection.to_floor_id:
                raise ValueError(
                    f"connection {connection.connection_id} must join different floors"
                )
            if not set(connection.edge_ids) <= set(edges_by_id):
                raise ValueError(
                    f"connection {connection.connection_id} references an unknown edge"
                )
            for edge_id in connection.edge_ids:
                edge = edges_by_id[edge_id]
                if edge.traversal_kind != connection.kind:
                    raise ValueError(
                        f"connection {connection.connection_id} traversal kind mismatch"
                    )
                edge_floor_pair = (
                    nodes_by_id[edge.from_node_id].floor_id,
                    nodes_by_id[edge.to_node_id].floor_id,
                )
                declared_pair = (connection.from_floor_id, connection.to_floor_id)
                if edge.directed and edge_floor_pair != declared_pair:
                    raise ValueError(
                        f"connection {connection.connection_id} direction mismatch"
                    )
                if not edge.directed and set(edge_floor_pair) != set(declared_pair):
                    raise ValueError(
                        f"connection {connection.connection_id} floor mismatch"
                    )
            if inter_floor_edge_ids & set(connection.edge_ids):
                raise ValueError("an edge cannot belong to multiple inter-floor connections")
            inter_floor_edge_ids.update(connection.edge_ids)
        actual_inter_floor_edges = {
            edge.edge_id
            for edge in self.edges
            if nodes_by_id[edge.from_node_id].floor_id != nodes_by_id[edge.to_node_id].floor_id
        }
        if inter_floor_edge_ids != actual_inter_floor_edges:
            raise ValueError("inter-floor edge declarations must be complete and exact")
        return self


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
        elif (
            self.observed_status is SpaceStatus.AVAILABLE
            and self.effective_status is not SpaceStatus.AVAILABLE
        ):
            raise ValueError("unclaimed available observation must remain effectively available")
        if self.assignable:
            if (
                self.observed_status is not SpaceStatus.AVAILABLE
                or self.effective_status is not SpaceStatus.AVAILABLE
                or self.claim_status is not FacilityClaimStatus.NONE
                or self.reason_codes
            ):
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
    """Human-readable identity for one deterministic synthetic driver state."""

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
        if (
            self.demo_profile is not None
            and self.source.source_kind is not FacilitySourceKind.SYNTHETIC
        ):
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
        if self.source.source_kind is FacilitySourceKind.IMPORTED and any(
            item is FacilityObservationSource.SYNTHETIC_TRUTH for item in observations
        ):
            raise ValueError("imported facility state cannot contain synthetic truth")
        return self

    def require_layout(self, layout: ParkingFacilityLayout) -> ParkingFacilityStateSnapshot:
        if self.parking_lot_id != layout.parking_lot_id:
            raise ValueError("facility state belongs to another parking lot")
        if self.layout_version != layout.layout_version:
            raise ValueError("facility state layout version mismatch")
        if {item.space_id for item in self.spaces} != {item.space_id for item in layout.spaces}:
            raise ValueError("facility state must cover layout spaces exactly")
        if {item.buffer_id for item in self.buffers} != {
            item.buffer_id for item in layout.buffers
        }:
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
        if (
            self.expected_departure_at is not None
            and self.expected_departure_at <= self.requested_at
        ):
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


class RoutePreview(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    parking_lot_id: Identifier
    layout_version: Identifier
    scenario_version: Identifier
    state_version: Identifier
    observed_at: AwareDatetime
    entrance_id: Identifier
    target_space_id: Identifier
    route: Route

    @model_validator(mode="after")
    def verify_route_identity(self) -> RoutePreview:
        if self.route.parking_lot_id != self.parking_lot_id:
            raise ValueError("route preview belongs to another parking lot")
        if self.route.layout_version != self.layout_version:
            raise ValueError("route preview layout version mismatch")
        return self

    def require_context(
        self,
        *,
        request: RoutePreviewRequest,
        layout: ParkingFacilityLayout,
        state: ParkingFacilityStateSnapshot,
    ) -> RoutePreview:
        state.require_layout(layout)
        if (
            self.parking_lot_id != layout.parking_lot_id
            or self.layout_version != layout.layout_version
        ):
            raise ValueError("route preview layout identity mismatch")
        if (
            self.layout_version != request.layout_version
            or self.scenario_version != request.scenario_version
            or self.state_version != request.state_version
            or self.entrance_id != request.entrance_id
            or self.target_space_id != request.target_space_id
        ):
            raise ValueError("route preview request identity mismatch")
        if (
            state.scenario_version != self.scenario_version
            or state.state_version != self.state_version
            or state.observed_at != self.observed_at
        ):
            raise ValueError("route preview state version mismatch")

        entrance_by_id = {item.entrance_id: item for item in layout.entrances}
        target_by_id = {item.space_id: item for item in layout.spaces}
        if self.entrance_id not in entrance_by_id or self.target_space_id not in target_by_id:
            raise ValueError("route preview references an unknown entrance or target")
        if self.route.from_node_id != entrance_by_id[self.entrance_id].node_id:
            raise ValueError("route preview starts at another entrance")
        if self.route.to_node_id != target_by_id[self.target_space_id].access_node_id:
            raise ValueError("route preview ends at another target access node")
        if (
            self.route.node_ids[0] != self.route.from_node_id
            or self.route.node_ids[-1] != self.route.to_node_id
        ):
            raise ValueError("route preview node sequence endpoints do not match route identity")

        nodes_by_id = {item.node_id: item for item in layout.nodes}
        edges_by_id = {item.edge_id: item for item in layout.edges}
        if not set(self.route.node_ids) <= set(nodes_by_id):
            raise ValueError("route preview references an unknown node")
        if not set(self.route.edge_ids) <= set(edges_by_id):
            raise ValueError("route preview references an unknown edge")
        if len(self.route.node_ids) != len(self.route.edge_ids) + 1:
            raise ValueError("route preview node and edge sequence lengths differ")
        for (from_node_id, to_node_id), edge_id in zip(
            pairwise(self.route.node_ids),
            self.route.edge_ids,
            strict=True,
        ):
            edge = edges_by_id[edge_id]
            follows_forward = (
                edge.from_node_id == from_node_id and edge.to_node_id == to_node_id
            )
            follows_reverse = (
                not edge.directed
                and edge.to_node_id == from_node_id
                and edge.from_node_id == to_node_id
            )
            if not follows_forward and not follows_reverse:
                raise ValueError("route preview edge sequence is not traversable")
        if tuple(item.edge_id for item in self.route.instructions) != self.route.edge_ids:
            raise ValueError("route preview instructions must cover route edges in order")
        if tuple(item.sequence for item in self.route.instructions) != tuple(
            range(1, len(self.route.instructions) + 1)
        ):
            raise ValueError("route preview instruction sequence must be contiguous")

        target_state = next(
            item for item in state.spaces if item.space_id == self.target_space_id
        )
        if (
            not target_state.assignable
            or target_state.effective_status is not SpaceStatus.AVAILABLE
        ):
            raise ValueError("route preview target is no longer assignable")
        return self


class CandidateAssessment(ContractModel):
    space_id: Identifier
    feasible: bool
    reason_codes: tuple[str, ...]
    recoverability_rank: Annotated[int, Field(ge=0)] | None = None
    dynamic_eta_s: NonNegativeSeconds | None = None
    distance_m: NonNegativeMeters | None = None
    depth: Annotated[int, Field(ge=1)]


class Recommendation(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    recommendation_id: Identifier
    request_id: Identifier
    parking_lot_id: Identifier
    algorithm_id: Identifier
    algorithm_version: Identifier
    data_source: DataSourceStatus
    solver_status: Literal["success", "no_feasible_space", "failed"]
    failure_code: Identifier | None = None
    recommended_space_id: Identifier | None = None
    alternative_space_ids: tuple[Identifier, ...] = ()
    assessments: tuple[CandidateAssessment, ...]
    route: Route | None = None
    explanation_codes: tuple[str, ...]
    degraded: bool = False
    degradation_reason: str | None = None
    claim_status: Literal["not_created_m2", "soft_held"] = "not_created_m2"
    soft_lock_expires_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def verify_success_payload(self) -> Recommendation:
        success = self.solver_status == "success"
        if success and (self.recommended_space_id is None or self.route is None):
            raise ValueError("successful recommendation requires a space and route")
        if not success and (
            self.recommended_space_id is not None
            or self.route is not None
            or self.alternative_space_ids
        ):
            raise ValueError("non-success recommendation cannot contain spaces or a route")
        failed = self.solver_status == "failed"
        if failed != (self.failure_code is not None):
            raise ValueError("failed recommendation requires failure_code only")
        if self.data_source.parking_lot_id != self.parking_lot_id:
            raise ValueError("data source belongs to another parking lot")
        if self.route is not None and self.route.parking_lot_id != self.parking_lot_id:
            raise ValueError("route belongs to another parking lot")
        if self.degraded != (self.degradation_reason is not None):
            raise ValueError("degraded flag and degradation_reason must agree")
        if self.claim_status == "soft_held" and (
            not success or self.soft_lock_expires_at is None
        ):
            raise ValueError("soft-held recommendation requires success and an expiry")
        if self.claim_status == "not_created_m2" and self.soft_lock_expires_at is not None:
            raise ValueError("unclaimed recommendation cannot contain a soft-lock expiry")
        return self


class Journey(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    journey_id: Identifier
    attempt_id: Identifier
    session_id: Identifier
    namespace: Literal["driver", "defense"]
    scenario_id: Identifier
    parking_lot_id: Identifier
    state: Literal[
        "idle",
        "waiting",
        "soft_held",
        "session_reserved",
        "navigating",
        "occupied",
        "departed",
        "cancelled",
        "expired",
        "failed",
    ]
    version: Annotated[int, Field(ge=1)]
    space_id: Identifier | None = None
    recommendation_id: Identifier | None = None
    updated_at: AwareDatetime
    expires_at: AwareDatetime | None = None
    terminal_reason: Identifier | None = None
    legal_operations: tuple[str, ...]


class JourneyRecommendationRequest(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    namespace: Literal["driver", "defense"] = "driver"
    scenario_id: Identifier
    journey_id: Identifier
    attempt_id: Identifier
    algorithm_id: Identifier = "online-rule-v2"
    idempotency_key: Identifier
    driver: DriverRequest


class JourneyRecommendationResponse(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    recommendation: Recommendation
    journey: Journey


class DriverEntrance(ContractModel):
    node_id: Identifier
    label: str = Field(min_length=1, max_length=80)


class DriverRecommendationContext(ContractModel):
    """Server-derived inputs needed to start a driver recommendation."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    observed_at: AwareDatetime
    scenario_id: Identifier
    parking_lot_id: Identifier
    layout_version: Identifier
    entrances: tuple[DriverEntrance, ...] = Field(min_length=1)
    spaces: tuple[ParkingSpace, ...] = Field(min_length=1)
    tandem_groups: tuple[TandemGroup, ...] = ()
    data_source: DataSourceStatus
    demo_profile: DriverDemoProfile | None = None

    @model_validator(mode="after")
    def verify_context_scope(self) -> DriverRecommendationContext:
        if self.data_source.parking_lot_id != self.parking_lot_id:
            raise ValueError("driver context data source belongs to another parking lot")
        if self.demo_profile is not None and self.data_source.mode is not DataMode.SYNTHETIC:
            raise ValueError("driver demo profile requires a synthetic data source")
        if len({item.node_id for item in self.entrances}) != len(self.entrances):
            raise ValueError("driver context entrances must be unique")
        if any(item.parking_lot_id != self.parking_lot_id for item in self.spaces):
            raise ValueError("driver context spaces belong to another parking lot")
        space_ids = {item.space_id for item in self.spaces}
        if any(
            not set(item.space_ids_near_to_deep) <= space_ids
            for item in self.tandem_groups
        ):
            raise ValueError("driver context tandem groups reference unknown spaces")
        return self


class DriverJourneySnapshot(ContractModel):
    """Authoritative recoverable driver state observed without renewing its deadline."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    observed_at: AwareDatetime
    journey: Journey | None = None
    recommendation: Recommendation | None = None
    driver: DriverRequest | None = None
    waiting_since: AwareDatetime | None = None

    @model_validator(mode="after")
    def verify_snapshot(self) -> DriverJourneySnapshot:
        present = (
            self.journey is not None,
            self.recommendation is not None,
            self.driver is not None,
        )
        if any(present) and not all(present):
            raise ValueError("driver journey snapshot payloads must be all present or all absent")
        if self.journey is not None and self.driver is not None:
            if self.journey.session_id != self.driver.session_id:
                raise ValueError("journey and driver belong to different sessions")
            if self.journey.parking_lot_id != self.driver.parking_lot_id:
                raise ValueError("journey and driver belong to different parking lots")
        if self.journey is not None and self.recommendation is not None:
            if self.recommendation.parking_lot_id != self.journey.parking_lot_id:
                raise ValueError("journey and recommendation belong to different parking lots")
        if self.waiting_since is not None and (
            self.journey is None or self.journey.state != "waiting"
        ):
            raise ValueError("waiting_since is only valid for a waiting journey")
        return self


class JourneyCommandRequest(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    expected_version: Annotated[int, Field(ge=1)]
    idempotency_key: Identifier


class DriverDemoProfileAdvanceRequest(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    expected_profile_id: Identifier
    expected_state_version: Identifier
    idempotency_key: Identifier


class DriverDemoProfileAdvanceResponse(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    demo_profile: DriverDemoProfile
    facility_state: ParkingFacilityStateSnapshot
    parking_lot: ParkingLot

    @model_validator(mode="after")
    def verify_scope(self) -> DriverDemoProfileAdvanceResponse:
        if self.facility_state.parking_lot_id != self.parking_lot.parking_lot_id:
            raise ValueError("demo profile response resources belong to different parking lots")
        if self.facility_state.demo_profile != self.demo_profile:
            raise ValueError("demo profile response metadata is inconsistent")
        return self


class JourneyConfirmRequest(JourneyCommandRequest):
    accepted: bool


class JourneyAlternativeRequest(JourneyCommandRequest):
    space_id: Identifier


class JourneyDeclineRequest(JourneyCommandRequest):
    replacement_journey_id: Identifier
    replacement_attempt_id: Identifier
    replacement_request_id: Identifier


class JourneyDeclineResponse(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    declined_journey: Journey
    replacement: JourneyRecommendationResponse


class JourneyReassignmentRequest(JourneyCommandRequest):
    reason: Literal["unable_to_park", "eta_exceeds_reservation"]
    replacement_journey_id: Identifier
    replacement_attempt_id: Identifier
    replacement_request_id: Identifier


class JourneyReassignmentResponse(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    ended_journey: Journey
    replacement: JourneyRecommendationResponse


class JourneyReplanRequest(JourneyCommandRequest):
    current_node_id: Identifier
    trigger: Literal["deviation", "cost_update", "manual_refresh"]
    channel_load: ChannelLoadSnapshot


class DriverDemoReplanRequest(JourneyCommandRequest):
    """Safe driver-demo action whose dynamic inputs are derived by the server."""

    action: Literal["simulate_deviation", "simulate_cost_update"]


class ReplanDecision(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    status: Literal["success", "warning", "failed"]
    trigger: Literal["deviation", "cost_update", "manual_refresh"]
    cost_snapshot: CostSnapshot
    previous_route: Route
    route: Route | None = None
    remaining_reservation_s: NonNegativeSeconds
    eta_with_safety_margin_s: NonNegativeSeconds | None = None
    reason_codes: tuple[Identifier, ...]


class JourneyReplanResponse(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    journey: Journey
    decision: ReplanDecision


class DriverTripEvent(ContractModel):
    sequence_no: Annotated[int, Field(ge=1)]
    event_type: Identifier
    reason_code: Identifier | None = None
    occurred_at: AwareDatetime


class DriverTripRecord(ContractModel):
    journey_id: Identifier
    parking_lot_id: Identifier
    space_id: Identifier | None = None
    state: Literal["occupied", "departed", "cancelled", "expired", "failed"]
    started_at: AwareDatetime | None = None
    parked_at: AwareDatetime | None = None
    ended_at: AwareDatetime | None = None
    terminal_reason: Identifier | None = None


class DriverTandemDepartureRequest(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    expected_version: Annotated[int, Field(ge=1)]
    expected_state_version: Identifier
    idempotency_key: Identifier


class DriverTandemReplayLocation(ContractModel):
    kind: Literal["space", "buffer", "exit"]
    location_id: Identifier
    node_id: Identifier
    floor_id: Identifier
    coordinate: Coordinate


class DriverTandemReplayStep(ContractModel):
    sequence: Annotated[int, Field(ge=1)]
    action: Literal["relocate_to_buffer", "direct_exit", "restore_original"]
    actor_id: Identifier
    actor_role: Literal["driver", "blocker"]
    label: str = Field(min_length=1, max_length=100)
    from_location: DriverTandemReplayLocation
    to_location: DriverTandemReplayLocation
    route: Route
    starts_at_s: NonNegativeSeconds
    duration_s: Annotated[float, Field(gt=0, allow_inf_nan=False)]

    @model_validator(mode="after")
    def verify_route_endpoints(self) -> DriverTandemReplayStep:
        if self.route.from_node_id != self.from_location.node_id:
            raise ValueError("tandem replay route starts at another location")
        if self.route.to_node_id != self.to_location.node_id:
            raise ValueError("tandem replay route ends at another location")
        return self


class DriverTandemDepartureReplay(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    replay_id: Identifier
    created_at: AwareDatetime
    journey_id: Identifier
    parking_lot_id: Identifier
    layout_version: Identifier
    scenario_version: Identifier
    state_version: Identifier
    cost_version: Identifier
    profile_id: Literal["tandem-focus"] = "tandem-focus"
    stack_group_id: Identifier
    target_space_id: Identifier
    blocker_vehicle_ids: tuple[Identifier, ...] = Field(min_length=1)
    buffer_ids: tuple[Identifier, ...] = Field(min_length=1)
    steps: tuple[DriverTandemReplayStep, ...] = Field(min_length=3)
    total_duration_s: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    before_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    after_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    facility_state: ParkingFacilityStateSnapshot
    final_journey: Journey

    @model_validator(mode="after")
    def verify_replay(self) -> DriverTandemDepartureReplay:
        if tuple(item.sequence for item in self.steps) != tuple(
            range(1, len(self.steps) + 1)
        ):
            raise ValueError("tandem replay sequence must be contiguous")
        direct_indices = [
            index for index, item in enumerate(self.steps) if item.action == "direct_exit"
        ]
        if len(direct_indices) != 1:
            raise ValueError("tandem replay requires exactly one direct exit")
        direct_index = direct_indices[0]
        if any(item.action != "relocate_to_buffer" for item in self.steps[:direct_index]):
            raise ValueError("tandem replay must move all blockers out before departure")
        if any(item.action != "restore_original" for item in self.steps[direct_index + 1 :]):
            raise ValueError("tandem replay must restore blockers after departure")
        blocker_count = direct_index
        if blocker_count < 1 or len(self.steps) != blocker_count * 2 + 1:
            raise ValueError("tandem replay blocker stages are incomplete")
        if len(self.blocker_vehicle_ids) != blocker_count or len(self.buffer_ids) != blocker_count:
            raise ValueError("tandem replay blocker and buffer counts differ")
        if self.steps[direct_index].actor_role != "driver":
            raise ValueError("tandem replay direct exit must belong to the driver")
        if any(
            item.actor_role != "blocker"
            for index, item in enumerate(self.steps)
            if index != direct_index
        ):
            raise ValueError("tandem replay relocation stages must belong to blockers")
        elapsed = 0.0
        for item in self.steps:
            if abs(item.starts_at_s - elapsed) > 1e-6:
                raise ValueError("tandem replay stage timing must be contiguous")
            if (
                item.route.parking_lot_id != self.parking_lot_id
                or item.route.layout_version != self.layout_version
                or item.route.cost_version != self.cost_version
            ):
                raise ValueError("tandem replay route identity mismatch")
            elapsed += item.duration_s
        if abs(elapsed - self.total_duration_s) > 1e-6:
            raise ValueError("tandem replay total duration mismatch")
        if (
            self.final_journey.journey_id != self.journey_id
            or self.final_journey.parking_lot_id != self.parking_lot_id
            or self.final_journey.state != "departed"
        ):
            raise ValueError("tandem replay final journey mismatch")
        if (
            self.facility_state.parking_lot_id != self.parking_lot_id
            or self.facility_state.layout_version != self.layout_version
            or self.facility_state.scenario_version != self.scenario_version
            or self.facility_state.state_version != self.state_version
            or self.facility_state.demo_profile is None
            or self.facility_state.demo_profile.profile_id != self.profile_id
        ):
            raise ValueError("tandem replay facility state identity mismatch")
        return self


class DriverTandemArrivalRequest(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    expected_version: Annotated[int, Field(ge=1)]
    expected_state_version: Identifier
    idempotency_key: Identifier


class DriverTandemArrivalLocation(ContractModel):
    kind: Literal["space", "buffer", "approach"]
    location_id: Identifier
    node_id: Identifier
    floor_id: Identifier
    coordinate: Coordinate


class DriverTandemArrivalStep(ContractModel):
    sequence: Annotated[int, Field(ge=1)]
    action: Literal["relocate_to_buffer", "direct_entry", "restore_original"]
    actor_id: Identifier
    actor_role: Literal["driver", "blocker"]
    label: str = Field(min_length=1, max_length=100)
    from_location: DriverTandemArrivalLocation
    to_location: DriverTandemArrivalLocation
    route: Route
    starts_at_s: NonNegativeSeconds
    duration_s: Annotated[float, Field(gt=0, allow_inf_nan=False)]

    @model_validator(mode="after")
    def verify_route_endpoints(self) -> DriverTandemArrivalStep:
        if self.route.from_node_id != self.from_location.node_id:
            raise ValueError("tandem arrival route starts at another location")
        if self.route.to_node_id != self.to_location.node_id:
            raise ValueError("tandem arrival route ends at another location")
        return self


class DriverTandemArrivalReplay(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    replay_id: Identifier
    created_at: AwareDatetime
    journey_id: Identifier
    parking_lot_id: Identifier
    layout_version: Identifier
    scenario_version: Identifier
    before_state_version: Identifier
    after_state_version: Identifier
    cost_version: Identifier
    profile_id: Literal["tandem-focus"] = "tandem-focus"
    stack_group_id: Identifier
    target_space_id: Identifier
    blocker_vehicle_ids: tuple[Identifier, ...] = Field(min_length=1)
    buffer_ids: tuple[Identifier, ...] = Field(min_length=1)
    steps: tuple[DriverTandemArrivalStep, ...] = Field(min_length=3)
    total_duration_s: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    before_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    after_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    before_facility_state: ParkingFacilityStateSnapshot
    after_facility_state: ParkingFacilityStateSnapshot
    final_journey: Journey

    @model_validator(mode="after")
    def verify_replay(self) -> DriverTandemArrivalReplay:
        if tuple(item.sequence for item in self.steps) != tuple(
            range(1, len(self.steps) + 1)
        ):
            raise ValueError("tandem arrival sequence must be contiguous")
        direct_indices = [
            index for index, item in enumerate(self.steps) if item.action == "direct_entry"
        ]
        if len(direct_indices) != 1:
            raise ValueError("tandem arrival requires exactly one direct entry")
        direct_index = direct_indices[0]
        if any(item.action != "relocate_to_buffer" for item in self.steps[:direct_index]):
            raise ValueError("tandem arrival must move all blockers out before entry")
        if any(item.action != "restore_original" for item in self.steps[direct_index + 1 :]):
            raise ValueError("tandem arrival must restore blockers after entry")
        blocker_count = direct_index
        if blocker_count < 1 or len(self.steps) != blocker_count * 2 + 1:
            raise ValueError("tandem arrival blocker stages are incomplete")
        if len(self.blocker_vehicle_ids) != blocker_count or len(self.buffer_ids) != blocker_count:
            raise ValueError("tandem arrival blocker and buffer counts differ")
        if self.steps[direct_index].actor_role != "driver":
            raise ValueError("tandem arrival direct entry must belong to the driver")
        if any(
            item.actor_role != "blocker"
            for index, item in enumerate(self.steps)
            if index != direct_index
        ):
            raise ValueError("tandem arrival relocation stages must belong to blockers")
        elapsed = 0.0
        for item in self.steps:
            if abs(item.starts_at_s - elapsed) > 1e-6:
                raise ValueError("tandem arrival stage timing must be contiguous")
            if (
                item.route.parking_lot_id != self.parking_lot_id
                or item.route.layout_version != self.layout_version
                or item.route.cost_version != self.cost_version
            ):
                raise ValueError("tandem arrival route identity mismatch")
            elapsed += item.duration_s
        if abs(elapsed - self.total_duration_s) > 1e-6:
            raise ValueError("tandem arrival total duration mismatch")
        if (
            self.final_journey.journey_id != self.journey_id
            or self.final_journey.parking_lot_id != self.parking_lot_id
            or self.final_journey.state != "occupied"
            or self.final_journey.space_id != self.target_space_id
        ):
            raise ValueError("tandem arrival final journey mismatch")
        for state, version in (
            (self.before_facility_state, self.before_state_version),
            (self.after_facility_state, self.after_state_version),
        ):
            if (
                state.parking_lot_id != self.parking_lot_id
                or state.layout_version != self.layout_version
                or state.scenario_version != self.scenario_version
                or state.state_version != version
                or state.demo_profile is None
                or state.demo_profile.profile_id != self.profile_id
            ):
                raise ValueError("tandem arrival facility state identity mismatch")
        return self


class DriverTripSnapshot(ContractModel):
    """Recoverable current-trip projection driven by one authoritative route."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    observed_at: AwareDatetime
    journey: Journey | None = None
    driver: DriverRequest | None = None
    current_route: Route | None = None
    current_node_id: Identifier | None = None
    last_replan: ReplanDecision | None = None
    started_at: AwareDatetime | None = None
    parked_at: AwareDatetime | None = None
    ended_at: AwareDatetime | None = None
    recent_events: tuple[DriverTripEvent, ...] = ()
    recent_trips: tuple[DriverTripRecord, ...] = ()
    tandem_arrival_replay_enabled: bool = False
    tandem_arrival_replay: DriverTandemArrivalReplay | None = None
    tandem_departure_replay_enabled: bool = False
    tandem_departure_replay: DriverTandemDepartureReplay | None = None

    @model_validator(mode="after")
    def verify_trip(self) -> DriverTripSnapshot:
        if (self.journey is None) != (self.driver is None):
            raise ValueError("trip journey and driver must be both present or both absent")
        if self.journey is None:
            if any(
                item is not None
                for item in (
                    self.current_route,
                    self.current_node_id,
                    self.last_replan,
                    self.started_at,
                    self.parked_at,
                    self.ended_at,
                    self.tandem_arrival_replay,
                    self.tandem_departure_replay,
                )
            ) or self.recent_events or self.recent_trips:
                raise ValueError("empty trip cannot contain navigation or lifecycle data")
            return self
        assert self.driver is not None
        if self.journey.session_id != self.driver.session_id:
            raise ValueError("trip journey and driver belong to different sessions")
        if self.journey.parking_lot_id != self.driver.parking_lot_id:
            raise ValueError("trip journey and driver belong to different parking lots")
        if self.current_route is not None:
            if self.current_route.parking_lot_id != self.journey.parking_lot_id:
                raise ValueError("trip route belongs to another parking lot")
            if self.current_node_id is None:
                raise ValueError("trip route requires a current node")
        if self.last_replan is not None and self.current_route is None:
            raise ValueError("last replan requires a current route")
        if self.tandem_departure_replay is not None:
            if self.tandem_departure_replay.journey_id != self.journey.journey_id:
                raise ValueError("trip tandem replay belongs to another journey")
            if self.journey.state != "departed":
                raise ValueError("trip tandem replay requires a departed journey")
        if self.tandem_arrival_replay is not None:
            if self.tandem_arrival_replay.journey_id != self.journey.journey_id:
                raise ValueError("trip tandem arrival replay belongs to another journey")
            if self.journey.state not in {"occupied", "departed"}:
                raise ValueError("trip tandem arrival replay requires an occupied journey history")
        return self


class ExternalOccupancyRequest(JourneyCommandRequest):
    replacement_journey_id: Identifier
    replacement_attempt_id: Identifier
    replacement_request_id: Identifier


class ExternalOccupancyResponse(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    failed_journey: Journey
    replacement: JourneyRecommendationResponse


class SimulationEvent(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    parking_lot_id: Identifier
    sequence_no: Annotated[int, Field(ge=1)]
    simulation_time_s: Annotated[int, Field(ge=0)]
    wall_time: AwareDatetime
    event_type: Identifier
    subject_id: Identifier
    payload: dict[str, Any]
    before_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    after_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class SimulationCommandRequest(ContractModel):
    simulation_time_s: Annotated[int, Field(ge=0)]
    priority: int
    sequence_hint: Annotated[int, Field(ge=0)]
    event_type: Identifier
    vehicle_id: Identifier
    payload: dict[str, Any] = Field(default_factory=dict)


class SimulationSummaryResponse(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    vehicle_count: Annotated[int, Field(ge=0)]
    occupied_space_count: Annotated[int, Field(ge=0)]
    waiting_vehicle_count: Annotated[int, Field(ge=0)]
    relocation_count: Annotated[int, Field(ge=0)]
    failure_count: Annotated[int, Field(ge=0)]
    final_state_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class SimulationRunRequest(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    parking_lot_id: Identifier
    seed: Annotated[int, Field(ge=0)]
    wall_time_origin: AwareDatetime
    commands: tuple[SimulationCommandRequest, ...]


class SimulationReplayRequest(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    parking_lot_id: Identifier
    seed: Annotated[int, Field(ge=0)]
    wall_time_origin: AwareDatetime
    events: tuple[SimulationEvent, ...]


class SimulationRunResponse(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    seed: Annotated[int, Field(ge=0)]
    events: tuple[SimulationEvent, ...]
    summary: SimulationSummaryResponse


class AlgorithmDescriptor(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    algorithm_id: Identifier
    version: Identifier
    display_name: str = Field(min_length=1, max_length=80)
    category: Literal["rule", "metaheuristic", "machine_learning", "optimization"]
    status: AlgorithmStatus
    required_inputs: tuple[str, ...]
    pending_reason: str | None = None

    @model_validator(mode="after")
    def verify_status(self) -> AlgorithmDescriptor:
        if self.status is AlgorithmStatus.ONLINE and self.pending_reason is not None:
            raise ValueError("online algorithm cannot contain pending_reason")
        if self.status is AlgorithmStatus.PENDING and not self.pending_reason:
            raise ValueError("pending algorithm requires pending_reason")
        return self


class ScenarioBundle(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    scenario_id: Identifier
    seed: Annotated[int, Field(ge=0)]
    parking_lot: ParkingLot
    layout: Layout
    cost_snapshot: CostSnapshot

    @model_validator(mode="after")
    def verify_bundle_scope(self) -> ScenarioBundle:
        lot_id = self.parking_lot.parking_lot_id
        if self.layout.parking_lot_id != lot_id or self.cost_snapshot.parking_lot_id != lot_id:
            raise ValueError("scenario resources have different parking_lot_id values")
        if self.layout.layout_version != self.cost_snapshot.layout_version:
            raise ValueError("cost snapshot layout version mismatch")
        if self.parking_lot.total_spaces != len(self.layout.spaces):
            raise ValueError("parking lot total does not match layout")
        available = sum(item.status is SpaceStatus.AVAILABLE for item in self.layout.spaces)
        if self.parking_lot.available_spaces != available:
            raise ValueError("parking lot availability does not match layout")
        charging = sum(item.charging for item in self.layout.spaces)
        if self.parking_lot.charging_spaces != charging:
            raise ValueError("parking lot charging count does not match layout")
        return self


SCHEMA_MODELS: dict[str, type[ContractModel]] = {
    "algorithm-descriptor": AlgorithmDescriptor,
    "channel-load-snapshot": ChannelLoadSnapshot,
    "cost-snapshot": CostSnapshot,
    "data-source-status": DataSourceStatus,
    "discovery-area": DiscoveryArea,
    "driver-demo-profile": DriverDemoProfile,
    "driver-demo-profile-advance-request": DriverDemoProfileAdvanceRequest,
    "driver-demo-profile-advance-response": DriverDemoProfileAdvanceResponse,
    "driver-request": DriverRequest,
    "driver-demo-replan-request": DriverDemoReplanRequest,
    "driver-trip-event": DriverTripEvent,
    "driver-trip-record": DriverTripRecord,
    "driver-trip-snapshot": DriverTripSnapshot,
    "driver-tandem-arrival-request": DriverTandemArrivalRequest,
    "driver-tandem-arrival-replay": DriverTandemArrivalReplay,
    "driver-tandem-departure-request": DriverTandemDepartureRequest,
    "driver-tandem-departure-replay": DriverTandemDepartureReplay,
    "error-response": ErrorResponse,
    "external-occupancy-request": ExternalOccupancyRequest,
    "external-occupancy-response": ExternalOccupancyResponse,
    "journey": Journey,
    "journey-alternative-request": JourneyAlternativeRequest,
    "journey-command-request": JourneyCommandRequest,
    "journey-confirm-request": JourneyConfirmRequest,
    "journey-decline-request": JourneyDeclineRequest,
    "journey-decline-response": JourneyDeclineResponse,
    "journey-recommendation-request": JourneyRecommendationRequest,
    "journey-recommendation-response": JourneyRecommendationResponse,
    "journey-reassignment-request": JourneyReassignmentRequest,
    "journey-reassignment-response": JourneyReassignmentResponse,
    "journey-replan-request": JourneyReplanRequest,
    "journey-replan-response": JourneyReplanResponse,
    "layout": Layout,
    "parking-lot": ParkingLot,
    "parking-facility-layout": ParkingFacilityLayout,
    "parking-facility-state-snapshot": ParkingFacilityStateSnapshot,
    "parking-space": ParkingSpace,
    "recommendation": Recommendation,
    "recommendation-request": RecommendationRequest,
    "driver-entrance": DriverEntrance,
    "driver-journey-snapshot": DriverJourneySnapshot,
    "driver-recommendation-context": DriverRecommendationContext,
    "replan-decision": ReplanDecision,
    "route": Route,
    "route-preview": RoutePreview,
    "route-preview-request": RoutePreviewRequest,
    "scenario-bundle": ScenarioBundle,
    "simulation-event": SimulationEvent,
    "simulation-command-request": SimulationCommandRequest,
    "simulation-replay-request": SimulationReplayRequest,
    "simulation-run-request": SimulationRunRequest,
    "simulation-run-response": SimulationRunResponse,
    "simulation-summary-response": SimulationSummaryResponse,
}
