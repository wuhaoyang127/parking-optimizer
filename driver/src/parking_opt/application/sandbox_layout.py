"""Sandbox layout construction and configuration."""

from __future__ import annotations

from typing import Any

from parking_opt.application.sandbox_types import _SCHEMA_VERSION
from parking_opt.layout.model import BufferSlot, ChannelZone, Layout, RoadEdge, RoadNode, Slot
from parking_opt.layout.networkx_adapter import materialize_path_costs


def _sandbox_config(layout: Layout) -> dict[str, Any]:
    return {
        "recoverability_policy": "risk_accepting",
        "rolling_enabled": False,
        "arrival_wait_capacity": 3,
        "max_arrival_wait_s": 120,
        "max_departure_wait_s": 300,
        "use_soft_departure_information": True,
        "rolling_window_s": 900,
        "optimization_budget_s": 1.0,
        "fallback_target_s": 0.1,
        "minimum_logging_reserve_s": 0.02,
        "max_requests_per_solve": 12,
        "max_positions_per_arrival": 8,
        "max_buffer_matchings_per_departure": 4,
        "max_action_plans_total": 64,
        "max_soft_future_records": 20,
        "buffer_count": len(layout.buffer_slots),
        "relocation_executor_capacity": 1,
        "executor_type": "simulation_only",
        "relocation_setup_s": 5.0,
        "relocation_speed_mps": 1.0,
        "active_buffer_position_ids": [item.position_id for item in layout.buffer_slots],
    }


def build_compact_sandbox_layout() -> Layout:
    """Build a readable 24-normal-position mixed-depth teaching layout."""

    nodes = (
        RoadNode("entry-main", 0.0, 0.0, "entrance"),
        *(
            RoadNode(f"access-{index:02d}", float(index * 10), 0.0, "position_access")
            for index in range(1, 7)
        ),
        RoadNode("exit-main", 70.0, 0.0, "exit"),
    )
    edges = tuple(
        RoadEdge(
            road_edge_id=f"road-{index:02d}",
            from_node_id=nodes[index - 1].road_node_id,
            to_node_id=nodes[index].road_node_id,
            distance_m=10.0,
            travel_time_s=10,
            directed=False,
            channel_zone_ids=("zone-main",),
        )
        for index in range(1, len(nodes))
    )
    independent = tuple(
        Slot(
            position_id=f"demo-i{index:02d}",
            x_m=float(index * 10),
            y_m=4.0,
            access_node_id=f"access-{index:02d}",
            stack_group_id=f"demo-ig{index:02d}",
            depth=1,
            channel_zone_ids=("zone-main",),
        )
        for index in range(1, 7)
    )
    tandem: list[Slot] = []
    for group_index in range(1, 10):
        access_index = ((group_index - 1) % 6) + 1
        row_index = (group_index - 1) // 6
        for depth in (1, 2):
            tandem.append(
                Slot(
                    position_id=f"demo-g{group_index:02d}-d{depth}",
                    x_m=float(access_index * 10),
                    y_m=float(10 + row_index * 7 + depth * 2),
                    access_node_id=f"access-{access_index:02d}",
                    stack_group_id=f"demo-g{group_index:02d}",
                    depth=depth,
                    channel_zone_ids=("zone-main",),
                )
            )
    layout = Layout(
        schema_version=_SCHEMA_VERSION,
        layout_id="synthetic-compact-crowded-v1",
        coordinate_origin_note="synthetic teaching layout in local metres; not surveyed",
        road_nodes=nodes,
        road_edges=edges,
        path_costs=(),
        slots=(*independent, *tandem),
        buffer_slots=(
            BufferSlot(
                position_id="demo-buffer-01",
                x_m=0.0,
                y_m=-7.0,
                access_node_id="entry-main",
                channel_zone_ids=("zone-main",),
            ),
        ),
        channel_zones=(ChannelZone("zone-main", 1),),
    )
    return materialize_path_costs(layout)
