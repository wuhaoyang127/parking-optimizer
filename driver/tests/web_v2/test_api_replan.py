from __future__ import annotations

from fastapi.testclient import TestClient

from parking_opt.api.models import DataMode
from api_fixtures import create_app, _journey_payload


def test_journey_api_replans_navigation_from_visible_channel_load() -> None:
    client = TestClient(create_app())
    created = client.post("/api/v2/journeys/recommendations", json=_journey_payload(suffix="replan-api")).json()
    confirmed = client.post(
        "/api/v2/journeys/journey-replan-api/confirm",
        json={"schema_version": "2.0.0", "expected_version": created["journey"]["version"], "idempotency_key": "confirm-replan-api", "accepted": True},
    ).json()
    navigating = client.post(
        "/api/v2/journeys/journey-replan-api/start-navigation",
        json={"schema_version": "2.0.0", "expected_version": confirmed["version"], "idempotency_key": "navigate-replan-api"},
    ).json()
    layout = client.get("/api/v2/parking-lots/lot-school/layout").json()
    load = {zone["channel_zone_id"]: 0 for zone in layout["channel_zones"]}
    response = client.post(
        "/api/v2/journeys/journey-replan-api/replan",
        json={
            "schema_version": "2.0.0",
            "expected_version": navigating["version"],
            "idempotency_key": "replan-api",
            "current_node_id": "entry",
            "trigger": "deviation",
            "channel_load": {
                "schema_version": "2.0.0",
                "parking_lot_id": "lot-school",
                "layout_version": layout["layout_version"],
                "observed_at": navigating["updated_at"],
                "active_units_by_zone": load,
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["journey"]["state"] == "navigating"
    assert body["journey"]["expires_at"] == navigating["expires_at"]
    assert body["decision"]["status"] == "success"
    assert body["decision"]["route"]["cost_version"].startswith("cost-dynamic-")
    assert set(body["decision"]["cost_snapshot"]["edge_travel_time_s"]) == {edge["edge_id"] for edge in layout["edges"]}
    trip = client.get("/api/v2/driver-session/current-trip", headers={"X-Session-ID": "session-replan-api"})
    assert trip.status_code == 200
    assert trip.headers["Cache-Control"] == "no-store"
    assert trip.json()["journey"]["state"] == "navigating"
    assert trip.json()["current_route"] == body["decision"]["route"]
    assert trip.json()["last_replan"]["status"] == "success"
    assert trip.json()["current_node_id"] == "entry"


def test_driver_demo_replan_derives_inputs_and_exposes_action_capabilities() -> None:
    client = TestClient(create_app())
    headers = {"X-Session-ID": "session-driver-demo-api"}
    created = client.post("/api/v2/journeys/recommendations", headers=headers, json=_journey_payload(suffix="driver-demo-api")).json()
    confirmed = client.post(
        "/api/v2/journeys/journey-driver-demo-api/confirm",
        headers=headers,
        json={"schema_version": "2.0.0", "expected_version": created["journey"]["version"], "idempotency_key": "confirm-driver-demo-api", "accepted": True},
    ).json()
    navigating = client.post(
        "/api/v2/journeys/journey-driver-demo-api/start-navigation",
        headers=headers,
        json={"schema_version": "2.0.0", "expected_version": confirmed["version"], "idempotency_key": "navigate-driver-demo-api"},
    ).json()
    assert {"driver_demo_replan", "report_external_occupancy", "reassign", "occupy"}.issubset(navigating["legal_operations"])
    payload = {"schema_version": "2.0.0", "expected_version": navigating["version"], "idempotency_key": "driver-demo-api", "action": "simulate_deviation"}
    first = client.post("/api/v2/journeys/journey-driver-demo-api/driver-demo-replan", headers=headers, json=payload)
    replay = client.post("/api/v2/journeys/journey-driver-demo-api/driver-demo-replan", headers=headers, json=payload)
    assert first.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["decision"]["trigger"] == "deviation"
    mismatch = client.post("/api/v2/journeys/journey-driver-demo-api/driver-demo-replan", headers=headers, json={**payload, "action": "simulate_cost_update"})
    assert mismatch.status_code == 409
    version_mismatch = client.post(
        "/api/v2/journeys/journey-driver-demo-api/driver-demo-replan",
        headers=headers,
        json={**payload, "expected_version": first.json()["journey"]["version"]},
    )
    assert version_mismatch.status_code == 409


def test_demo_actions_fail_closed_outside_synthetic_mode() -> None:
    app = create_app()
    client = TestClient(app)
    headers = {"X-Session-ID": "session-demo-guard"}
    created = client.post("/api/v2/journeys/recommendations", headers=headers, json=_journey_payload(suffix="demo-guard")).json()
    confirmed = client.post(
        "/api/v2/journeys/journey-demo-guard/confirm",
        headers=headers,
        json={"schema_version": "2.0.0", "expected_version": created["journey"]["version"], "idempotency_key": "confirm-demo-guard", "accepted": True},
    ).json()
    navigating = client.post(
        "/api/v2/journeys/journey-demo-guard/start-navigation",
        headers=headers,
        json={"schema_version": "2.0.0", "expected_version": confirmed["version"], "idempotency_key": "navigate-demo-guard"},
    ).json()
    app.state.data_mode = DataMode.REAL
    denied = client.post(
        "/api/v2/journeys/journey-demo-guard/driver-demo-replan",
        headers=headers,
        json={"schema_version": "2.0.0", "expected_version": navigating["version"], "idempotency_key": "demo-guard", "action": "simulate_deviation"},
    )
    assert denied.status_code == 409
    assert "synthetic" in denied.json()["message"]
