from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from parking_opt.api.app import create_app
from parking_opt.api.scenarios import built_in_scenarios
from parking_opt.api.sources import ScenarioProfile, SyntheticParkingDataSource
from facility_stub_source import (
    CorruptRouteSource,
    StaleStateSource,
    StubFacilitySource,
    UnavailableTargetSource,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _session_store_fingerprint(client: TestClient) -> tuple[object, object]:
    store = client.app.state.session_store
    return store.active_claims(), store.events()


def _without_observation_time(payload: dict[str, object]) -> dict[str, object]:
    stable = deepcopy(payload)
    stable.pop("updated_at")
    return stable


def test_facility_endpoints_are_additive_session_scoped_and_have_no_selector() -> None:
    source = StubFacilitySource()
    client = TestClient(create_app(scenario_profile=ScenarioProfile.LEGACY, facility_source=source))
    layout = client.get("/api/v2/parking-lots/lot-school/facility-layout")
    assert layout.status_code == 200
    assert layout.json()["layout_version"] == "facility-school-v1"
    missing_session = client.get("/api/v2/parking-lots/lot-school/facility-state")
    assert missing_session.status_code == 422
    assert set(missing_session.json()) == {"code", "message", "details", "request_id"}
    rejected_selector = client.get("/api/v2/parking-lots/lot-school/facility-layout?scenario_id=school-demo")
    assert rejected_selector.status_code == 422
    headers = {"X-Session-ID": "driver-contract-test"}
    before_store = _session_store_fingerprint(client)
    before_lot = client.get("/api/v2/parking-lots/lot-school", headers=headers).json()
    state = client.get("/api/v2/parking-lots/lot-school/facility-state", headers=headers)
    assert state.status_code == 200
    assert state.headers["Vary"] == "X-Session-ID"
    preview = client.post(
        "/api/v2/parking-lots/lot-school/route-previews",
        headers=headers,
        json={
            "schema_version": "1.0.0",
            "layout_version": "facility-school-v1",
            "scenario_version": "scenario-school-v1",
            "state_version": "state-1",
            "entrance_id": "entrance-south",
            "target_space_id": "T-01",
        },
    )
    assert preview.status_code == 200
    assert preview.json()["route"]["schema_version"] == "2.0.0"
    assert source.sessions == ["driver-contract-test", "driver-contract-test", "driver-contract-test"]
    assert len(source.preview_requests) == 1
    assert _session_store_fingerprint(client) == before_store
    after_lot = client.get("/api/v2/parking-lots/lot-school", headers=headers).json()
    assert _without_observation_time(after_lot) == _without_observation_time(before_lot)


@pytest.mark.parametrize(
    ("source", "expected_status"),
    [
        (CorruptRouteSource(), 503),
        (StaleStateSource(), 409),
        (UnavailableTargetSource(), 409),
    ],
)
def test_route_preview_distinguishes_source_corruption_from_stale_state(
    source: StubFacilitySource, expected_status: int
) -> None:
    client = TestClient(create_app(scenario_profile=ScenarioProfile.LEGACY, facility_source=source))
    headers = {"X-Session-ID": "driver-conflict-test"}
    before_store = _session_store_fingerprint(client)
    before_lot = client.get("/api/v2/parking-lots/lot-school", headers=headers).json()
    response = client.post(
        "/api/v2/parking-lots/lot-school/route-previews",
        headers=headers,
        json={
            "schema_version": "1.0.0",
            "layout_version": "facility-school-v1",
            "scenario_version": "scenario-school-v1",
            "state_version": "state-1",
            "entrance_id": "entrance-south",
            "target_space_id": "T-01",
        },
    )
    assert response.status_code == expected_status
    assert _session_store_fingerprint(client) == before_store
    after_lot = client.get("/api/v2/parking-lots/lot-school", headers=headers).json()
    assert _without_observation_time(after_lot) == _without_observation_time(before_lot)


def test_legacy_facility_source_fails_closed_and_public_profile_is_published() -> None:
    client = TestClient(create_app(scenario_profile=ScenarioProfile.LEGACY))
    response = client.get("/api/v2/parking-lots/lot-school/facility-layout")
    assert response.status_code == 503
    assert "not published" in response.json()["message"]
    public_client = TestClient(create_app(scenario_profile=ScenarioProfile.PUBLIC))
    assert public_client.get("/api/v2/parking-lots").status_code == 200
    assert public_client.get("/api/v2/discovery-area").status_code == 200
    assert public_client.get("/api/v2/parking-lots/lot-school/facility-layout").status_code == 200


def test_legacy_profile_is_internal_and_query_cannot_select_another_scenario() -> None:
    scenarios = built_in_scenarios()
    legacy = SyntheticParkingDataSource(scenarios, profile=ScenarioProfile.LEGACY)
    assert legacy.profile is ScenarioProfile.LEGACY
    client = TestClient(create_app(scenario_profile=ScenarioProfile.LEGACY))
    regular = client.get("/api/v2/parking-lots/lot-school/layout")
    attempted_switch = client.get("/api/v2/parking-lots/lot-school/layout?scenario_id=commercial-demo")
    assert attempted_switch.status_code == 200
    assert attempted_switch.json() == regular.json()


def test_facility_openapi_uses_the_runtime_error_model_for_422() -> None:
    schema = create_app(scenario_profile=ScenarioProfile.LEGACY).openapi()
    operations = (
        schema["paths"]["/api/v2/parking-lots/{parking_lot_id}/facility-layout"]["get"],
        schema["paths"]["/api/v2/parking-lots/{parking_lot_id}/facility-state"]["get"],
        schema["paths"]["/api/v2/parking-lots/{parking_lot_id}/route-previews"]["post"],
    )
    for operation in operations:
        error_schema = operation["responses"]["422"]["content"]["application/json"]["schema"]
        assert error_schema == {"$ref": "#/components/schemas/ErrorResponse"}


def test_r0a_legacy_hashes_remain_unchanged() -> None:
    expected = {
        "schemas/v2/layout.schema.json": "47c2409fce768ea96494abea567a1fecf1e4b3970f55102f26e1861f16f68547",
        "data/synthetic/web-v2/commercial-demo.scenario.json": "65a034399810f567ca59f5c6c04c9f022e62052e6816abeafaf9afe0aab79579",
        "data/synthetic/web-v2/school-demo.scenario.json": "b0b0e2fe0613401eb47d987441799b6ac3756a157950302fdbbd44985ece10a0",
        "data/synthetic/web-v2/hospital-demo.scenario.json": "885513da6c97dae9b9f0b3dbd1ea6d31053119a943a5890e9e0862a380261e82",
        "data/synthetic/web-v2/transport-hub-demo.scenario.json": "825077594d3fec87fa2e2a4d853955d1fefe958896e39c57417203b6061bdfca",
    }
    actual = {
        relative: hashlib.sha256((REPO_ROOT / relative).read_bytes()).hexdigest()
        for relative in expected
    }
    assert actual == expected
