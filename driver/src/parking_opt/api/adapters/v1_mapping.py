"""Build the v1 layout mapping and approved config from v2 visible values."""

from __future__ import annotations

import heapq
from typing import Any

from parking_opt.api.models import CostSnapshot, Layout
from parking_opt.api.routing import RouteCostService


def _routes_from(route_service: RouteCostService, layout: Layout, costs: CostSnapshot,
                 from_node_id: str) -> dict[str, tuple[float, float, tuple, tuple]]:
    """从 from_node 一次 Dijkstra 算到所有可达节点。

    复刻 RouteCostService.route 的成本模型与元组排序（不早停、不算指引），
    返回 {to_node_id: (distance_m, eta_s, edge_ids, path_nodes)}。供 v1_layout_mapping
    一次取到所有目标的最短路径，把 O(n²) 次 route 降到 O(n) 次 Dijkstra。
    """
    RouteCostService._validate(layout, costs)
    node_ids = {item.node_id for item in layout.nodes}
    adjacency: dict[str, list[tuple]] = {nid: [] for nid in node_ids}
    for edge in layout.edges:
        if edge.edge_id in costs.unavailable_edge_ids:
            continue
        adjacency[edge.from_node_id].append((edge, edge.to_node_id))
        if not edge.directed:
            adjacency[edge.to_node_id].append((edge, edge.from_node_id))
    for arcs in adjacency.values():
        arcs.sort(key=lambda item: (item[0].edge_id, item[1]))
    queue = [(0.0, 0.0, (), (from_node_id,), from_node_id)]
    best: dict[str, tuple] = {}
    result: dict[str, tuple[float, float, tuple, tuple]] = {}
    while queue:
        eta, distance, edge_ids, path_nodes, current = heapq.heappop(queue)
        key = (eta, distance, edge_ids, path_nodes)
        if current in best and best[current] <= key:
            continue
        best[current] = key
        result[current] = (distance, eta, edge_ids, path_nodes)
        for edge, to_node in adjacency[current]:
            heapq.heappush(queue, (
                eta + costs.edge_travel_time_s[edge.edge_id],
                distance + edge.distance_m,
                (*edge_ids, edge.edge_id),
                (*path_nodes, to_node),
                to_node,
            ))
    return result


def v1_layout_mapping(route_service, layout: Layout, costs: CostSnapshot) -> dict[str, Any]:
    relevant_nodes = sorted(
        {
            *layout.entrance_node_ids,
            *layout.exit_node_ids,
            *(item.access_node_id for item in layout.spaces),
            *(item.access_node_id for item in layout.buffers),
        }
    )
    edge_by_id = {item.edge_id: item for item in layout.edges}
    path_costs: list[dict[str, Any]] = []
    for from_node in relevant_nodes:
        routes = _routes_from(route_service, layout, costs, from_node)
        for to_node in relevant_nodes:
            if to_node not in routes:
                continue
            distance_m, _, edge_ids, _ = routes[to_node]
            zones = tuple(
                dict.fromkeys(
                    zone
                    for edge_id in edge_ids
                    for zone in edge_by_id[edge_id].channel_zone_ids
                )
            )
            path_costs.append(
                {
                    "path_cost_id": f"path-{from_node}-{to_node}",
                    "from_node_id": from_node,
                    "to_node_id": to_node,
                    "distance_m": distance_m,
                    "travel_time_s": sum(max(0, round(costs.edge_travel_time_s[eid])) for eid in edge_ids),
                    "road_edge_ids": list(edge_ids),
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
