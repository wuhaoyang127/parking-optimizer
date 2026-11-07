"""Deterministic dynamic shortest-path service for web-v2."""

from __future__ import annotations

import heapq
from collections.abc import Mapping
from dataclasses import dataclass
from math import atan2, degrees, hypot, isfinite

from parking_opt.api.models import CostSnapshot, Layout, RoadEdge, Route, RouteInstruction


class RouteInputError(ValueError):
    """Raised when layout/cost scope is inconsistent or incomplete."""


class RouteNotFoundError(ValueError):
    """Raised when no directed path exists between two known nodes."""


@dataclass(frozen=True, slots=True)
class _Arc:
    edge: RoadEdge
    from_node_id: str
    to_node_id: str


class RouteCostService:
    """Compute reproducible routes using a caller-visible cost snapshot only."""

    def __init__(self) -> None:
        self._entrance_headings: dict[tuple[str, str, str], float] = {}

    def register_entrance_headings(
        self, parking_lot_id: str, layout_version: str, headings: Mapping[str, float]
    ) -> None:
        """Register published display headings without changing route selection."""
        if any(not isfinite(value) or not 0 <= value < 360 for value in headings.values()):
            raise RouteInputError("entrance display heading must be finite and within [0, 360)")
        for node_id, heading in headings.items():
            self._entrance_headings[parking_lot_id, layout_version, node_id] = heading

    def route(
        self,
        layout: Layout,
        costs: CostSnapshot,
        *,
        from_node_id: str,
        to_node_id: str,
    ) -> Route:
        self._validate(layout, costs)
        node_ids = {item.node_id for item in layout.nodes}
        if from_node_id not in node_ids or to_node_id not in node_ids:
            raise RouteInputError("route endpoint is not present in the layout")
        if from_node_id == to_node_id:
            return Route(
                parking_lot_id=layout.parking_lot_id,
                layout_version=layout.layout_version,
                cost_version=costs.cost_version,
                from_node_id=from_node_id,
                to_node_id=to_node_id,
                node_ids=(from_node_id,),
                edge_ids=(),
                distance_m=0,
                dynamic_eta_s=0,
                instructions=(),
            )

        adjacency: dict[str, list[_Arc]] = {node_id: [] for node_id in node_ids}
        for edge in layout.edges:
            if edge.edge_id in costs.unavailable_edge_ids:
                continue
            adjacency[edge.from_node_id].append(_Arc(edge, edge.from_node_id, edge.to_node_id))
            if not edge.directed:
                adjacency[edge.to_node_id].append(_Arc(edge, edge.to_node_id, edge.from_node_id))
        for arcs in adjacency.values():
            arcs.sort(key=lambda item: (item.edge.edge_id, item.to_node_id))

        # Key order makes ties stable: ETA, distance, edge-id sequence, node-id sequence.
        queue: list[tuple[float, float, tuple[str, ...], tuple[str, ...], str]] = [
            (0.0, 0.0, (), (from_node_id,), from_node_id)
        ]
        best: dict[str, tuple[float, float, tuple[str, ...], tuple[str, ...]]] = {}
        chosen: tuple[float, float, tuple[str, ...], tuple[str, ...]] | None = None
        while queue:
            eta, distance, edge_ids, path_nodes, current = heapq.heappop(queue)
            key = (eta, distance, edge_ids, path_nodes)
            if current in best and best[current] <= key:
                continue
            best[current] = key
            if current == to_node_id:
                chosen = key
                break
            for arc in adjacency[current]:
                heapq.heappush(
                    queue,
                    (
                        eta + costs.edge_travel_time_s[arc.edge.edge_id],
                        distance + arc.edge.distance_m,
                        (*edge_ids, arc.edge.edge_id),
                        (*path_nodes, arc.to_node_id),
                        arc.to_node_id,
                    ),
                )
        if chosen is None:
            raise RouteNotFoundError(f"no route from {from_node_id} to {to_node_id}")
        eta, distance, edge_ids, path_nodes = chosen
        edge_by_id = {item.edge_id: item for item in layout.edges}
        nodes = {item.node_id: item for item in layout.nodes}
        previous_heading = self._entrance_headings.get(
            (layout.parking_lot_id, layout.layout_version, from_node_id)
        )
        guidance: list[RouteInstruction] = []
        for index, edge_id in enumerate(edge_ids, start=1):
            start = nodes[path_nodes[index - 1]].coordinate
            end = nodes[path_nodes[index]].coordinate
            dx, dy = end.x_m - start.x_m, end.y_m - start.y_m
            heading = (
                degrees(atan2(dy, dx))
                if isfinite(dx) and isfinite(dy) and hypot(dx, dy) > 1e-9
                else None
            )
            action = "沿高亮通道前行"
            if heading is not None and previous_heading is not None:
                # Default management canvas: x right, y down; positive turns go right.
                turn = (heading - previous_heading + 180) % 360 - 180
                if abs(turn) <= 30 + 1e-9:
                    action = "直行"
                elif abs(turn) >= 150 - 1e-9:
                    action = "按高亮路线调整方向后前行"
                else:
                    action = "右转后前行" if turn > 0 else "左转后前行"
            edge = edge_by_id[edge_id]
            text = f"{action} {edge.distance_m:g} 米至{nodes[path_nodes[index]].label}。"
            if index == len(edge_ids):
                text += "到达目标区域。请核对目标并自行确认。"
            guidance.append(
                RouteInstruction(
                    sequence=index,
                    edge_id=edge_id,
                    text=text,
                    distance_m=edge.distance_m,
                    travel_time_s=costs.edge_travel_time_s[edge_id],
                )
            )
            previous_heading = heading
        instructions = tuple(guidance)
        return Route(
            parking_lot_id=layout.parking_lot_id,
            layout_version=layout.layout_version,
            cost_version=costs.cost_version,
            from_node_id=from_node_id,
            to_node_id=to_node_id,
            node_ids=path_nodes,
            edge_ids=edge_ids,
            distance_m=distance,
            dynamic_eta_s=eta,
            instructions=instructions,
        )

    @staticmethod
    def _validate(layout: Layout, costs: CostSnapshot) -> None:
        if layout.parking_lot_id != costs.parking_lot_id:
            raise RouteInputError("parking_lot_id mismatch between layout and costs")
        if layout.layout_version != costs.layout_version:
            raise RouteInputError("layout_version mismatch between layout and costs")
        edge_ids = {item.edge_id for item in layout.edges}
        cost_edge_ids = set(costs.edge_travel_time_s)
        if edge_ids != cost_edge_ids:
            missing = sorted(edge_ids - cost_edge_ids)
            unknown = sorted(cost_edge_ids - edge_ids)
            raise RouteInputError(
                f"cost edge domain mismatch; missing={missing}, unknown={unknown}"
            )
        unknown_unavailable = set(costs.unavailable_edge_ids) - edge_ids
        if unknown_unavailable:
            raise RouteInputError(
                f"unavailable edge domain mismatch: {sorted(unknown_unavailable)}"
            )
