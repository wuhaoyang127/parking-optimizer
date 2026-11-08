from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from parking_opt.api.adapters.v1 import V1OnlineRuleAdapter
from parking_opt.api.app import create_app
from parking_opt.api.facility_scenarios import PUBLIC_SPECS, build_public_facility_scenarios
from parking_opt.api.models import DriverRequest, SpaceStatus
from parking_opt.api.routing import RouteCostService
from parking_opt.api.services.online_rule import OnlineRuleServiceV2
from parking_opt.api.sources import ScenarioProfile

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("spec", PUBLIC_SPECS)
def test_online_rule_smoke_covers_regular_charging_tandem_and_route(spec) -> None:  # type: ignore[no-untyped-def]
    scenario = build_public_facility_scenarios()[spec.lot_id]
    routes = RouteCostService()
    service = OnlineRuleServiceV2(
        v1_adapter=V1OnlineRuleAdapter(
            schema_dir=REPO_ROOT / "schemas" / "v1", route_service=routes
        ),
        route_service=routes,
    )
    entrance_node = scenario.bundle.layout.entrance_node_ids[0]
    for charging in (False, True):
        result = service.recommend(
            DriverRequest(
                request_id=f"request-{charging}",
                idempotency_key=f"idem-{charging}",
                session_id="session-smoke",
                parking_lot_id=spec.lot_id,
                entrance_node_id=entrance_node,
                requires_charging=charging,
                requested_at=datetime(2026, 8, 20, 10, 0, tzinfo=UTC),
            ),
            scenario.bundle.layout,
            scenario.bundle.cost_snapshot,
            scenario.bundle.parking_lot.data_source,
        )
        assert result.solver_status == "success"
        assert result.route is not None
        if charging:
            chosen = next(
                item
                for item in scenario.bundle.layout.spaces
                if item.space_id == result.recommended_space_id
            )
            assert chosen.charging
    tandem_ids = {
        space_id
        for group in scenario.bundle.layout.tandem_groups
        for space_id in group.space_ids_near_to_deep
    }
    assert tandem_ids
    assert tandem_ids <= {item.space_id for item in result.assessments}

    forced_spaces = tuple(
        item
        if item.space_id in tandem_ids
        else item.model_copy(
            update={
                "status": SpaceStatus.OCCUPIED,
                "assignable": False,
                "assignability_reasons": ("SPACE_OCCUPIED",),
            }
        )
        for item in scenario.bundle.layout.spaces
    )
    tandem_layout = scenario.bundle.layout.model_copy(update={"spaces": forced_spaces})
    tandem_result = service.recommend(
        DriverRequest(
            request_id="request-tandem",
            idempotency_key="idem-tandem",
            session_id="session-tandem",
            parking_lot_id=spec.lot_id,
            entrance_node_id=entrance_node,
            requested_at=datetime(2026, 8, 20, 10, 0, tzinfo=UTC),
        ),
        tandem_layout,
        scenario.bundle.cost_snapshot,
        scenario.bundle.parking_lot.data_source,
    )
    assert tandem_result.solver_status == "success"
    assert tandem_result.recommended_space_id in tandem_ids
    assert tandem_result.route is not None

    no_buffer_layout = tandem_layout.model_copy(
        update={
            "spaces": tuple(
                item.model_copy(
                    update={
                        "status": SpaceStatus.OCCUPIED,
                        "assignable": False,
                        "assignability_reasons": ("SPACE_OCCUPIED",),
                    }
                )
                if item.space_id in tandem_ids and item.depth == 2
                else item
                for item in tandem_layout.spaces
            ),
            "buffers": tuple(
                item.model_copy(update={"available": False}) for item in tandem_layout.buffers
            ),
        }
    )
    failed = service.recommend(
        DriverRequest(
            request_id="request-no-buffer",
            idempotency_key="idem-no-buffer",
            session_id="session-no-buffer",
            parking_lot_id=spec.lot_id,
            entrance_node_id=entrance_node,
            requested_at=datetime(2026, 8, 20, 10, 0, tzinfo=UTC),
        ),
        no_buffer_layout,
        scenario.bundle.cost_snapshot,
        scenario.bundle.parking_lot.data_source,
    )
    assert failed.solver_status == "no_feasible_space"
    assert all(not item.feasible for item in failed.assessments)


def test_public_profile_serves_complete_resources_by_default() -> None:
    client = TestClient(create_app(scenario_profile=ScenarioProfile.PUBLIC))
    lots = client.get("/api/v2/parking-lots")
    assert lots.status_code == 200
    assert {item["total_spaces"] for item in lots.json()} == {28, 32, 48, 52}
    layout = client.get("/api/v2/parking-lots/lot-commercial/facility-layout")
    assert layout.status_code == 200
    state = client.get(
        "/api/v2/parking-lots/lot-commercial/facility-state", headers={"X-Session-ID": "api-r1"}
    )
    assert state.status_code == 200
    target = next(item for item in state.json()["spaces"] if item["assignable"])
    preview = client.post(
        "/api/v2/parking-lots/lot-commercial/route-previews",
        headers={"X-Session-ID": "api-r1"},
        json={
            "schema_version": "1.0.0",
            "layout_version": layout.json()["layout_version"],
            "scenario_version": state.json()["scenario_version"],
            "state_version": state.json()["state_version"],
            "entrance_id": layout.json()["default_entrance_id"],
            "target_space_id": target["space_id"],
        },
    )
    assert preview.status_code == 200
