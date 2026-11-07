"""Isolated NetworkX adapter that returns only ordinary immutable path values."""

from __future__ import annotations

from collections.abc import Mapping
from itertools import pairwise
from typing import Any

import networkx as nx  # type: ignore[import-untyped]

from parking_opt.layout.model import Layout, PathCost


class UnreachablePathError(ValueError):
    """Raised when a required entrance/position/exit route is disconnected."""


def _edge_weight(_u: str, _v: str, data: Mapping[str, Any]) -> float:
    if "distance_m" in data:
        return float(data["distance_m"])
    return min(float(item["distance_m"]) for item in data.values())


def _build_graph(layout: Layout) -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    for node in sorted(layout.road_nodes, key=lambda item: item.road_node_id):
        graph.add_node(node.road_node_id)
    for edge in sorted(layout.road_edges, key=lambda item: item.road_edge_id):
        attributes = {
            "road_edge_id": edge.road_edge_id,
            "distance_m": edge.distance_m,
            "travel_time_s": edge.travel_time_s,
            "channel_zone_ids": edge.channel_zone_ids,
        }
        graph.add_edge(
            edge.from_node_id,
            edge.to_node_id,
            key=edge.road_edge_id,
            **attributes,
        )
        if not edge.directed:
            graph.add_edge(
                edge.to_node_id,
                edge.from_node_id,
                key=f"{edge.road_edge_id}::reverse",
                **attributes,
            )
    return graph


def _edge_for_hop(
    graph: nx.MultiDiGraph,
    from_node_id: str,
    to_node_id: str,
) -> Mapping[str, Any]:
    candidates = graph.get_edge_data(from_node_id, to_node_id)
    if candidates is None:
        raise UnreachablePathError(f"missing graph hop {from_node_id}->{to_node_id}")
    return min(
        candidates.values(),
        key=lambda item: (
            float(item["distance_m"]),
            int(item["travel_time_s"]),
            str(item["road_edge_id"]),
        ),
    )


def materialize_path_costs(
    layout: Layout,
    *,
    require_all_relevant_pairs: bool = True,
) -> Layout:
    """Materialize deterministic shortest-distance costs as plain layout values."""

    graph = _build_graph(layout)
    relevant_nodes = {
        item.road_node_id for item in layout.road_nodes if item.node_kind in {"entrance", "exit"}
    }
    relevant_nodes.update(item.access_node_id for item in layout.slots)
    relevant_nodes.update(item.access_node_id for item in layout.buffer_slots)
    ordered_nodes = tuple(sorted(relevant_nodes))
    costs: list[PathCost] = []
    for from_node_id in ordered_nodes:
        for to_node_id in ordered_nodes:
            if from_node_id == to_node_id:
                node_path = [from_node_id]
            else:
                try:
                    node_path = nx.shortest_path(
                        graph,
                        source=from_node_id,
                        target=to_node_id,
                        weight=_edge_weight,
                        method="dijkstra",
                    )
                except nx.NetworkXNoPath as exc:
                    if require_all_relevant_pairs:
                        raise UnreachablePathError(
                            f"required path is unreachable: {from_node_id}->{to_node_id}"
                        ) from exc
                    continue
            edges = tuple(_edge_for_hop(graph, left, right) for left, right in pairwise(node_path))
            edge_ids = tuple(str(item["road_edge_id"]) for item in edges)
            zones: list[str] = []
            for edge in edges:
                for zone_id in edge["channel_zone_ids"]:
                    if zone_id not in zones:
                        zones.append(zone_id)
            costs.append(
                PathCost(
                    path_cost_id=f"pc::{from_node_id}::{to_node_id}",
                    from_node_id=from_node_id,
                    to_node_id=to_node_id,
                    distance_m=sum(float(item["distance_m"]) for item in edges),
                    travel_time_s=sum(int(item["travel_time_s"]) for item in edges),
                    road_edge_ids=edge_ids,
                    channel_zone_ids=tuple(zones),
                )
            )
    return layout.with_path_costs(
        tuple(sorted(costs, key=lambda item: (item.from_node_id, item.to_node_id)))
    )
