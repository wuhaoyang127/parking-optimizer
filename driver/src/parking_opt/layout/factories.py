"""Deterministic C2 baseline layout factories with preregistered buffer order."""

from __future__ import annotations

from itertools import pairwise

from parking_opt.layout.model import (
    BufferSlot,
    ChannelZone,
    Layout,
    RoadEdge,
    RoadNode,
    Slot,
)
from parking_opt.layout.networkx_adapter import materialize_path_costs

BUFFER_CANDIDATE_ORDER = {
    "independent": ("ind-s099", "ind-s100"),
    "mixed_depth": ("mix-i019", "mix-i020"),
}
EXTRA_BUFFER_ORDER = ("mix-b001", "mix-b002")


def _roadway() -> tuple[tuple[RoadNode, ...], tuple[RoadEdge, ...]]:
    nodes = [
        RoadNode("entry-main", 0.0, 0.0, "entrance"),
        *(
            RoadNode(f"access-{index:02d}", float((index + 1) * 10), 0.0, "position_access")
            for index in range(10)
        ),
        RoadNode("exit-main", 110.0, 0.0, "exit"),
    ]
    node_ids = [item.road_node_id for item in nodes]
    edges = tuple(
        RoadEdge(
            road_edge_id=f"road-{index:02d}",
            from_node_id=left,
            to_node_id=right,
            distance_m=10.0,
            travel_time_s=10,
            directed=False,
            channel_zone_ids=("zone-main",),
        )
        for index, (left, right) in enumerate(
            pairwise(node_ids),
            start=1,
        )
    )
    return tuple(nodes), edges


def _convert_buffers(
    slots: tuple[Slot, ...],
    family: str,
    buffer_count: int,
) -> tuple[tuple[Slot, ...], tuple[BufferSlot, ...]]:
    if buffer_count not in {0, 1, 2}:
        raise ValueError("buffer_count must be 0, 1, or 2")
    selected = set(BUFFER_CANDIDATE_ORDER[family][:buffer_count])
    normal = tuple(item for item in slots if item.position_id not in selected)
    by_id = {item.position_id: item for item in slots}
    buffers = tuple(
        BufferSlot(
            position_id=position_id,
            x_m=by_id[position_id].x_m,
            y_m=by_id[position_id].y_m,
            access_node_id=by_id[position_id].access_node_id,
            channel_zone_ids=by_id[position_id].channel_zone_ids,
        )
        for position_id in BUFFER_CANDIDATE_ORDER[family][:buffer_count]
    )
    return normal, buffers


def build_independent_layout(buffer_count: int = 0) -> Layout:
    """Build 100 physical independent positions with stable optional conversion."""

    nodes, edges = _roadway()
    base_slots = tuple(
        Slot(
            position_id=f"ind-s{index:03d}",
            x_m=float(((index - 1) % 10 + 1) * 10),
            y_m=float(2 + 2 * ((index - 1) // 10)),
            access_node_id=f"access-{(index - 1) % 10:02d}",
            stack_group_id=f"ind-g{index:03d}",
            depth=1,
            channel_zone_ids=("zone-main",),
        )
        for index in range(1, 101)
    )
    slots, buffers = _convert_buffers(base_slots, "independent", buffer_count)
    layout = Layout(
        schema_version="1.0.0",
        layout_id=f"independent-fixed-total-b{buffer_count}-v1",
        coordinate_origin_note="synthetic C2 local-metre baseline; not a surveyed layout",
        road_nodes=nodes,
        road_edges=edges,
        path_costs=(),
        slots=slots,
        buffer_slots=buffers,
        channel_zones=(ChannelZone("zone-main", 1),),
    )
    return materialize_path_costs(layout)


def build_mixed_depth_layout(buffer_count: int = 0) -> Layout:
    """Build 100 physical positions: 20 independent and forty two-deep groups."""

    nodes, edges = _roadway()
    independent = tuple(
        Slot(
            position_id=f"mix-i{index:03d}",
            x_m=float(((index - 1) % 10 + 1) * 10),
            y_m=float(3 + 3 * ((index - 1) // 10)),
            access_node_id=f"access-{(index - 1) % 10:02d}",
            stack_group_id=f"mix-ig{index:03d}",
            depth=1,
            channel_zone_ids=("zone-main",),
        )
        for index in range(1, 21)
    )
    tandem: list[Slot] = []
    for group_index in range(1, 41):
        access_index = (group_index - 1) % 10
        row_index = (group_index - 1) // 10
        for depth in (1, 2):
            tandem.append(
                Slot(
                    position_id=f"mix-g{group_index:03d}-d{depth}",
                    x_m=float((access_index + 1) * 10),
                    y_m=float(10 + row_index * 6 + depth * 2),
                    access_node_id=f"access-{access_index:02d}",
                    stack_group_id=f"mix-g{group_index:03d}",
                    depth=depth,
                    channel_zone_ids=("zone-main",),
                )
            )
    slots, buffers = _convert_buffers(
        (*independent, *tandem),
        "mixed_depth",
        buffer_count,
    )
    layout = Layout(
        schema_version="1.0.0",
        layout_id=f"mixed-depth-fixed-total-b{buffer_count}-v1",
        coordinate_origin_note="synthetic C2 local-metre baseline; not a surveyed layout",
        road_nodes=nodes,
        road_edges=edges,
        path_costs=(),
        slots=slots,
        buffer_slots=buffers,
        channel_zones=(ChannelZone("zone-main", 1),),
    )
    return materialize_path_costs(layout)


def build_mixed_depth_extra_buffer_layout(buffer_count: int) -> Layout:
    """Keep 100 normal positions and add one or two synthetic service-lane buffers."""

    if buffer_count not in {1, 2}:
        raise ValueError("extra buffer_count must be 1 or 2")
    baseline = build_mixed_depth_layout(0)
    buffer_nodes = (
        RoadNode("buffer-access-01", 0.0, -10.0, "position_access"),
        RoadNode("buffer-access-02", 0.0, -20.0, "position_access"),
    )
    buffer_edges = (
        RoadEdge(
            "buffer-road-01",
            "entry-main",
            "buffer-access-01",
            10.0,
            10,
            False,
            ("zone-main",),
        ),
        RoadEdge(
            "buffer-road-02",
            "buffer-access-01",
            "buffer-access-02",
            10.0,
            10,
            False,
            ("zone-main",),
        ),
    )
    buffers = tuple(
        BufferSlot(
            position_id=position_id,
            x_m=0.0,
            y_m=float(-10 * index),
            access_node_id=f"buffer-access-{index:02d}",
            channel_zone_ids=("zone-main",),
        )
        for index, position_id in enumerate(
            EXTRA_BUFFER_ORDER[:buffer_count],
            start=1,
        )
    )
    layout = Layout(
        schema_version="1.0.0",
        layout_id=f"mixed-depth-extra-buffer-b{buffer_count}-v1",
        coordinate_origin_note=("synthetic C7 extra-buffer service lane; not a surveyed layout"),
        road_nodes=(*baseline.road_nodes, *buffer_nodes),
        road_edges=(*baseline.road_edges, *buffer_edges),
        path_costs=(),
        slots=baseline.slots,
        buffer_slots=buffers,
        channel_zones=baseline.channel_zones,
    )
    return materialize_path_costs(layout)
