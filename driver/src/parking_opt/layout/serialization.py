"""Layout <-> v1 mapping (de)serialization."""

from __future__ import annotations

from typing import Any

from parking_opt.layout.model import (
    BufferSlot,
    ChannelZone,
    Layout,
    PathCost,
    RoadEdge,
    RoadNode,
    Slot,
)


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
