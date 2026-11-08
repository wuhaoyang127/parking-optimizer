from __future__ import annotations

from fastapi.testclient import TestClient

from api_fixtures import create_app, _journey_payload


def test_all_p3_driver_commands_reject_a_mismatched_session_header() -> None:
    client = TestClient(create_app())
    headers = {"X-Session-ID": "session-header-p3"}
    wrong_headers = {"X-Session-ID": "another-session"}
    created = client.post("/api/v2/journeys/recommendations", headers=headers, json=_journey_payload(suffix="header-p3")).json()
    confirmed = client.post(
        "/api/v2/journeys/journey-header-p3/confirm",
        headers=headers,
        json={"schema_version": "2.0.0", "expected_version": created["journey"]["version"], "idempotency_key": "confirm-header-p3", "accepted": True},
    ).json()
    bad_start = client.post(
        "/api/v2/journeys/journey-header-p3/start-navigation",
        headers=wrong_headers,
        json={"schema_version": "2.0.0", "expected_version": confirmed["version"], "idempotency_key": "bad-start-header-p3"},
    )
    assert bad_start.status_code == 409
    navigating = client.post(
        "/api/v2/journeys/journey-header-p3/start-navigation",
        headers=headers,
        json={"schema_version": "2.0.0", "expected_version": confirmed["version"], "idempotency_key": "navigate-header-p3"},
    ).json()
    layout = client.get("/api/v2/parking-lots/lot-school/layout").json()
    command = {"schema_version": "2.0.0", "expected_version": navigating["version"], "idempotency_key": "bad-command-header-p3"}
    replan = {
        **command,
        "current_node_id": "entry",
        "trigger": "deviation",
        "channel_load": {
            "schema_version": "2.0.0",
            "parking_lot_id": "lot-school",
            "layout_version": layout["layout_version"],
            "observed_at": navigating["updated_at"],
            "active_units_by_zone": {item["channel_zone_id"]: 0 for item in layout["channel_zones"]},
        },
    }
    external = {**command, "replacement_journey_id": "journey-header-p3-external", "replacement_attempt_id": "attempt-header-p3-external", "replacement_request_id": "request-header-p3-external"}
    reassign = {**command, "reason": "unable_to_park", "replacement_journey_id": "journey-header-p3-reassign", "replacement_attempt_id": "attempt-header-p3-reassign", "replacement_request_id": "request-header-p3-reassign"}
    for endpoint, payload in (("replan", replan), ("report-external-occupancy", external), ("occupy", command), ("reassign", reassign)):
        response = client.post(f"/api/v2/journeys/journey-header-p3/{endpoint}", headers=wrong_headers, json=payload)
        assert response.status_code == 409, endpoint
    occupied = client.post("/api/v2/journeys/journey-header-p3/occupy", headers=headers, json={**command, "idempotency_key": "occupy-header-p3"}).json()
    for endpoint in ("depart", "reset-demo"):
        response = client.post(
            f"/api/v2/journeys/journey-header-p3/{endpoint}",
            headers=wrong_headers,
            json={"schema_version": "2.0.0", "expected_version": occupied["version"], "idempotency_key": f"bad-{endpoint}-header-p3"},
        )
        assert response.status_code == 409, endpoint


def test_replan_stale_or_non_navigating_state_returns_contract_conflict() -> None:
    client = TestClient(create_app())
    created = client.post("/api/v2/journeys/recommendations", json=_journey_payload(suffix="replan-conflict")).json()
    layout = client.get("/api/v2/parking-lots/lot-school/layout").json()
    payload = {
        "schema_version": "2.0.0",
        "expected_version": created["journey"]["version"],
        "idempotency_key": "replan-conflict",
        "current_node_id": "entry",
        "trigger": "deviation",
        "channel_load": {
            "schema_version": "2.0.0",
            "parking_lot_id": "lot-school",
            "layout_version": layout["layout_version"],
            "observed_at": created["journey"]["updated_at"],
            "active_units_by_zone": {item["channel_zone_id"]: 0 for item in layout["channel_zones"]},
        },
    }
    state_conflict = client.post("/api/v2/journeys/journey-replan-conflict/replan", json=payload)
    assert state_conflict.status_code == 409
    assert state_conflict.json()["code"] == "ILLEGALTRANSITIONERROR"
    confirmed = client.post(
        "/api/v2/journeys/journey-replan-conflict/confirm",
        json={"schema_version": "2.0.0", "expected_version": created["journey"]["version"], "idempotency_key": "confirm-replan-conflict", "accepted": True},
    ).json()
    navigating = client.post(
        "/api/v2/journeys/journey-replan-conflict/start-navigation",
        json={"schema_version": "2.0.0", "expected_version": confirmed["version"], "idempotency_key": "navigate-replan-conflict"},
    ).json()
    stale = client.post("/api/v2/journeys/journey-replan-conflict/replan", json={**payload, "idempotency_key": "stale-replan-conflict"})
    assert navigating["version"] > payload["expected_version"]
    assert stale.status_code == 409
    assert stale.json()["code"] == "VERSIONCONFLICTERROR"
    future_load = {
        **payload,
        "expected_version": navigating["version"],
        "idempotency_key": "future-load-replan-conflict",
        "channel_load": {**payload["channel_load"], "observed_at": "2099-01-01T00:00:00Z"},
    }
    future = client.post("/api/v2/journeys/journey-replan-conflict/replan", json=future_load)
    assert future.status_code == 409
    assert future.json()["code"] == "ILLEGALTRANSITIONERROR"


def test_demo_reset_is_audited_as_departed() -> None:
    client = TestClient(create_app())
    headers = {"X-Session-ID": "session-reset-api"}
    created = client.post("/api/v2/journeys/recommendations", headers=headers, json=_journey_payload(suffix="reset-api")).json()
    confirmed = client.post(
        "/api/v2/journeys/journey-reset-api/confirm",
        headers=headers,
        json={"schema_version": "2.0.0", "expected_version": created["journey"]["version"], "idempotency_key": "confirm-reset-api", "accepted": True},
    ).json()
    navigating = client.post(
        "/api/v2/journeys/journey-reset-api/start-navigation",
        headers=headers,
        json={"schema_version": "2.0.0", "expected_version": confirmed["version"], "idempotency_key": "navigate-reset-api"},
    ).json()
    occupied = client.post(
        "/api/v2/journeys/journey-reset-api/occupy",
        headers=headers,
        json={"schema_version": "2.0.0", "expected_version": navigating["version"], "idempotency_key": "occupy-reset-api"},
    ).json()
    reset = client.post(
        "/api/v2/journeys/journey-reset-api/reset-demo",
        headers=headers,
        json={"schema_version": "2.0.0", "expected_version": occupied["version"], "idempotency_key": "reset-api"},
    )
    assert reset.status_code == 200
    assert reset.json()["state"] == "departed"
    assert reset.json()["terminal_reason"] == "DEMO_RESET"
    trip = client.get("/api/v2/driver-session/current-trip", headers=headers)
    assert trip.status_code == 200
    assert trip.json()["journey"]["state"] == "departed"
    assert trip.json()["current_route"] is None
    assert trip.json()["current_node_id"] is None
    assert trip.json()["last_replan"] is None
    assert trip.json()["recent_trips"][0]["terminal_reason"] == "DEMO_RESET"
