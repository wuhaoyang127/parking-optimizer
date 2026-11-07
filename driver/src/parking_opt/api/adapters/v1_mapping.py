"""Build the v1 layout mapping and approved config from v2 visible values."""

from __future__ import annotations

from typing import Any

from parking_opt.api.models import CostSnapshot, Layout
from parking_opt.api.routing import RouteNotFoundError


def v1_layout_mapping(route_service, layout: Layout, costs: CostSnapshot) -> dict[str, Any]:
    relevant_nodes = sorted(
        {
            *layout.entrance_node_ids,
            *layout.exit_node_ids,
            *(item.access_node_id for item in layout.spaces),
            *(item.access_node_id for item in layout.buffers),
        }
    )
    path_costs: list[dict[str, Any]] = []
    for from_node in relevant_nodes:
        for to_node in relevant_nodes:
            try:
                route = route_service.route(
                    layout, costs, from_node_id=from_node, to_node_id=to_node
                )
            except RouteNotFoundError:
                continue
            zones = tuple(
                dict.fromkeys(
                    zone
                    for edge_id in route.edge_ids
                    for zone in next(
                        item for item in layout.edges if item.edge_id == edge_id
                    ).channel_zone_ids
                )
            )
            path_costs.append(
                {
                    "path_cost_id": f"path-{from_node}-{to_node}",
                    "from_node_id": from_node,
                    "to_node_id": to_node,
                    "distance_m": route.distance_m,
                    "travel_time_s": max(0, round(route.dynamic_eta_s)),
                    "road_edge_ids": list(route.edge_ids),
                    "channel_zone_ids": list(zones),
                }
            )
    return {
        "schema_version": "1.0.0",
        "layout_id": f"v1-{layout.parking_lot_id}-{layout.layout_version}",
        "coordinate_system": {
            "kind": "local_meters",
            "origin_note": layout.coordinate_origin_note,
        },
        "road_nodes": [
            {
                "road_node_id": item.node_id,
                "x_m": item.coordinate.x_m,
                "y_m": item.coordinate.y_m,
                "node_kind": "position_access"
                if item.kind in {"space_access", "buffer_access"}
                else item.kind,
            }
            for item in layout.nodes
        ],
        "road_edges": [
            {
                "road_edge_id": item.edge_id,
                "from_node_id": item.from_node_id,
                "to_node_id": item.to_node_id,
                "distance_m": item.distance_m,
                "travel_time_s": max(0, round(costs.edge_travel_time_s[item.edge_id])),
                "directed": item.directed,
                "channel_zone_ids": list(item.channel_zone_ids),
            }
            for item in layout.edges
        ],
        "path_costs": path_costs,
        "slots": [
            {
                "position_id": item.space_id,
                "x_m": item.coordinate.x_m,
                "y_m": item.coordinate.y_m,
                "access_node_id": item.access_node_id,
                "stack_group_id": item.stack_group_id,
                "depth": item.depth,
                "channel_zone_ids": [],
            }
            for item in layout.spaces
        ],
        "buffer_slots": [
            {
                "position_id": item.buffer_id,
                "x_m": item.coordinate.x_m,
                "y_m": item.coordinate.y_m,
                "access_node_id": item.access_node_id,
                "channel_zone_ids": list(item.channel_zone_ids),
            }
            for item in layout.buffers
        ],
        "channel_zones": [
            {"channel_zone_id": item.channel_zone_id, "capacity": item.capacity}
            for item in layout.channel_zones
        ],
    }


def approved_config(layout: Layout) -> dict[str, Any]:
    active_buffers = [item.buffer_id for item in layout.buffers if item.available]
    return {
        "recoverability_policy": "strict_recoverable",
        "rolling_enabled": False,
        "arrival_wait_capacity": 8,
        "max_arrival_wait_s": 30,
        "max_departure_wait_s": 300,
        "use_soft_departure_information": False,
        "rolling_window_s": 900,
        "optimization_budget_s": 1.0,
        "fallback_target_s": 0.1,
        "minimum_logging_reserve_s": 0.02,
        "max_requests_per_solve": 12,
        "max_positions_per_arrival": max(1, len(layout.spaces)),
        "max_buffer_matchings_per_departure": 4,
        "max_action_plans_total": 64,
        "max_soft_future_records": 20,
        "buffer_count": len(active_buffers),
        "relocation_executor_capacity": 1,
        "executor_type": "simulation_only",
        "relocation_setup_s": 5.0,
        "relocation_speed_mps": 1.0,
        "active_buffer_position_ids": active_buffers,
    }
