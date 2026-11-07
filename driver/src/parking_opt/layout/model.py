"""Third-party-free immutable parking-layout values."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True, slots=True)
class RoadNode:
    road_node_id: str
    x_m: float
    y_m: float
    node_kind: str


@dataclass(frozen=True, slots=True)
class RoadEdge:
    road_edge_id: str
    from_node_id: str
    to_node_id: str
    distance_m: float
    travel_time_s: int
    directed: bool
    channel_zone_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PathCost:
    path_cost_id: str
    from_node_id: str
    to_node_id: str
    distance_m: float
    travel_time_s: int
    road_edge_ids: tuple[str, ...]
    channel_zone_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Slot:
    position_id: str
    x_m: float
    y_m: float
    access_node_id: str
    stack_group_id: str
    depth: int
    channel_zone_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BufferSlot:
    position_id: str
    x_m: float
    y_m: float
    access_node_id: str
    channel_zone_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ChannelZone:
    channel_zone_id: str
    capacity: int


@dataclass(frozen=True, slots=True)
class Layout:
    """Immutable layout whose path costs are plain values, never graph objects."""

    schema_version: str
    layout_id: str
    coordinate_origin_note: str
    road_nodes: tuple[RoadNode, ...]
    road_edges: tuple[RoadEdge, ...]
    path_costs: tuple[PathCost, ...]
    slots: tuple[Slot, ...]
    buffer_slots: tuple[BufferSlot, ...]
    channel_zones: tuple[ChannelZone, ...]

    def with_path_costs(self, path_costs: tuple[PathCost, ...]) -> Layout:
        """Return a copy with deterministic materialized path values."""

        return replace(self, path_costs=path_costs)


def layout_from_mapping(value: dict[str, Any]) -> Layout:
    """Build an immutable layout from a schema-validated v1 mapping."""

    return Layout(
        schema_version=value["schema_version"],
        layout_id=value["layout_id"],
        coordinate_origin_note=value["coordinate_system"]["origin_note"],
        road_nodes=tuple(
            RoadNode(
                road_node_id=item["road_node_id"],
                x_m=float(item["x_m"]),
                y_m=float(item["y_m"]),
                node_kind=item["node_kind"],
            )
            for item in value["road_nodes"]
        ),
        road_edges=tuple(
            RoadEdge(
                road_edge_id=item["road_edge_id"],
                from_node_id=item["from_node_id"],
                to_node_id=item["to_node_id"],
                distance_m=float(item["distance_m"]),
                travel_time_s=item["travel_time_s"],
                directed=item["directed"],
                channel_zone_ids=tuple(item["channel_zone_ids"]),
            )
            for item in value["road_edges"]
        ),
        path_costs=tuple(
            PathCost(
                path_cost_id=item["path_cost_id"],
                from_node_id=item["from_node_id"],
                to_node_id=item["to_node_id"],
                distance_m=float(item["distance_m"]),
                travel_time_s=item["travel_time_s"],
                road_edge_ids=tuple(item["road_edge_ids"]),
                channel_zone_ids=tuple(item["channel_zone_ids"]),
            )
            for item in value["path_costs"]
        ),
        slots=tuple(
            Slot(
                position_id=item["position_id"],
                x_m=float(item["x_m"]),
                y_m=float(item["y_m"]),
                access_node_id=item["access_node_id"],
                stack_group_id=item["stack_group_id"],
                depth=item["depth"],
                channel_zone_ids=tuple(item["channel_zone_ids"]),
            )
            for item in value["slots"]
        ),
        buffer_slots=tuple(
            BufferSlot(
                position_id=item["position_id"],
                x_m=float(item["x_m"]),
                y_m=float(item["y_m"]),
                access_node_id=item["access_node_id"],
                channel_zone_ids=tuple(item["channel_zone_ids"]),
            )
            for item in value["buffer_slots"]
        ),
        channel_zones=tuple(
            ChannelZone(
                channel_zone_id=item["channel_zone_id"],
                capacity=item["capacity"],
            )
            for item in value["channel_zones"]
        ),
    )


def layout_to_mapping(layout: Layout) -> dict[str, Any]:
    """Serialize only fields in the approved v1 layout schema."""

    return {
        "schema_version": layout.schema_version,
        "layout_id": layout.layout_id,
        "coordinate_system": {
            "kind": "local_meters",
            "origin_note": layout.coordinate_origin_note,
        },
        "road_nodes": [
            {
                "road_node_id": item.road_node_id,
                "x_m": item.x_m,
                "y_m": item.y_m,
                "node_kind": item.node_kind,
            }
            for item in layout.road_nodes
        ],
        "road_edges": [
            {
                "road_edge_id": item.road_edge_id,
                "from_node_id": item.from_node_id,
                "to_node_id": item.to_node_id,
                "distance_m": item.distance_m,
                "travel_time_s": item.travel_time_s,
                "directed": item.directed,
                "channel_zone_ids": list(item.channel_zone_ids),
            }
            for item in layout.road_edges
        ],
        "path_costs": [
            {
                "path_cost_id": item.path_cost_id,
                "from_node_id": item.from_node_id,
                "to_node_id": item.to_node_id,
                "distance_m": item.distance_m,
                "travel_time_s": item.travel_time_s,
                "road_edge_ids": list(item.road_edge_ids),
                "channel_zone_ids": list(item.channel_zone_ids),
            }
            for item in layout.path_costs
        ],
        "slots": [
            {
                "position_id": item.position_id,
                "x_m": item.x_m,
                "y_m": item.y_m,
                "access_node_id": item.access_node_id,
                "stack_group_id": item.stack_group_id,
                "depth": item.depth,
                "channel_zone_ids": list(item.channel_zone_ids),
            }
            for item in layout.slots
        ],
        "buffer_slots": [
            {
                "position_id": item.position_id,
                "x_m": item.x_m,
                "y_m": item.y_m,
                "access_node_id": item.access_node_id,
                "channel_zone_ids": list(item.channel_zone_ids),
            }
            for item in layout.buffer_slots
        ],
        "channel_zones": [
            {
                "channel_zone_id": item.channel_zone_id,
                "capacity": item.capacity,
            }
            for item in layout.channel_zones
        ],
    }
