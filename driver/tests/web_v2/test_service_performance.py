from __future__ import annotations

import math
import tomllib
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from time import perf_counter_ns

from parking_opt.api.adapters.v1 import V1OnlineRuleAdapter
from parking_opt.api.dynamic_costs import DynamicCostService
from parking_opt.api.models import ChannelLoadSnapshot, DriverRequest
from parking_opt.api.routing import RouteCostService
from parking_opt.api.scenarios import built_in_scenarios
from parking_opt.api.services.journey import JourneyRecommendationService
from parking_opt.api.services.online_rule import OnlineRuleServiceV2
from parking_opt.api.services.replanning import JourneyReplanService
from parking_opt.api.sessions import InMemorySessionStore, SessionNamespace, SessionTiming

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_COUNT = 40


def _budgets() -> dict[str, int]:
    with (REPO_ROOT / "configs" / "web-v2" / "m3.toml").open("rb") as handle:
        performance = tomllib.load(handle).get("performance")
    if not isinstance(performance, dict):
        raise ValueError("m3.toml requires a performance table")
    budgets: dict[str, int] = {}
    for key, value in performance.items():
        if not isinstance(key, str) or not isinstance(value, int):
            raise ValueError("M3 performance budgets must be integer values")
        budgets[key] = value
    return budgets


def _timing() -> SessionTiming:
    return SessionTiming(
        driver_idle_ttl_s=1800,
        defense_idle_ttl_s=7200,
        soft_hold_ttl_s=30,
        driver_reservation_ttl_s=300,
        defense_reservation_ttl_s=60,
    )


def _p95_ms(samples_ns: list[int]) -> float:
    rank = math.ceil(0.95 * len(samples_ns)) - 1
    return sorted(samples_ns)[rank] / 1_000_000


def _measure(operation: Callable[[], object]) -> int:
    started = perf_counter_ns()
    operation()
    return perf_counter_ns() - started


def _recommendation_service(store: InMemorySessionStore) -> JourneyRecommendationService:
    routes = RouteCostService()
    online = OnlineRuleServiceV2(
        v1_adapter=V1OnlineRuleAdapter(
            schema_dir=REPO_ROOT / "schemas" / "v1",
            route_service=routes,
        ),
        route_service=routes,
    )
    return JourneyRecommendationService(
        online_rule=online,
        route_service=routes,
        session_store=store,
        eta_safety_margin_s=60,
        driver_reservation_ttl_s=300,
    )


def test_state_command_p95_meets_frozen_budget() -> None:
    samples: list[int] = []
    for index in range(SAMPLE_COUNT + 1):
        store = InMemorySessionStore(timing=_timing())
        elapsed = _measure(
            partial(
                store.soft_hold,
                session_id=f"perf-session-{index}",
                namespace=SessionNamespace.DRIVER,
                scenario_id="school-demo",
                parking_lot_id="lot-school",
                journey_id=f"perf-journey-{index}",
                attempt_id=f"perf-attempt-{index}",
                space_id="A-01",
                idempotency_key=f"perf-hold-{index}",
            )
        )
        if index:
            samples.append(elapsed)
    assert _p95_ms(samples) <= _budgets()["state_command_p95_ms"]


def test_recommend_and_hold_p95_meets_frozen_budget() -> None:
    bundle = built_in_scenarios()["school-demo"]
    samples: list[int] = []
    for index in range(SAMPLE_COUNT + 1):
        store = InMemorySessionStore(timing=_timing())
        service = _recommendation_service(store)
        driver = DriverRequest(
            request_id=f"perf-request-{index}",
            idempotency_key=f"perf-driver-{index}",
            session_id=f"perf-session-{index}",
            parking_lot_id=bundle.layout.parking_lot_id,
            entrance_node_id=bundle.layout.entrance_node_ids[0],
            requested_at=datetime(2026, 8, 13, tzinfo=UTC),
        )
        elapsed = _measure(
            partial(
                service.recommend_and_hold,
                driver=driver,
                namespace=SessionNamespace.DRIVER,
                scenario_id=bundle.scenario_id,
                journey_id=f"perf-journey-{index}",
                attempt_id=f"perf-attempt-{index}",
                layout=bundle.layout,
                costs=bundle.cost_snapshot,
                data_source=bundle.parking_lot.data_source,
                idempotency_key=f"perf-recommend-{index}",
            )
        )
        if index:
            samples.append(elapsed)
    assert _p95_ms(samples) <= _budgets()["recommend_and_hold_p95_ms"]


def test_replan_p95_meets_frozen_budget() -> None:
    bundle = built_in_scenarios()["school-demo"]
    target = bundle.layout.spaces[0]
    samples: list[int] = []
    for index in range(SAMPLE_COUNT + 1):
        store = InMemorySessionStore(timing=_timing())
        held = store.soft_hold(
            session_id=f"perf-session-{index}",
            namespace=SessionNamespace.DRIVER,
            scenario_id=bundle.scenario_id,
            parking_lot_id=bundle.layout.parking_lot_id,
            journey_id=f"perf-journey-{index}",
            attempt_id=f"perf-attempt-{index}",
            space_id=target.space_id,
            idempotency_key=f"perf-hold-{index}",
        )
        reserved = store.confirm(
            journey_id=held.journey_id,
            accepted=True,
            expected_version=held.version,
            idempotency_key=f"perf-confirm-{index}",
        )
        navigating = store.start_navigation(
            journey_id=held.journey_id,
            expected_version=reserved.version,
            idempotency_key=f"perf-navigate-{index}",
        )
        routes = RouteCostService()
        original = routes.route(
            bundle.layout,
            bundle.cost_snapshot,
            from_node_id=bundle.layout.entrance_node_ids[0],
            to_node_id=target.access_node_id,
        )
        service = JourneyReplanService(
            route_service=routes,
            cost_service=DynamicCostService(),
            session_store=store,
            eta_safety_margin_s=60,
        )
        service.register_route(held.journey_id, original)
        load = ChannelLoadSnapshot(
            parking_lot_id=bundle.layout.parking_lot_id,
            layout_version=bundle.layout.layout_version,
            observed_at=store.current_wall_time(),
            active_units_by_zone={
                zone.channel_zone_id: 0 for zone in bundle.layout.channel_zones
            },
        )
        elapsed = _measure(
            partial(
                service.replan,
                journey_id=navigating.journey_id,
                expected_version=navigating.version,
                current_node_id=bundle.layout.entrance_node_ids[0],
                trigger="deviation",
                layout=bundle.layout,
                channel_load=load,
                idempotency_key=f"perf-replan-{index}",
            )
        )
        if index:
            samples.append(elapsed)
    assert _p95_ms(samples) <= _budgets()["replan_p95_ms"]
