"""Copy validated layout facts into the third-party-free authoritative state."""

from __future__ import annotations

from parking_opt.domain.enums import PositionKind
from parking_opt.domain.invariants import assert_state_invariants
from parking_opt.domain.records import PositionState
from parking_opt.domain.state import (
    AuthoritativeState,
    PathCostReference,
    PositionMetadata,
    empty_authoritative_state,
)
from parking_opt.layout.model import Layout


def initial_state_from_layout(
    layout: Layout,
    *,
    run_id: str,
    scenario_id: str,
    active_buffer_position_ids: tuple[str, ...],
    relocation_executor_capacity: int,
    arrival_wait_capacity: int,
    max_arrival_wait_s: int,
) -> AuthoritativeState:
    """Create state version zero without retaining NetworkX or mutable layout objects."""

    known_buffers = {item.position_id for item in layout.buffer_slots}
    if not set(active_buffer_position_ids) <= known_buffers:
        raise ValueError("active buffers must be a subset of layout buffer positions")
    position_metadata = (
        *(
            PositionMetadata(
                position_id=item.position_id,
                position_kind=PositionKind.NORMAL,
                access_node_id=item.access_node_id,
                stack_group_id=item.stack_group_id,
                depth=item.depth,
                channel_zone_ids=item.channel_zone_ids,
            )
            for item in layout.slots
        ),
        *(
            PositionMetadata(
                position_id=item.position_id,
                position_kind=PositionKind.BUFFER,
                access_node_id=item.access_node_id,
                stack_group_id=None,
                depth=None,
                channel_zone_ids=item.channel_zone_ids,
            )
            for item in layout.buffer_slots
        ),
    )
    positions = (
        *(
            PositionState(
                position_id=item.position_id,
                position_kind=PositionKind.NORMAL,
                physically_available=True,
                assignable=True,
                planned_closure=False,
                occupant_vehicle_id=None,
            )
            for item in layout.slots
        ),
        *(
            PositionState(
                position_id=item.position_id,
                position_kind=PositionKind.BUFFER,
                physically_available=item.position_id in active_buffer_position_ids,
                assignable=False,
                planned_closure=False,
                occupant_vehicle_id=None,
            )
            for item in layout.buffer_slots
        ),
    )
    exits = tuple(item.road_node_id for item in layout.road_nodes if item.node_kind == "exit")
    state = empty_authoritative_state(
        run_id=run_id,
        scenario_id=scenario_id,
        layout_id=layout.layout_id,
        position_metadata=tuple(position_metadata),
        exit_node_ids=exits,
        path_costs=tuple(
            PathCostReference(
                from_node_id=item.from_node_id,
                to_node_id=item.to_node_id,
                distance_m=item.distance_m,
                travel_time_s=item.travel_time_s,
                channel_zone_ids=item.channel_zone_ids,
            )
            for item in layout.path_costs
        ),
        positions=tuple(positions),
        executor_capacity=relocation_executor_capacity,
        channel_zone_capacities=tuple(
            (item.channel_zone_id, item.capacity) for item in layout.channel_zones
        ),
        active_buffer_position_ids=active_buffer_position_ids,
        arrival_wait_capacity=arrival_wait_capacity,
        max_arrival_wait_s=max_arrival_wait_s,
    )
    assert_state_invariants(state)
    return state
