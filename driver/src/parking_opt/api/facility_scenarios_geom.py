"""Geometry helpers for facility scenario generation."""

from __future__ import annotations

from math import hypot
from typing import Literal

from parking_opt.api.models import Coordinate, FacilityEdge, FacilityNode, FacilityZone, RoadNode


def _edge(edge_id: str, left: FacilityNode, right: FacilityNode, *, directed: bool, channel: str) -> FacilityEdge:
    distance = hypot(
        right.coordinate.x_m - left.coordinate.x_m, right.coordinate.y_m - left.coordinate.y_m
    )
    return FacilityEdge(
        edge_id=edge_id,
        from_node_id=left.node_id,
        to_node_id=right.node_id,
        centerline=(left.coordinate, right.coordinate),
        width_m=6,
        distance_m=distance,
        base_travel_time_s=max(2, round(distance / 4)),
        directed=directed,
        channel_zone_ids=(channel,),
    )


def _node(
    node_id: str,
    x_m: float,
    y_m: float,
    kind: Literal["entrance", "exit", "junction", "space_access", "buffer_access", "inter_floor"],
    label: str,
) -> FacilityNode:
    return FacilityNode(node_id=node_id, floor_id="floor-1", coordinate=Coordinate(x_m=x_m, y_m=y_m), kind=kind, label=label)


def _zone(
    zone_id: str,
    label: str,
    kind: Literal["parking", "charging", "tandem", "buffer", "restricted", "service", "pedestrian"],
    polygon: tuple[Coordinate, ...],
) -> FacilityZone:
    return FacilityZone(zone_id=zone_id, floor_id="floor-1", label=label, kind=kind, polygon=polygon)


def _project_node(item: FacilityNode) -> RoadNode:
    if item.kind == "inter_floor":
        raise ValueError("Layout 2.0 compatibility projection does not support inter-floor nodes")
    return RoadNode(node_id=item.node_id, coordinate=item.coordinate, kind=item.kind, label=item.label)
