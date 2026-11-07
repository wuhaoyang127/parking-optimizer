from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from parking_opt.api.adapters.v1 import V1OnlineRuleAdapter
from parking_opt.api.models import CostSnapshot, DriverRequest
from parking_opt.api.routing import RouteCostService
from parking_opt.api.scenarios import built_in_scenarios
from parking_opt.api.services.online_rule import OnlineRuleServiceV2

REPO_ROOT = Path(__file__).resolve().parents[2]


def _service(*, clock: Callable[[], float] | None = None) -> OnlineRuleServiceV2:
    routes = RouteCostService()
    return OnlineRuleServiceV2(
        v1_adapter=V1OnlineRuleAdapter(
            schema_dir=REPO_ROOT / "schemas" / "v1",
            route_service=routes,
            clock=clock,
        ),
        route_service=routes,
    )


def _request(lot_id: str, *, charging: bool = False) -> DriverRequest:
    return DriverRequest(
        request_id="request-001",
        idempotency_key="idem-001",
        session_id="session-001",
        parking_lot_id=lot_id,
        entrance_node_id="entry",
        requires_charging=charging,
        requested_at=datetime(2026, 8, 12, 9, 1, tzinfo=UTC),
    )


def test_recommendation_is_deterministic_and_does_not_create_claim() -> None:
    bundle = built_in_scenarios()["school-demo"]
    request = _request(bundle.parking_lot.parking_lot_id)
    first = _service().recommend(
        request, bundle.layout, bundle.cost_snapshot, bundle.parking_lot.data_source
    )
    second = _service().recommend(
        request, bundle.layout, bundle.cost_snapshot, bundle.parking_lot.data_source
    )
    assert first == second
    assert first.solver_status == "success"
    assert first.recommended_space_id == "C-01"
    assert first.claim_status == "not_created_m2"
    assert first.soft_lock_expires_at is None


def test_v1_tandem_blocking_filter_is_preserved() -> None:
    bundle = built_in_scenarios()["school-demo"]
    result = _service().recommend(
        _request(bundle.parking_lot.parking_lot_id),
        bundle.layout,
        bundle.cost_snapshot,
        bundle.parking_lot.data_source,
    )
    b02 = next(item for item in result.assessments if item.space_id == "B-02")
    assert b02.feasible is False
    assert "ENTRY_NOT_CLEAR" in b02.reason_codes


def test_charging_requirement_is_a_v2_hard_constraint() -> None:
    bundle = built_in_scenarios()["commercial-demo"]
    result = _service().recommend(
        _request(bundle.parking_lot.parking_lot_id, charging=True),
        bundle.layout,
        bundle.cost_snapshot,
        bundle.parking_lot.data_source,
    )
    assert result.recommended_space_id in {"A-01", "A-02"}
    non_charging = next(item for item in result.assessments if item.space_id == "B-01")
    assert non_charging.feasible is False
    assert "CHARGING_REQUIRED" in non_charging.reason_codes


def test_current_dynamic_eta_can_reorder_v1_feasible_candidates() -> None:
    bundle = built_in_scenarios()["commercial-demo"]
    values = dict(bundle.cost_snapshot.edge_travel_time_s)
    values["edge-junction-a"] = 80
    values["edge-junction-b"] = 4
    costs = CostSnapshot(
        parking_lot_id=bundle.parking_lot.parking_lot_id,
        layout_version=bundle.layout.layout_version,
        cost_version="cost-b-is-faster",
        observed_at=bundle.cost_snapshot.observed_at,
        edge_travel_time_s=values,
    )
    result = _service().recommend(
        _request(bundle.parking_lot.parking_lot_id),
        bundle.layout,
        costs,
        bundle.parking_lot.data_source,
    )
    assert result.recommended_space_id == "B-01"
    assert result.route is not None
    assert result.route.cost_version == "cost-b-is-faster"


def test_v1_timeout_is_not_reported_as_no_feasible_space() -> None:
    bundle = built_in_scenarios()["school-demo"]
    ticks = iter((0.0, 99.0))

    def clock() -> float:
        return next(ticks, 99.0)

    result = _service(clock=clock).recommend(
        _request(bundle.parking_lot.parking_lot_id),
        bundle.layout,
        bundle.cost_snapshot,
        bundle.parking_lot.data_source,
    )
    assert result.solver_status == "failed"
    assert result.failure_code == "V1_ASSESSMENT_TIMEOUT"
    assert result.recommended_space_id is None
