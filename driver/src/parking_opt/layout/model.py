"""Third-party-free immutable parking-layout values."""

from __future__ import annotations

from dataclasses import dataclass, replace


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


from parking_opt.layout.serialization import layout_from_mapping, layout_to_mapping  # noqa: E402
