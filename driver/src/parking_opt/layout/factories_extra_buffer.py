"""C7 extra-buffer service-lane layout factory."""

from __future__ import annotations

from parking_opt.layout.factories import build_mixed_depth_layout
from parking_opt.layout.model import (
    BufferSlot,
    ChannelZone,
    Layout,
    RoadEdge,
    RoadNode,
)
from parking_opt.layout.networkx_adapter import materialize_path_costs

EXTRA_BUFFER_ORDER = ("mix-b001", "mix-b002")


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
