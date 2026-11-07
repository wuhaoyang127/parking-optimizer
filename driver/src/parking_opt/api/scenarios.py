"""Deterministic synthetic parking-lot scenarios for web-v2 development and demos."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from parking_opt.api.models import (
    Coordinate,
    ParkingSpace,
    PricingSummary,
    ScenarioBundle,
    SpaceStatus,
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


from parking_opt.api.scenario_bundle import _bundle  # noqa: E402
