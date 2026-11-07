"""Deterministic synthetic parking-lot scenarios for web-v2 development and demos."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from parking_opt.api.models import (
    BufferSpace,
    ChannelZone,
    Coordinate,
    CostSnapshot,
    DataMode,
    DataSourceStatus,
    HealthStatus,
    Layout,
    ParkingLot,
    ParkingSpace,
    PricingSummary,
    RoadEdge,
    RoadNode,
    ScenarioBundle,
    SpaceStatus,
    TandemGroup,
    VenueType,
)

SYNTHETIC_UPDATED_AT = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)
SCENARIO_IDS = (
    "school-demo",
    "hospital-demo",
    "commercial-demo",
    "transport-hub-demo",
)


def _space(
    lot_id: str,
    space_id: str,
    x_m: float,
    y_m: float,
    access_node_id: str,
    *,
    status: SpaceStatus = SpaceStatus.AVAILABLE,
    charging: bool = False,
    stack_group_id: str | None = None,
    depth: int = 1,
) -> ParkingSpace:
    assignable = status is SpaceStatus.AVAILABLE
    return ParkingSpace(
        parking_lot_id=lot_id,
        space_id=space_id,
        coordinate=Coordinate(x_m=x_m, y_m=y_m),
        access_node_id=access_node_id,
        status=status,
        charging=charging,
        stack_group_id=stack_group_id or f"independent-{space_id}",
        depth=depth,
        assignable=assignable,
        assignability_reasons=() if assignable else (f"SPACE_{status.value.upper()}",),
    )


def _bundle(
    *,
    scenario_id: str,
    lot_id: str,
    name: str,
    region: str,
    venue_type: VenueType,
    occupied_ids: frozenset[str],
    charging_ids: frozenset[str],
    edge_times: tuple[float, float, float, float],
    pricing: PricingSummary,
) -> ScenarioBundle:
    nodes = (
        RoadNode(
            node_id="entry", coordinate=Coordinate(x_m=0, y_m=0), kind="entrance", label="入口"
        ),
        RoadNode(
            node_id="junction-a",
            coordinate=Coordinate(x_m=20, y_m=0),
            kind="junction",
            label="A区路口",
        ),
        RoadNode(
            node_id="access-a",
            coordinate=Coordinate(x_m=36, y_m=-8),
            kind="space_access",
            label="A区车位",
        ),
        RoadNode(
            node_id="access-b",
            coordinate=Coordinate(x_m=36, y_m=8),
            kind="space_access",
            label="B区纵深位",
        ),
        RoadNode(
            node_id="buffer-access",
            coordinate=Coordinate(x_m=20, y_m=14),
            kind="buffer_access",
            label="临时移车区",
        ),
        RoadNode(node_id="exit", coordinate=Coordinate(x_m=0, y_m=18), kind="exit", label="出口"),
    )
    edge_specs = (
        ("edge-entry-junction", "entry", "junction-a", 20.0, edge_times[0], ("channel-main",)),
        ("edge-junction-a", "junction-a", "access-a", 18.0, edge_times[1], ("channel-a",)),
        ("edge-junction-b", "junction-a", "access-b", 18.0, edge_times[2], ("channel-b",)),
        (
            "edge-junction-buffer",
            "junction-a",
            "buffer-access",
            14.0,
            edge_times[3],
            ("channel-buffer",),
        ),
        ("edge-buffer-exit", "buffer-access", "exit", 24.0, 24.0, ("channel-main",)),
    )
    edges = tuple(
        RoadEdge(
            edge_id=edge_id,
            from_node_id=from_node,
            to_node_id=to_node,
            distance_m=distance,
            base_travel_time_s=travel_time,
            channel_zone_ids=zones,
        )
        for edge_id, from_node, to_node, distance, travel_time, zones in edge_specs
    )

    def status(space_id: str) -> SpaceStatus:
        return SpaceStatus.OCCUPIED if space_id in occupied_ids else SpaceStatus.AVAILABLE

    spaces = (
        _space(
            lot_id,
            "A-01",
            37,
            -11,
            "access-a",
            status=status("A-01"),
            charging="A-01" in charging_ids,
        ),
        _space(
            lot_id,
            "A-02",
            41,
            -11,
            "access-a",
            status=status("A-02"),
            charging="A-02" in charging_ids,
        ),
        _space(
            lot_id,
            "A-03",
            45,
            -11,
            "access-a",
            status=status("A-03"),
            charging="A-03" in charging_ids,
        ),
        _space(
            lot_id,
            "B-01",
            37,
            11,
            "access-b",
            status=status("B-01"),
            stack_group_id="stack-B1",
            depth=1,
        ),
        _space(
            lot_id,
            "B-02",
            37,
            15,
            "access-b",
            status=status("B-02"),
            stack_group_id="stack-B1",
            depth=2,
        ),
        _space(
            lot_id,
            "B-03",
            45,
            11,
            "access-b",
            status=status("B-03"),
            stack_group_id="stack-B2",
            depth=1,
        ),
        _space(
            lot_id,
            "B-04",
            45,
            15,
            "access-b",
            status=status("B-04"),
            stack_group_id="stack-B2",
            depth=2,
        ),
        _space(
            lot_id,
            "C-01",
            25,
            -11,
            "junction-a",
            status=status("C-01"),
            charging="C-01" in charging_ids,
        ),
    )
    layout = Layout(
        parking_lot_id=lot_id,
        layout_version="layout-2026-08-12",
        coordinate_origin_note="deterministic synthetic coordinates; entrance origin; meters",
        entrance_node_ids=("entry",),
        exit_node_ids=("exit",),
        nodes=nodes,
        edges=edges,
        channel_zones=tuple(
            ChannelZone(channel_zone_id=zone, capacity=1)
            for zone in ("channel-main", "channel-a", "channel-b", "channel-buffer")
        ),
        spaces=spaces,
        tandem_groups=(
            TandemGroup(stack_group_id="stack-B1", space_ids_near_to_deep=("B-01", "B-02")),
            TandemGroup(stack_group_id="stack-B2", space_ids_near_to_deep=("B-03", "B-04")),
        ),
        buffers=(
            BufferSpace(
                parking_lot_id=lot_id,
                buffer_id="BUF-01",
                coordinate=Coordinate(x_m=23, y_m=16),
                access_node_id="buffer-access",
                available=True,
                channel_zone_ids=("channel-buffer",),
            ),
        ),
    )
    available = sum(item.status is SpaceStatus.AVAILABLE for item in spaces)
    source = DataSourceStatus(
        parking_lot_id=lot_id,
        mode=DataMode.SYNTHETIC,
        health=HealthStatus.HEALTHY,
        source_name=f"web-v2 deterministic fixture: {scenario_id}",
        updated_at=SYNTHETIC_UPDATED_AT,
    )
    lot = ParkingLot(
        parking_lot_id=lot_id,
        name=name,
        region_label=region,
        venue_type=venue_type,
        synthetic=True,
        opening_status="open",
        total_spaces=len(spaces),
        available_spaces=available,
        charging_spaces=sum(item.charging for item in spaces),
        pricing=pricing,
        updated_at=SYNTHETIC_UPDATED_AT,
        data_source=source,
    )
    costs = CostSnapshot(
        parking_lot_id=lot_id,
        layout_version=layout.layout_version,
        cost_version="cost-2026-08-12T090000Z",
        observed_at=SYNTHETIC_UPDATED_AT,
        edge_travel_time_s={item.edge_id: item.base_travel_time_s for item in edges},
    )
    return ScenarioBundle(
        scenario_id=scenario_id,
        seed=20260812,
        parking_lot=lot,
        layout=layout,
        cost_snapshot=costs,
    )


def built_in_scenarios() -> dict[str, ScenarioBundle]:
    """Build all four fixed demo lots without random or wall-clock input."""

    bundles = (
        _bundle(
            scenario_id="school-demo",
            lot_id="lot-school",
            name="大学创新园停车场",
            region="学校",
            venue_type="school",
            occupied_ids=frozenset({"A-01", "B-01"}),
            charging_ids=frozenset({"A-01", "C-01"}),
            edge_times=(18, 16, 21, 14),
            pricing=PricingSummary(
                currency="CNY",
                first_hour_yuan=2.0,
                additional_hour_yuan=3.0,
                daily_cap_yuan=30.0,
                note="模拟校内首小时优惠",
            ),
        ),
        _bundle(
            scenario_id="hospital-demo",
            lot_id="lot-hospital",
            name="市立医院停车场",
            region="医院",
            venue_type="hospital",
            occupied_ids=frozenset({"A-01", "A-02", "B-01", "B-03"}),
            charging_ids=frozenset({"A-02", "C-01"}),
            edge_times=(28, 20, 25, 18),
            pricing=PricingSummary(
                currency="CNY",
                first_hour_yuan=5.0,
                additional_hour_yuan=3.0,
                daily_cap_yuan=30.0,
                note="模拟就诊高峰动态通行成本",
            ),
        ),
        _bundle(
            scenario_id="commercial-demo",
            lot_id="lot-commercial",
            name="中心商业广场停车场",
            region="商业中心",
            venue_type="commercial",
            occupied_ids=frozenset({"A-03", "B-02", "C-01"}),
            charging_ids=frozenset({"A-01", "A-02", "C-01"}),
            edge_times=(22, 19, 17, 14),
            pricing=PricingSummary(
                first_hour_yuan=6.0,
                additional_hour_yuan=4.0,
                daily_cap_yuan=40.0,
                note="模拟商业停车计费",
            ),
        ),
        _bundle(
            scenario_id="transport-hub-demo",
            lot_id="lot-transport-hub",
            name="综合交通枢纽停车场",
            region="交通枢纽",
            venue_type="transport_hub",
            occupied_ids=frozenset({"A-02", "B-03", "B-04"}),
            charging_ids=frozenset({"C-01"}),
            edge_times=(16, 15, 19, 13),
            pricing=PricingSummary(
                first_hour_yuan=3.0,
                additional_hour_yuan=2.0,
                daily_cap_yuan=20.0,
                note="模拟交通枢纽停车计费",
            ),
        ),
    )
    return {item.scenario_id: item for item in bundles}


def load_scenarios(directory: Path) -> dict[str, ScenarioBundle]:
    """Load generated fixtures and validate every byte through the v2 models."""

    scenarios: dict[str, ScenarioBundle] = {}
    for path in sorted(directory.glob("*.scenario.json")):
        bundle = ScenarioBundle.model_validate_json(path.read_text(encoding="utf-8"))
        if bundle.scenario_id in scenarios:
            raise ValueError(f"duplicate scenario_id: {bundle.scenario_id}")
        scenarios[bundle.scenario_id] = bundle
    if set(scenarios) != set(SCENARIO_IDS):
        raise ValueError(f"expected scenarios {SCENARIO_IDS}, got {tuple(scenarios)}")
    return scenarios


def export_scenarios(directory: Path) -> None:
    """Write stable, reviewable synthetic JSON fixtures."""

    directory.mkdir(parents=True, exist_ok=True)
    for scenario in built_in_scenarios().values():
        path = directory / f"{scenario.scenario_id}.scenario.json"
        payload = scenario.model_dump(mode="json")
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
