"""Deterministic M4 public facilities and their Layout 2.0 projections."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise
from math import hypot
from typing import Literal

from parking_opt.api.facility import (
    FacilityDataUnavailableError,
    FacilityNotFoundError,
    FacilityVersionConflictError,
)
from parking_opt.api.models import (
    BufferSpace,
    ChannelZone,
    Coordinate,
    CostSnapshot,
    DataMode,
    DataSourceStatus,
    DriverDemoProfile,
    FacilityBounds,
    FacilityBuffer,
    FacilityBufferState,
    FacilityClaimStatus,
    FacilityEdge,
    FacilityEntrance,
    FacilityExit,
    FacilityFloor,
    FacilityNode,
    FacilityObservationSource,
    FacilityProvenance,
    FacilityRectangle,
    FacilitySourceKind,
    FacilitySourceStatus,
    FacilitySpace,
    FacilitySpaceState,
    FacilityTandemGroup,
    FacilityZone,
    HealthStatus,
    Layout,
    ParkingFacilityLayout,
    ParkingFacilityStateSnapshot,
    ParkingLot,
    ParkingSpace,
    PricingSummary,
    RoadEdge,
    RoadNode,
    RoutePreview,
    RoutePreviewRequest,
    ScenarioBundle,
    SpaceStatus,
    TandemGroup,
    VenueType,
)
from parking_opt.api.routing import RouteCostService, RouteNotFoundError
from parking_opt.api.sessions import InMemorySessionStore, JourneyState, SessionNamespace
from parking_opt.api.sources import ParkingLotNotFoundError, ScenarioProfile

PUBLISHED_AT = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class FacilityScenarioSpec:
    scenario_id: str
    lot_id: str
    name: str
    region: str
    venue_type: VenueType
    spaces: int
    charging: int
    tandem_groups: int
    buffers: int
    occupied: int
    entrances: int
    exits: int
    ring_directed: bool
    seed: int
    pricing: PricingSummary


@dataclass(frozen=True, slots=True)
class PublishedFacilityScenario:
    layout: ParkingFacilityLayout
    base_state: ParkingFacilityStateSnapshot
    bundle: ScenarioBundle


@dataclass(frozen=True, slots=True)
class DriverDemoProfileSpec:
    profile_id: str
    label: str
    description: str


@dataclass(frozen=True, slots=True)
class PublishedDriverDemoScenario:
    demo_profile: DriverDemoProfile
    layout: ParkingFacilityLayout
    base_state: ParkingFacilityStateSnapshot
    bundle: ScenarioBundle


DRIVER_DEMO_PROFILE_SPECS = (
    DriverDemoProfileSpec(
        "normal-flow",
        "平峰通行",
        "空位分布较均衡。优先展示近端普通车位和合规备选。",
    ),
    DriverDemoProfileSpec(
        "peak-remote",
        "高峰远端",
        "近端车位接近饱和。系统需要跨区寻找较远的可行车位。",
    ),
    DriverDemoProfileSpec(
        "charging-tight",
        "充电紧张",
        "充电位暂时占满。充电需求会如实进入等待而不降级。",
    ),
    DriverDemoProfileSpec(
        "tandem-focus",
        "纵深协同",
        "普通独立位已满。外侧位已为后续车辆预留。系统会真实选择可恢复的内侧协同位。",
    ),
)


PUBLIC_SPECS = (
    FacilityScenarioSpec(
        "commercial-full-v1",
        "lot-commercial",
        "中心商业广场停车场",
        "商业中心",
        "commercial",
        48,
        8,
        1,
        1,
        31,
        2,
        2,
        True,
        4101,
        PricingSummary(
            first_hour_yuan=6, additional_hour_yuan=4, daily_cap_yuan=40, note="模拟商业停车计费"
        ),
    ),
    FacilityScenarioSpec(
        "school-full-v1",
        "lot-school",
        "大学创新园停车场",
        "学校",
        "school",
        28,
        4,
        4,
        2,
        14,
        1,
        1,
        False,
        4201,
        PricingSummary(
            first_hour_yuan=2, additional_hour_yuan=3, daily_cap_yuan=30, note="模拟校内首小时优惠"
        ),
    ),
    FacilityScenarioSpec(
        "hospital-full-v1",
        "lot-hospital",
        "市立医院停车场",
        "医院",
        "hospital",
        32,
        6,
        1,
        1,
        22,
        2,
        2,
        False,
        4301,
        PricingSummary(
            first_hour_yuan=5,
            additional_hour_yuan=3,
            daily_cap_yuan=30,
            note="模拟就诊高峰动态通行成本",
        ),
    ),
    FacilityScenarioSpec(
        "transport-hub-full-v1",
        "lot-transport-hub",
        "综合交通枢纽停车场",
        "交通枢纽",
        "transport_hub",
        52,
        10,
        1,
        1,
        31,
        2,
        2,
        True,
        4401,
        PricingSummary(
            first_hour_yuan=3,
            additional_hour_yuan=2,
            daily_cap_yuan=20,
            note="模拟交通枢纽停车计费",
        ),
    ),
)


def _edge(
    edge_id: str, left: FacilityNode, right: FacilityNode, *, directed: bool, channel: str
) -> FacilityEdge:
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
    return FacilityNode(
        node_id=node_id,
        floor_id="floor-1",
        coordinate=Coordinate(x_m=x_m, y_m=y_m),
        kind=kind,
        label=label,
    )


def _zone(
    zone_id: str,
    label: str,
    kind: Literal["parking", "charging", "tandem", "buffer", "restricted", "service", "pedestrian"],
    polygon: tuple[Coordinate, ...],
) -> FacilityZone:
    return FacilityZone(
        zone_id=zone_id,
        floor_id="floor-1",
        label=label,
        kind=kind,
        polygon=polygon,
    )


def _project_node(item: FacilityNode) -> RoadNode:
    if item.kind == "inter_floor":
        raise ValueError("Layout 2.0 compatibility projection does not support inter-floor nodes")
    return RoadNode(
        node_id=item.node_id,
        coordinate=item.coordinate,
        kind=item.kind,
        label=item.label,
    )


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
        _edge(
            "entry-west", by_id["entrance-west"], ring[0], directed=True, channel="channel-entry"
        ),
        _edge("exit-west", ring[3], by_id["exit-west"], directed=True, channel="channel-exit"),
    ]
    if spec.entrances == 2:
        edges.append(
            _edge(
                "entry-east",
                by_id["entrance-east"],
                ring[2],
                directed=True,
                channel="channel-entry",
            )
        )
    if spec.exits == 2:
        edges.append(
            _edge("exit-east", ring[1], by_id["exit-east"], directed=True, channel="channel-exit")
        )
    access_by_id = {item.node_id: item for item in access_nodes}
    for lane, values, west_gate, east_gate, west_anchor, east_anchor in (
        ("north", north_xs, lane_gateways[0], lane_gateways[1], ring[0], ring[1]),
        ("south", south_xs, lane_gateways[2], lane_gateways[3], ring[3], ring[2]),
    ):
        lane_nodes = tuple(access_by_id[access_id(lane, x_m)] for x_m in values)
        path = (west_anchor, west_gate, *lane_nodes, east_gate, east_anchor)
        edges.extend(
            _edge(
                f"lane-{lane}-{index + 1}",
                left,
                right,
                directed=True,
                channel="channel-rows",
            )
            for index, (left, right) in enumerate(pairwise(path))
        )
    for index, node in enumerate(buffer_nodes):
        edges.append(
            _edge(
                f"buffer-{index + 1}",
                ring[2],
                node,
                directed=False,
                channel="channel-buffer",
            )
        )

    charging_ids = {f"P-{index:02d}" for index in range(1, spec.charging + 1)}
    spaces: list[FacilitySpace] = []
    for index in range(1, independent_count + 1):
        row, column = (index - 1) % 4, (index - 1) // 4
        space_id = f"P-{index:02d}"
        spaces.append(
            FacilitySpace(
                parking_lot_id=spec.lot_id,
                space_id=space_id,
                floor_id="floor-1",
                zone_id="zone-charging" if space_id in charging_ids else "zone-parking",
                geometry=FacilityRectangle(
                    center=Coordinate(x_m=independent_xs[column], y_m=(24, 36, 44, 56)[row]),
                    width_m=2.6,
                    length_m=5.2,
                    heading_deg=90,
                ),
                access_node_id=access_id("north" if row < 2 else "south", independent_xs[column]),
                charging=space_id in charging_ids,
            )
        )
    tandem_groups: list[FacilityTandemGroup] = []
    for group_index in range(spec.tandem_groups):
        group_id, pair_ids = f"stack-{group_index + 1}", []
        for depth in (1, 2):
            sequence = independent_count + group_index * 2 + depth
            space_id = f"P-{sequence:02d}"
            pair_ids.append(space_id)
            spaces.append(
                FacilitySpace(
                    parking_lot_id=spec.lot_id,
                    space_id=space_id,
                    floor_id="floor-1",
                    zone_id="zone-tandem",
                    geometry=FacilityRectangle(
                        center=Coordinate(x_m=tandem_xs[group_index], y_m=30 + depth * 5.5),
                        width_m=2.6,
                        length_m=5.2,
                        heading_deg=0,
                    ),
                    access_node_id=access_id("north", tandem_xs[group_index]),
                    stack_group_id=group_id,
                    depth=depth,
                )
            )
        tandem_groups.append(
            FacilityTandemGroup(
                stack_group_id=group_id,
                space_ids_near_to_deep=tuple(pair_ids),
                buffer_ids=(f"BUF-{group_index % spec.buffers + 1:02d}",),
            )
        )
    buffers = tuple(
        FacilityBuffer(
            parking_lot_id=spec.lot_id,
            buffer_id=f"BUF-{index + 1:02d}",
            floor_id="floor-1",
            zone_id="zone-buffer",
            geometry=FacilityRectangle(
                center=Coordinate(x_m=96 + index * 10, y_m=74),
                width_m=3,
                length_m=6,
                heading_deg=90,
            ),
            access_node_id=buffer_nodes[index].node_id,
            stack_group_ids=tuple(
                f"stack-{group + 1}"
                for group in range(spec.tandem_groups)
                if group % spec.buffers == index
            ),
        )
        for index in range(spec.buffers)
    )

    def rectangle_zone(min_x: float, min_y: float, max_x: float, max_y: float):  # type: ignore[no-untyped-def]
        return (
            Coordinate(x_m=min_x, y_m=min_y),
            Coordinate(x_m=max_x, y_m=min_y),
            Coordinate(x_m=max_x, y_m=max_y),
            Coordinate(x_m=min_x, y_m=max_y),
        )

    zones = (
        _zone(
            "zone-parking",
            "普通停车区",
            "parking",
            rectangle_zone(18, 20, max(independent_xs) + 4, 60),
        ),
        _zone("zone-charging", "充电停车区", "charging", rectangle_zone(18, 20, 40, 60)),
        _zone(
            "zone-tandem",
            "纵深停车区",
            "tandem",
            rectangle_zone(min(tandem_xs) - 4, 31, max(tandem_xs) + 4, 45),
        ),
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
            for item in (
                "channel-ring",
                "channel-entry",
                "channel-exit",
                "channel-rows",
                "channel-buffer",
            )
        ),
        entrances=tuple(
            FacilityEntrance(
                entrance_id=f"entrance-{i + 1}",
                node_id=node.node_id,
                label=node.label,
                initial_heading_deg=0,
            )
            for i, node in enumerate(entrances)
        ),
        exits=tuple(
            FacilityExit(exit_id=f"exit-{i + 1}", node_id=node.node_id, label=node.label)
            for i, node in enumerate(exits)
        ),
        default_entrance_id="entrance-1",
        spaces=tuple(spaces),
        tandem_groups=tuple(tandem_groups),
        buffers=buffers,
    )
    occupied_candidates = tuple(
        item for item in spaces if not item.charging and item.stack_group_id is None
    )
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
            FacilitySpaceState(
                space_id=item.space_id,
                observed_status=SpaceStatus.OCCUPIED
                if item.space_id in occupied_ids
                else SpaceStatus.AVAILABLE,
                observation_source=FacilityObservationSource.SYNTHETIC_TRUTH,
                effective_status=SpaceStatus.OCCUPIED
                if item.space_id in occupied_ids
                else SpaceStatus.AVAILABLE,
                assignable=item.space_id not in occupied_ids,
                reason_codes=("SPACE_OCCUPIED",) if item.space_id in occupied_ids else (),
            )
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
    return PublishedFacilityScenario(
        layout=layout, base_state=state, bundle=_project_bundle(spec, layout, state)
    )


def _project_bundle(
    spec: FacilityScenarioSpec, layout: ParkingFacilityLayout, state: ParkingFacilityStateSnapshot
) -> ScenarioBundle:
    states = {item.space_id: item for item in state.spaces}
    road_layout = Layout(
        parking_lot_id=layout.parking_lot_id,
        layout_version=layout.layout_version,
        coordinate_origin_note=layout.coordinate_origin_note,
        entrance_node_ids=tuple(item.node_id for item in layout.entrances),
        exit_node_ids=tuple(item.node_id for item in layout.exits),
        nodes=tuple(_project_node(item) for item in layout.nodes),
        edges=tuple(
            RoadEdge(
                edge_id=item.edge_id,
                from_node_id=item.from_node_id,
                to_node_id=item.to_node_id,
                distance_m=item.distance_m,
                base_travel_time_s=item.base_travel_time_s,
                directed=item.directed,
                channel_zone_ids=item.channel_zone_ids,
            )
            for item in layout.edges
        ),
        channel_zones=layout.channel_zones,
        spaces=tuple(
            ParkingSpace(
                parking_lot_id=item.parking_lot_id,
                space_id=item.space_id,
                coordinate=item.geometry.center,
                access_node_id=item.access_node_id,
                status=states[item.space_id].effective_status,
                charging=item.charging,
                stack_group_id=item.stack_group_id or f"single-{item.space_id}",
                depth=item.depth,
                assignable=states[item.space_id].assignable,
                assignability_reasons=states[item.space_id].reason_codes,
            )
            for item in layout.spaces
        ),
        tandem_groups=tuple(
            TandemGroup(
                stack_group_id=item.stack_group_id,
                space_ids_near_to_deep=item.space_ids_near_to_deep,
            )
            for item in layout.tandem_groups
        ),
        buffers=tuple(
            BufferSpace(
                parking_lot_id=item.parking_lot_id,
                buffer_id=item.buffer_id,
                coordinate=item.geometry.center,
                access_node_id=item.access_node_id,
                available=True,
                channel_zone_ids=("channel-buffer",),
            )
            for item in layout.buffers
        ),
    )
    source = DataSourceStatus(
        parking_lot_id=spec.lot_id,
        mode=DataMode.SYNTHETIC,
        health=HealthStatus.HEALTHY,
        source_name=f"web-v2 public facility: {spec.scenario_id}",
        updated_at=PUBLISHED_AT,
    )
    lot = ParkingLot(
        parking_lot_id=spec.lot_id,
        name=spec.name,
        region_label=spec.region,
        venue_type=spec.venue_type,
        synthetic=True,
        opening_status="open",
        total_spaces=spec.spaces,
        available_spaces=sum(
            item.effective_status is SpaceStatus.AVAILABLE for item in state.spaces
        ),
        charging_spaces=spec.charging,
        pricing=spec.pricing,
        updated_at=PUBLISHED_AT,
        data_source=source,
    )
    costs = CostSnapshot(
        parking_lot_id=spec.lot_id,
        layout_version=layout.layout_version,
        cost_version="cost-base-1",
        observed_at=PUBLISHED_AT,
        edge_travel_time_s={item.edge_id: item.base_travel_time_s for item in road_layout.edges},
    )
    return ScenarioBundle(
        scenario_id=spec.scenario_id,
        seed=spec.seed,
        parking_lot=lot,
        layout=road_layout,
        cost_snapshot=costs,
    )


def build_public_facility_scenarios() -> dict[str, PublishedFacilityScenario]:
    return {item.lot_id: _build_scenario(item) for item in PUBLIC_SPECS}


def _profile_occupied_ids(
    profile_id: str, scenario: PublishedFacilityScenario
) -> frozenset[str]:
    spaces = scenario.layout.spaces
    if profile_id == "normal-flow":
        return frozenset(
            item.space_id
            for item in scenario.base_state.spaces
            if item.observed_status is SpaceStatus.OCCUPIED
        )
    if profile_id == "peak-remote":
        far_independent = sorted(
            (item for item in spaces if item.stack_group_id is None and not item.charging),
            key=lambda item: (item.geometry.center.x_m, item.space_id),
            reverse=True,
        )[:3]
        far_charging = sorted(
            (item for item in spaces if item.charging),
            key=lambda item: (item.geometry.center.x_m, item.space_id),
            reverse=True,
        )[:1]
        available_ids = {item.space_id for item in (*far_independent, *far_charging)}
        return frozenset(item.space_id for item in spaces if item.space_id not in available_ids)
    if profile_id == "charging-tight":
        base_occupied = {
            item.space_id
            for item in scenario.base_state.spaces
            if item.observed_status is SpaceStatus.OCCUPIED
        }
        return frozenset(
            base_occupied | {item.space_id for item in spaces if item.charging}
        )
    if profile_id == "tandem-focus":
        return frozenset(item.space_id for item in spaces if item.stack_group_id is None)
    raise ValueError(f"unsupported driver demo profile: {profile_id}")


def _profile_space_state(
    item: FacilitySpaceState,
    *,
    occupied_ids: frozenset[str],
    reserved_outer_ids: frozenset[str],
) -> FacilitySpaceState:
    if item.space_id in reserved_outer_ids:
        return item.model_copy(
            update={
                "observed_status": SpaceStatus.UNAVAILABLE,
                "effective_status": SpaceStatus.UNAVAILABLE,
                "assignable": False,
                "reason_codes": ("DEMO_TANDEM_OUTER_RESERVED",),
            }
        )
    occupied = item.space_id in occupied_ids
    return item.model_copy(
        update={
            "observed_status": (
                SpaceStatus.OCCUPIED if occupied else SpaceStatus.AVAILABLE
            ),
            "effective_status": (
                SpaceStatus.OCCUPIED if occupied else SpaceStatus.AVAILABLE
            ),
            "assignable": not occupied,
            "reason_codes": ("SPACE_OCCUPIED",) if occupied else (),
        }
    )


def _build_driver_demo_scenarios(
    scenario: PublishedFacilityScenario,
) -> tuple[PublishedDriverDemoScenario, ...]:
    result = []
    total = len(DRIVER_DEMO_PROFILE_SPECS)
    for index, profile_spec in enumerate(DRIVER_DEMO_PROFILE_SPECS):
        profile = DriverDemoProfile(
            profile_id=profile_spec.profile_id,
            label=profile_spec.label,
            description=profile_spec.description,
            ordinal=index + 1,
            total=total,
        )
        occupied_ids = _profile_occupied_ids(profile.profile_id, scenario)
        reserved_outer_ids = (
            frozenset(
                group.space_ids_near_to_deep[0]
                for group in scenario.layout.tandem_groups
            )
            if profile.profile_id == "tandem-focus"
            else frozenset()
        )

        state = scenario.base_state.model_copy(
            update={
                "state_version": f"state-{profile.profile_id}-base-1",
                "demo_profile": profile,
                "spaces": tuple(
                    _profile_space_state(
                        item,
                        occupied_ids=occupied_ids,
                        reserved_outer_ids=reserved_outer_ids,
                    )
                    for item in scenario.base_state.spaces
                ),
            }
        ).require_layout(scenario.layout)
        bundle = _project_bundle(
            next(item for item in PUBLIC_SPECS if item.lot_id == scenario.layout.parking_lot_id),
            scenario.layout,
            state,
        )
        bundle = bundle.model_copy(
            update={
                "seed": bundle.seed + index,
                "cost_snapshot": bundle.cost_snapshot.model_copy(
                    update={"cost_version": f"cost-{profile.profile_id}-1"}
                ),
            }
        )
        result.append(
            PublishedDriverDemoScenario(
                demo_profile=profile,
                layout=scenario.layout,
                base_state=state,
                bundle=bundle,
            )
        )
    return tuple(result)


class PublicFacilityDataSource:
    """Public data source shared by compatibility and facility endpoints."""

    def __init__(
        self,
        *,
        session_store: InMemorySessionStore,
        route_service: RouteCostService,
        profiles_enabled: bool = True,
    ) -> None:
        self._by_lot = build_public_facility_scenarios()
        self._driver_profiles = {
            lot_id: _build_driver_demo_scenarios(scenario)
            for lot_id, scenario in self._by_lot.items()
        }
        self._session_store = session_store
        self._route_service = route_service
        for scenario in self._by_lot.values():
            route_service.register_entrance_headings(
                scenario.layout.parking_lot_id,
                scenario.layout.layout_version,
                {item.node_id: item.initial_heading_deg for item in scenario.layout.entrances},
            )
        self._profiles_enabled = profiles_enabled
        self._profile = ScenarioProfile.PUBLIC

    @property
    def profile(self) -> ScenarioProfile:
        return self._profile

    @property
    def driver_demo_profiles_enabled(self) -> bool:
        return self._profiles_enabled

    def list_bundles(self) -> tuple[ScenarioBundle, ...]:
        return tuple(self._by_lot[key].bundle for key in sorted(self._by_lot))

    def get_bundle(self, parking_lot_id: str) -> ScenarioBundle:
        try:
            return self._by_lot[parking_lot_id].bundle
        except KeyError as exc:
            raise ParkingLotNotFoundError(f"unknown parking lot: {parking_lot_id}") from exc

    def list_driver_bundles(self, *, session_id: str) -> tuple[ScenarioBundle, ...]:
        return tuple(
            self.get_driver_bundle(parking_lot_id, session_id=session_id)
            for parking_lot_id in sorted(self._by_lot)
        )

    def get_driver_bundle(self, parking_lot_id: str, *, session_id: str) -> ScenarioBundle:
        return self._driver_scenario(parking_lot_id, session_id=session_id).bundle

    def get_driver_demo_profile(
        self, parking_lot_id: str, *, session_id: str
    ) -> DriverDemoProfile:
        return self._driver_scenario(
            parking_lot_id, session_id=session_id
        ).demo_profile

    def driver_demo_profile_count(self, parking_lot_id: str) -> int:
        try:
            return len(self._driver_profiles[parking_lot_id]) if self._profiles_enabled else 1
        except KeyError as exc:
            raise ParkingLotNotFoundError(f"unknown parking lot: {parking_lot_id}") from exc

    def driver_demo_profile_index(
        self, parking_lot_id: str, *, profile_id: str
    ) -> int:
        try:
            profiles = self._driver_profiles[parking_lot_id]
        except KeyError as exc:
            raise ParkingLotNotFoundError(f"unknown parking lot: {parking_lot_id}") from exc
        for index, profile in enumerate(profiles):
            if profile.demo_profile.profile_id == profile_id:
                return index
        raise FacilityVersionConflictError(f"unknown driver demo profile: {profile_id}")

    def get_layout(self, parking_lot_id: str) -> ParkingFacilityLayout:
        return self._scenario(parking_lot_id).layout

    def get_state(self, parking_lot_id: str, *, session_id: str) -> ParkingFacilityStateSnapshot:
        scenario = self._driver_scenario(parking_lot_id, session_id=session_id)
        with self._session_store.atomic():
            availability = self._session_store.availability_snapshot(
                session_id=session_id,
                namespace=SessionNamespace.DRIVER,
                scopes=((scenario.base_state.scenario_id, parking_lot_id),),
            )
            active_claims = self._session_store.active_claims()
            coordination_records = self._session_store.tandem_coordination_records(
                session_id=session_id,
                scenario_id=scenario.base_state.scenario_id,
                parking_lot_id=parking_lot_id,
            )
            claimed_journeys = []
            for claim in active_claims:
                if (
                    claim.session_id == session_id
                    and claim.namespace is SessionNamespace.DRIVER
                    and claim.scenario_id == scenario.base_state.scenario_id
                    and claim.parking_lot_id == parking_lot_id
                ):
                    journey = self._session_store.get_journey(claim.journey_id)
                    if journey is None:
                        raise FacilityDataUnavailableError("active claim has no journey")
                    claimed_journeys.append((claim, journey))
        scope = availability.scopes[0]
        unavailable = dict(scope.unavailable_space_reasons)
        coordination_by_space = {
            space_id: record
            for record in coordination_records
            for space_id in record.blocker_space_ids
        }
        journeys = {}
        for claim, journey in claimed_journeys:
            journeys[claim.space_id] = journey
        claim_map = {
            JourneyState.SOFT_HELD: FacilityClaimStatus.SOFT_HELD,
            JourneyState.SESSION_RESERVED: FacilityClaimStatus.SESSION_RESERVED,
            JourneyState.NAVIGATING: FacilityClaimStatus.NAVIGATING,
        }
        projected = []
        for item in scenario.base_state.spaces:
            if item.space_id in scope.claimed_space_ids:
                claimed_journey = journeys.get(item.space_id)
                journey_state = None if claimed_journey is None else claimed_journey.state
                if journey_state is JourneyState.OCCUPIED:
                    projected.append(
                        item.model_copy(
                            update={
                                "observed_status": SpaceStatus.OCCUPIED,
                                "observation_source": FacilityObservationSource.SYNTHETIC_TRUTH,
                                "claim_status": FacilityClaimStatus.NONE,
                                "effective_status": SpaceStatus.OCCUPIED,
                                "assignable": False,
                                "reason_codes": ("SPACE_OCCUPIED",),
                            }
                        )
                    )
                    continue
                claim_status = (
                    claim_map[journey_state]
                    if journey_state in claim_map
                    else FacilityClaimStatus.SOFT_HELD
                )
                projected.append(
                    item.model_copy(
                        update={
                            "claim_status": claim_status,
                            "effective_status": SpaceStatus.UNAVAILABLE,
                            "assignable": False,
                            "reason_codes": ("SESSION_CLAIMED",),
                        }
                    )
                )
            elif item.space_id in coordination_by_space:
                projected.append(
                    item.model_copy(
                        update={
                            "observed_status": SpaceStatus.OCCUPIED,
                            "observation_source": FacilityObservationSource.SYNTHETIC_TRUTH,
                            "claim_status": FacilityClaimStatus.NONE,
                            "effective_status": SpaceStatus.OCCUPIED,
                            "assignable": False,
                            "reason_codes": ("TANDEM_COORDINATION_BLOCKER",),
                        }
                    )
                )
            elif item.space_id in unavailable:
                projected.append(
                    item.model_copy(
                        update={
                            "observed_status": SpaceStatus.UNAVAILABLE,
                            "observation_source": FacilityObservationSource.USER_OVERRIDE,
                            "effective_status": SpaceStatus.UNAVAILABLE,
                            "assignable": False,
                            "reason_codes": (unavailable[item.space_id],),
                        }
                    )
                )
            else:
                projected.append(item)
        journey_identity = tuple(
            sorted(
                (
                    space_id,
                    journey.state.value,
                    journey.updated_at.isoformat(),
                )
                for space_id, journey in journeys.items()
                if space_id in scope.claimed_space_ids
            )
        )
        token = hashlib.sha256(
            repr(
                (
                    scenario.demo_profile.profile_id,
                    journey_identity,
                    tuple(
                        (
                            item.journey_id,
                            item.stack_group_id,
                            item.blocker_space_ids,
                            item.buffer_ids,
                            item.created_at.isoformat(),
                        )
                        for item in coordination_records
                    ),
                    sorted(unavailable.items()),
                )
            ).encode("ascii")
        ).hexdigest()[:12]
        observed_at = max(
            (
                *(journey.updated_at for journey in journeys.values()),
                *(item.created_at for item in coordination_records),
            ),
            default=scenario.base_state.observed_at,
        )
        return scenario.base_state.model_copy(
            update={
                "state_version": f"state-{token}",
                "observed_at": observed_at,
                "spaces": tuple(projected),
            }
        )

    def preview_route(
        self, parking_lot_id: str, *, session_id: str, request: RoutePreviewRequest
    ) -> RoutePreview:
        scenario = self._driver_scenario(parking_lot_id, session_id=session_id)
        state = self.get_state(parking_lot_id, session_id=session_id)
        if (
            request.layout_version != scenario.layout.layout_version
            or request.scenario_version != state.scenario_version
            or request.state_version != state.state_version
        ):
            raise FacilityVersionConflictError("route preview state is stale")
        entrance = next(
            (item for item in scenario.layout.entrances if item.entrance_id == request.entrance_id),
            None,
        )
        target = next(
            (item for item in scenario.layout.spaces if item.space_id == request.target_space_id),
            None,
        )
        if entrance is None or target is None:
            raise FacilityDataUnavailableError("route preview endpoint is unknown")
        try:
            route = self._route_service.route(
                scenario.bundle.layout,
                scenario.bundle.cost_snapshot,
                from_node_id=entrance.node_id,
                to_node_id=target.access_node_id,
            )
        except RouteNotFoundError as exc:
            raise FacilityDataUnavailableError(str(exc)) from exc
        return RoutePreview(
            parking_lot_id=parking_lot_id,
            layout_version=scenario.layout.layout_version,
            scenario_version=state.scenario_version,
            state_version=state.state_version,
            observed_at=state.observed_at,
            entrance_id=request.entrance_id,
            target_space_id=request.target_space_id,
            route=route,
        )

    def _scenario(self, parking_lot_id: str) -> PublishedFacilityScenario:
        try:
            return self._by_lot[parking_lot_id]
        except KeyError as exc:
            raise FacilityNotFoundError(f"unknown parking lot: {parking_lot_id}") from exc

    def _driver_scenario(
        self, parking_lot_id: str, *, session_id: str
    ) -> PublishedDriverDemoScenario:
        try:
            profiles = self._driver_profiles[parking_lot_id]
        except KeyError as exc:
            raise FacilityNotFoundError(f"unknown parking lot: {parking_lot_id}") from exc
        if not self._profiles_enabled:
            return profiles[0]
        index = self._session_store.driver_demo_profile_index(
            session_id=session_id,
            parking_lot_id=parking_lot_id,
            profile_count=len(profiles),
        )
        return profiles[index]
