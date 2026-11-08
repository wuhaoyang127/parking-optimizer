"""Build one deterministic public facility scenario."""
from __future__ import annotations
from itertools import pairwise
from parking_opt.api.facility_scenarios_geom import _edge, _node, _zone
from parking_opt.api.facility_scenarios_types import PUBLISHED_AT, FacilityScenarioSpec, PublishedFacilityScenario
from parking_opt.api.models import (
    ChannelZone,
    Coordinate,
    FacilityBounds,
    FacilityBuffer,
    FacilityBufferState,
    FacilityEntrance,
    FacilityExit,
    FacilityFloor,
    FacilityObservationSource,
    FacilityProvenance,
    FacilityRectangle,
    FacilitySourceKind,
    FacilitySourceStatus,
    FacilitySpace,
    FacilitySpaceState,
    FacilityTandemGroup,
    HealthStatus,
    ParkingFacilityLayout,
    ParkingFacilityStateSnapshot,
    SpaceStatus,
)
from parking_opt.api.facility_scenarios_bundle import _project_bundle
def _build_scenario(spec: FacilityScenarioSpec) -> PublishedFacilityScenario:
    bounds = FacilityBounds(min_x_m=0, min_y_m=0, max_x_m=120, max_y_m=80)
    ring = (
        _node("junction-nw", 15, 15, "junction", "西北路口"),
        _node("junction-ne", 105, 15, "junction", "东北路口"),
        _node("junction-se", 105, 65, "junction", "东南路口"),
        _node("junction-sw", 15, 65, "junction", "西南路口"),
    )
    entrances = [_node("entrance-west", 5, 15, "entrance", "西入口")]
    exits = [_node("exit-west", 5, 65, "exit", "西出口")]
    if spec.entrances == 2:
        entrances.append(_node("entrance-east", 115, 65, "entrance", "东入口"))
    if spec.exits == 2:
        exits.append(_node("exit-east", 115, 15, "exit", "东出口"))
    independent_count = spec.spaces - spec.tandem_groups * 2
    independent_xs = tuple(22 + column * 5.5 for column in range((independent_count + 3) // 4))
    tandem_start_x = 94 - (spec.tandem_groups - 1) * 8
    tandem_xs = tuple(tandem_start_x + group * 8 for group in range(spec.tandem_groups))
    north_xs = tuple(sorted({*independent_xs, *tandem_xs}))
    south_xs = independent_xs
    def access_id(lane: str, x_m: float) -> str:
        return f"access-{lane}-{round(x_m * 10)}"
    access_nodes = tuple(
        _node(access_id(lane, x_m), x_m, y_m, "space_access", f"{label}{index + 1}")
        for lane, y_m, label, values in (
            ("north", 30, "北停车巷接入点", north_xs),
            ("south", 50, "南停车巷接入点", south_xs),
        )
        for index, x_m in enumerate(values)
    )
    lane_gateways = (
        _node("lane-north-west", 15, 30, "junction", "北停车巷西口"),
        _node("lane-north-east", 105, 30, "junction", "北停车巷东口"),
        _node("lane-south-west", 15, 50, "junction", "南停车巷西口"),
        _node("lane-south-east", 105, 50, "junction", "南停车巷东口"),
    )
    buffer_nodes = tuple(
        _node(f"buffer-access-{i + 1}", 96 + i * 10, 68, "buffer_access", f"移车缓冲区{i + 1}")
        for i in range(spec.buffers)
    )
    nodes = (*ring, *entrances, *exits, *access_nodes, *lane_gateways, *buffer_nodes)
    by_id = {item.node_id: item for item in nodes}
    edges = [
        _edge("ring-north", ring[0], ring[1], directed=spec.ring_directed, channel="channel-ring"),
        _edge("ring-east", ring[1], ring[2], directed=spec.ring_directed, channel="channel-ring"),
        _edge("ring-south", ring[2], ring[3], directed=spec.ring_directed, channel="channel-ring"),
        _edge("ring-west", ring[3], ring[0], directed=spec.ring_directed, channel="channel-ring"),
        _edge("entry-west", by_id["entrance-west"], ring[0], directed=True, channel="channel-entry"),
        _edge("exit-west", ring[3], by_id["exit-west"], directed=True, channel="channel-exit"),
    ]
    if spec.entrances == 2:
        edges.append(_edge("entry-east", by_id["entrance-east"], ring[2], directed=True, channel="channel-entry"))
    if spec.exits == 2:
        edges.append(_edge("exit-east", ring[1], by_id["exit-east"], directed=True, channel="channel-exit"))
    access_by_id = {item.node_id: item for item in access_nodes}
    for lane, values, west_gate, east_gate, west_anchor, east_anchor in (
        ("north", north_xs, lane_gateways[0], lane_gateways[1], ring[0], ring[1]),
        ("south", south_xs, lane_gateways[2], lane_gateways[3], ring[3], ring[2]),
    ):
        lane_nodes = tuple(access_by_id[access_id(lane, x_m)] for x_m in values)
        path = (west_anchor, west_gate, *lane_nodes, east_gate, east_anchor)
        edges.extend(
            _edge(f"lane-{lane}-{index + 1}", left, right, directed=True, channel="channel-rows")
            for index, (left, right) in enumerate(pairwise(path))
        )
    for index, node in enumerate(buffer_nodes):
        edges.append(_edge(f"buffer-{index + 1}", ring[2], node, directed=False, channel="channel-buffer"))
    charging_ids = {f"P-{index:02d}" for index in range(1, spec.charging + 1)}
    spaces: list[FacilitySpace] = []
    for index in range(1, independent_count + 1):
        row, column = (index - 1) % 4, (index - 1) // 4
        space_id = f"P-{index:02d}"
        spaces.append(
            FacilitySpace(parking_lot_id=spec.lot_id, space_id=space_id, floor_id="floor-1", zone_id="zone-charging" if space_id in charging_ids else "zone-parking", geometry=FacilityRectangle(center=Coordinate(x_m=independent_xs[column], y_m=(24, 36, 44, 56)[row]), width_m=2.6, length_m=5.2, heading_deg=90), access_node_id=access_id("north" if row < 2 else "south", independent_xs[column]), charging=space_id in charging_ids)
        )
    tandem_groups: list[FacilityTandemGroup] = []
    for group_index in range(spec.tandem_groups):
        group_id, pair_ids = f"stack-{group_index + 1}", []
        for depth in (1, 2):
            sequence = independent_count + group_index * 2 + depth
            space_id = f"P-{sequence:02d}"
            pair_ids.append(space_id)
            spaces.append(
                FacilitySpace(parking_lot_id=spec.lot_id, space_id=space_id, floor_id="floor-1", zone_id="zone-tandem", geometry=FacilityRectangle(center=Coordinate(x_m=tandem_xs[group_index], y_m=30 + depth * 5.5), width_m=2.6, length_m=5.2, heading_deg=0), access_node_id=access_id("north", tandem_xs[group_index]), stack_group_id=group_id, depth=depth)
            )
        tandem_groups.append(
            FacilityTandemGroup(
                stack_group_id=group_id,
                space_ids_near_to_deep=tuple(pair_ids),
                buffer_ids=(f"BUF-{group_index % spec.buffers + 1:02d}",),
            )
        )
    buffers = tuple(
        FacilityBuffer(parking_lot_id=spec.lot_id, buffer_id=f"BUF-{index + 1:02d}", floor_id="floor-1", zone_id="zone-buffer", geometry=FacilityRectangle(center=Coordinate(x_m=96 + index * 10, y_m=74), width_m=3, length_m=6, heading_deg=90), access_node_id=buffer_nodes[index].node_id, stack_group_ids=tuple(f"stack-{group + 1}" for group in range(spec.tandem_groups) if group % spec.buffers == index))
        for index in range(spec.buffers)
    )
    def rectangle_zone(min_x: float, min_y: float, max_x: float, max_y: float):
        return (
            Coordinate(x_m=min_x, y_m=min_y),
            Coordinate(x_m=max_x, y_m=min_y),
            Coordinate(x_m=max_x, y_m=max_y),
            Coordinate(x_m=min_x, y_m=max_y),
        )
    zones = (
        _zone("zone-parking", "普通停车区", "parking", rectangle_zone(18, 20, max(independent_xs) + 4, 60)),
        _zone("zone-charging", "充电停车区", "charging", rectangle_zone(18, 20, 40, 60)),
        _zone("zone-tandem", "纵深停车区", "tandem", rectangle_zone(min(tandem_xs) - 4, 31, max(tandem_xs) + 4, 45)),
        _zone("zone-buffer", "移车缓冲区", "buffer", rectangle_zone(90, 68, 116, 79)),
    )
    layout_version = f"{spec.scenario_id}-layout-1"
    layout = ParkingFacilityLayout(
        parking_lot_id=spec.lot_id,
        layout_version=layout_version,
        provenance=FacilityProvenance(
            source_kind=FacilitySourceKind.SYNTHETIC,
            source_name="web-v2 public deterministic facility generator",
            source_revision="m4-r1-v1",
            published_at=PUBLISHED_AT,
        ),
        coordinate_origin_note="south-west facility corner; local planar meters",
        bounds=bounds,
        default_floor_id="floor-1",
        floors=(FacilityFloor(floor_id="floor-1", label="地面层", elevation_m=0, bounds=bounds),),
        zones=zones,
        nodes=nodes,
        edges=tuple(edges),
        channel_zones=tuple(
            ChannelZone(channel_zone_id=item, capacity=1)
            for item in ("channel-ring", "channel-entry", "channel-exit", "channel-rows", "channel-buffer")
        ),
        entrances=tuple(
            FacilityEntrance(entrance_id=f"entrance-{i + 1}", node_id=node.node_id, label=node.label, initial_heading_deg=0)
            for i, node in enumerate(entrances)
        ),
        exits=tuple(FacilityExit(exit_id=f"exit-{i + 1}", node_id=node.node_id, label=node.label) for i, node in enumerate(exits)),
        default_entrance_id="entrance-1",
        spaces=tuple(spaces),
        tandem_groups=tuple(tandem_groups),
        buffers=buffers,
    )
    occupied_candidates = tuple(item for item in spaces if not item.charging and item.stack_group_id is None)
    occupied_ids = {item.space_id for item in occupied_candidates[: spec.occupied]}
    state = ParkingFacilityStateSnapshot(
        parking_lot_id=spec.lot_id,
        layout_version=layout_version,
        scenario_id=spec.scenario_id,
        scenario_version="scenario-1",
        state_version="state-base-1",
        observed_at=PUBLISHED_AT,
        source=FacilitySourceStatus(
            source_kind=FacilitySourceKind.SYNTHETIC,
            health=HealthStatus.HEALTHY,
            source_name="web-v2 public deterministic facility generator",
            updated_at=PUBLISHED_AT,
        ),
        spaces=tuple(
            FacilitySpaceState(space_id=item.space_id, observed_status=SpaceStatus.OCCUPIED if item.space_id in occupied_ids else SpaceStatus.AVAILABLE, observation_source=FacilityObservationSource.SYNTHETIC_TRUTH, effective_status=SpaceStatus.OCCUPIED if item.space_id in occupied_ids else SpaceStatus.AVAILABLE, assignable=item.space_id not in occupied_ids, reason_codes=("SPACE_OCCUPIED",) if item.space_id in occupied_ids else ())
            for item in spaces
        ),
        buffers=tuple(
            FacilityBufferState(
                buffer_id=item.buffer_id,
                status=SpaceStatus.AVAILABLE,
                observation_source=FacilityObservationSource.SYNTHETIC_TRUTH,
            )
            for item in buffers
        ),
    ).require_layout(layout)
    return PublishedFacilityScenario(layout=layout, base_state=state, bundle=_project_bundle(spec, layout, state))
