"""ParkingFacilityLayout model and reference verification."""
from __future__ import annotations
from itertools import pairwise
from math import cos, hypot, radians, sin
from typing import Literal
from pydantic import Field, model_validator
from parking_opt.api.models import ContractModel, Identifier
from parking_opt.api.models_discovery import ChannelZone, Coordinate
from parking_opt.api.models_facility_verify import _FacilitySpacesVerificationMixin
from parking_opt.api.models_facility import (
    FacilityBounds,
    FacilityBuffer,
    FacilityEdge,
    FacilityEntrance,
    FacilityExit,
    FacilityFloor,
    FacilityImageRegistration,
    FacilityInterFloorConnection,
    FacilityNode,
    FacilityProvenance,
    FacilityRectangle,
    FacilityRestrictedArea,
    FacilitySpace,
    FacilityTandemGroup,
    FacilityZone,
)
class ParkingFacilityLayout(_FacilitySpacesVerificationMixin, ContractModel):
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
                bounds.contains(Coordinate(x_m=rectangle.center.x_m + dx * cosine - dy * sine, y_m=rectangle.center.y_m + dx * sine + dy * cosine))
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
            if not (self.bounds.min_x_m <= floor.bounds.min_x_m < floor.bounds.max_x_m <= self.bounds.max_x_m and self.bounds.min_y_m <= floor.bounds.min_y_m < floor.bounds.max_y_m <= self.bounds.max_y_m):
                raise ValueError(f"floor {floor.floor_id} bounds exceed facility bounds")
        zones_by_id = {item.zone_id: item for item in self.zones}
        if len(zones_by_id) != len(self.zones):
            raise ValueError("zone ids must be unique")
        for zone in self.zones:
            if zone.floor_id not in floor_ids:
                raise ValueError(f"zone {zone.zone_id} references an unknown floor")
            if not all(floors_by_id[zone.floor_id].bounds.contains(point) for point in zone.polygon):
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
        channel_zone_ids = unique(tuple(item.channel_zone_id for item in self.channel_zones), "channel zone")
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
            centerline_distance = sum(hypot(right.x_m - left.x_m, right.y_m - left.y_m) for left, right in pairwise(edge.centerline))
            distance_tolerance = max(0.001, edge.distance_m * 0.001)
            if abs(centerline_distance - edge.distance_m) > distance_tolerance:
                raise ValueError(f"edge {edge.edge_id} distance differs from its centerline")
            edge_floors = {nodes_by_id[edge.from_node_id].floor_id, nodes_by_id[edge.to_node_id].floor_id}
            for point in edge.centerline:
                if not any(floors_by_id[floor_id].bounds.contains(point) for floor_id in edge_floors):
                    raise ValueError(f"edge {edge.edge_id} centerline exceeds connected floors")
        entrance_ids = unique(tuple(item.entrance_id for item in self.entrances), "entrance")
        if self.default_entrance_id not in entrance_ids:
            raise ValueError("default entrance does not exist")
        for entrance in self.entrances:
            entrance_node = nodes_by_id.get(entrance.node_id)
            if entrance_node is None or entrance_node.kind != "entrance":
                raise ValueError(f"entrance {entrance.entrance_id} must reference an entrance node")
        if {item.node_id for item in self.entrances} != {item.node_id for item in self.nodes if item.kind == "entrance"}:
            raise ValueError("facility entrances must cover entrance nodes exactly")
        if len({item.node_id for item in self.entrances}) != len(self.entrances):
            raise ValueError("facility entrances cannot repeat a node")
        unique(tuple(item.exit_id for item in self.exits), "exit")
        for facility_exit in self.exits:
            exit_node = nodes_by_id.get(facility_exit.node_id)
            if exit_node is None or exit_node.kind != "exit":
                raise ValueError(f"exit {facility_exit.exit_id} must reference an exit node")
        if {item.node_id for item in self.exits} != {item.node_id for item in self.nodes if item.kind == "exit"}:
            raise ValueError("facility exits must cover exit nodes exactly")
        if len({item.node_id for item in self.exits}) != len(self.exits):
            raise ValueError("facility exits cannot repeat a node")
        self._verify_spaces_buffers_groups()
        return self
