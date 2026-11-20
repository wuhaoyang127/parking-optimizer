"""研究端 nodes/edges 布局 → 车主端 v2 ScenarioBundle 转换器（布局推送用）。

把研究端自定义布局（nodes: entry/exit/road/spot，edges: from/to/distance）
转换成车主端推荐引擎需要的 ScenarioBundle（ParkingLot + Layout + CostSnapshot）。
坐标原样保留，供后续 2D/3D 渲染复用。
"""
from __future__ import annotations
import hashlib
import logging
from datetime import UTC, datetime

from parking_opt.api.models import (
    DataMode,
    DataSourceStatus,
    HealthStatus,
    ParkingLot,
    PricingSummary,
    SpaceStatus,
)
from parking_opt.api.models_discovery import (
    ChannelZone,
    Coordinate,
    DiscoveryArea,
    DiscoveryLotSummary,
    DiscoveryPosition,
    OffsiteEstimate,
    ParkingSpace,
    RoadEdge,
    RoadNode,
    TandemGroup,
)
from parking_opt.api.models_layout import Layout
from parking_opt.api.models_simulation import ScenarioBundle
from parking_opt.api.models_state import CostSnapshot

_WALK_SPEED_M_S = 1.4
_CHANNEL_ZONE_ID = "zone-default"
LOGGER = logging.getLogger(__name__)


def _coords(nodes: list[dict]) -> dict[str, tuple[float, float]]:
    return {nd["id"]: (float(nd["x"]), float(nd["y"])) for nd in nodes}


def build_scenario_bundle(lot_id: str, name: str, venue_type: str, data: dict) -> ScenarioBundle:
    """把 nodes/edges 布局转成 ScenarioBundle。venue_type 取 school/hospital/commercial/transport_hub。"""
    nodes = data["nodes"]
    edges = data["edges"]
    coord = _coords(nodes)

    road_nodes: list[RoadNode] = []
    spaces: list[ParkingSpace] = []
    entrance_ids: list[str] = []
    exit_ids: list[str] = []

    for nd in nodes:
        nid = str(nd["id"])
        pos = Coordinate(x_m=coord[nid][0], y_m=coord[nid][1])
        kind = nd["type"]
        if kind == "entry":
            road_nodes.append(RoadNode(node_id=nid, coordinate=pos, kind="entrance", label=nid))
            entrance_ids.append(nid)
        elif kind == "exit":
            road_nodes.append(RoadNode(node_id=nid, coordinate=pos, kind="exit", label=nid))
            exit_ids.append(nid)
        elif kind == "road":
            road_nodes.append(RoadNode(node_id=nid, coordinate=pos, kind="junction", label=nid))
        elif kind == "spot":
            road_nodes.append(RoadNode(node_id=nid, coordinate=pos, kind="space_access", label=nid))
            group = str(nd.get("group", nid))
            depth = int(nd.get("depth", 1))
            spaces.append(ParkingSpace(
                parking_lot_id=lot_id, space_id=nid, coordinate=pos, access_node_id=nid,
                status=SpaceStatus.AVAILABLE, charging=False, stack_group_id=group,
                depth=depth, assignable=True,
            ))

    # 无出口时合成一个（与入口同点，并连一条边），保证 exit_node_ids 非空
    if not exit_ids:
        if not entrance_ids:
            raise ValueError("布局缺少入口节点（entry）")
        synthetic_exit = "exit-auto"
        ex, ey = coord[entrance_ids[0]]
        road_nodes.append(RoadNode(node_id=synthetic_exit, coordinate=Coordinate(x_m=ex, y_m=ey),
                                   kind="exit", label=synthetic_exit))
        exit_ids = [synthetic_exit]
        edges = list(edges) + [
            {"from": entrance_ids[0], "to": synthetic_exit, "distance": 0.5},
            {"from": synthetic_exit, "to": entrance_ids[0], "distance": 0.5},
        ]

    zone = ChannelZone(channel_zone_id=_CHANNEL_ZONE_ID, capacity=max(64, len(nodes)))
    road_edges: list[RoadEdge] = []
    for i, ed in enumerate(edges):
        dist = max(float(ed["distance"]), 0.01)
        road_edges.append(RoadEdge(
            edge_id=f"edge-{i}", from_node_id=str(ed["from"]), to_node_id=str(ed["to"]),
            distance_m=dist, base_travel_time_s=max(dist / _WALK_SPEED_M_S, 0.1),
            directed=False, channel_zone_ids=(_CHANNEL_ZONE_ID,),
        ))

    groups: dict[str, list[ParkingSpace]] = {}
    for s in spaces:
        groups.setdefault(s.stack_group_id, []).append(s)
    tandem_groups = [
        TandemGroup(
            stack_group_id=gid,
            space_ids_near_to_deep=tuple(m.space_id for m in sorted(members, key=lambda x: x.depth)),
        )
        for gid, members in groups.items()
        if len(members) > 1
    ]

    layout = Layout(
        parking_lot_id=lot_id,
        layout_version=f"{lot_id}-layout-1",
        coordinate_origin_note="研究端推送布局",
        entrance_node_ids=tuple(entrance_ids),
        exit_node_ids=tuple(exit_ids),
        nodes=tuple(road_nodes),
        edges=tuple(road_edges),
        channel_zones=(zone,),
        spaces=tuple(spaces),
        tandem_groups=tuple(tandem_groups),
        buffers=(),
    )

    now = datetime.now(UTC)
    total = len(spaces)
    available = sum(1 for s in spaces if s.status is SpaceStatus.AVAILABLE)
    charging = sum(1 for s in spaces if s.charging)
    lot = ParkingLot(
        parking_lot_id=lot_id, name=name, region_label=name, venue_type=venue_type,
        synthetic=True, opening_status="open", total_spaces=total,
        available_spaces=available, charging_spaces=charging,
        pricing=PricingSummary(first_hour_yuan=6.0, additional_hour_yuan=4.0,
                               daily_cap_yuan=40.0, note="自定义布局"),
        updated_at=now,
        data_source=DataSourceStatus(
            parking_lot_id=lot_id, mode=DataMode.SYNTHETIC, health=HealthStatus.HEALTHY,
            source_name="research pushed layout", updated_at=now,
        ),
    )
    cost = CostSnapshot(
        parking_lot_id=lot_id, layout_version=layout.layout_version,
        cost_version=f"{lot_id}-cost-1", observed_at=now,
        edge_travel_time_s={e.edge_id: e.base_travel_time_s for e in road_edges},
    )
    return ScenarioBundle(
        scenario_id=f"{lot_id}-scenario-1", seed=0,
        parking_lot=lot, layout=layout, cost_snapshot=cost,
    )


def load_pushed_scenarios() -> dict[str, ScenarioBundle]:
    """从 Supabase 读取推送布局并转换成 {lot_id: ScenarioBundle}；失败/无效项跳过。"""
    try:
        from parking_opt.api.research_supabase import pull_layouts
        items = pull_layouts()
    except Exception:
        return {}
    result: dict[str, ScenarioBundle] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        lot_id = str(it.get("id", "")).strip()
        name = str(it.get("name", lot_id)).strip()
        venue = str(it.get("venue_type", "commercial"))
        data = it.get("data")
        if not lot_id or not name or not isinstance(data, dict):
            continue
        try:
            result[lot_id] = build_scenario_bundle(lot_id, name, venue, data)
        except Exception as exc:
            LOGGER.warning("跳过无效推送布局 %s: %s", lot_id, exc)
            continue
    return result


def _offsite_estimates_for(lot_id: str, refs: tuple[str, ...]) -> tuple[OffsiteEstimate, ...]:
    """为推送布局生成稳定伪随机的离场估价（接入地图前用，后续换真实值）。

    距离按 300~1500 米取伪随机；时间 = 距离 / 车速，车速按 3.5~5.5 m/s 取伪随机，
    用「红绿灯 + 路况」带来的速度差异让时间与距离大体匹配但非严格线性。
    """
    estimates = []
    for ref in refs:
        digest = hashlib.sha256(f"{lot_id}:{ref}".encode()).hexdigest()
        distance_m = 300 + int(digest[:6], 16) % 1200
        speed_mps = 3.5 + (int(digest[6:10], 16) % 200) / 100.0
        eta_s = max(45, round(distance_m / speed_mps))
        estimates.append(OffsiteEstimate(reference_id=ref, distance_m=distance_m, eta_s=eta_s))
    return tuple(estimates)


def with_pushed_lots(area: DiscoveryArea, pushed: dict[str, ScenarioBundle]) -> DiscoveryArea:
    """把推送布局追加到发现区（默认位置 + 稳定伪随机估价），保证与 parking-lots 列表同源。"""
    refs = tuple(item.reference_id for item in area.references)
    lots = list(area.lots)
    for i, lot_id in enumerate(sorted(pushed)):
        lots.append(DiscoveryLotSummary(
            parking_lot_id=lot_id,
            opening_hours_label="自定义布局",
            position=DiscoveryPosition(x_pct=48 + (i % 3) * 8, y_pct=48 + (i // 3) * 8),
            offsite_estimates=_offsite_estimates_for(lot_id, refs),
        ))
    return area.model_copy(update={"lots": tuple(lots)})
