from __future__ import annotations

from fastapi.testclient import TestClient

from api_fixtures import create_app, _journey_payload


def test_journey_api_runs_soft_hold_to_normal_departure() -> None:
    client = TestClient(create_app())
    recommendation = client.post(
        "/api/v2/journeys/recommendations",
        json={
            "schema_version": "2.0.0",
            "namespace": "driver",
            "scenario_id": "school-demo",
            "journey_id": "journey-api-lifecycle",
            "attempt_id": "attempt-api-lifecycle",
            "algorithm_id": "online-rule-v2",
            "idempotency_key": "recommend-api-lifecycle",
            "driver": {
                "schema_version": "2.0.0",
                "request_id": "request-api-lifecycle",
                "idempotency_key": "driver-api-lifecycle",
                "session_id": "session-api-lifecycle",
                "parking_lot_id": "lot-school",
                "entrance_node_id": "entry",
                "requires_charging": False,
                "requested_at": "2026-08-13T00:00:00Z",
                "expected_departure_at": None,
            },
        },
    )
    assert recommendation.status_code == 200
    body = recommendation.json()
    assert body["recommendation"]["claim_status"] == "soft_held"
    assert body["journey"]["state"] == "soft_held"
    assert body["journey"]["expires_at"] is not None
    confirm = client.post(
        "/api/v2/journeys/journey-api-lifecycle/confirm",
        json={"schema_version": "2.0.0", "expected_version": body["journey"]["version"], "idempotency_key": "confirm-api-lifecycle", "accepted": True},
    )
    assert confirm.status_code == 200
    assert confirm.json()["state"] == "session_reserved"
    original_expiry = confirm.json()["expires_at"]
    navigation = client.post(
        "/api/v2/journeys/journey-api-lifecycle/start-navigation",
        json={"schema_version": "2.0.0", "expected_version": confirm.json()["version"], "idempotency_key": "navigate-api-lifecycle"},
    )
    assert navigation.status_code == 200
    assert navigation.json()["state"] == "navigating"
    assert navigation.json()["expires_at"] == original_expiry
    occupied = client.post(
        "/api/v2/journeys/journey-api-lifecycle/occupy",
        json={"schema_version": "2.0.0", "expected_version": navigation.json()["version"], "idempotency_key": "occupy-api-lifecycle"},
    )
    assert occupied.status_code == 200
    assert occupied.json()["state"] == "occupied"
    assert occupied.json()["expires_at"] is None
    departed = client.post(
        "/api/v2/journeys/journey-api-lifecycle/depart",
        json={"schema_version": "2.0.0", "expected_version": occupied.json()["version"], "idempotency_key": "depart-api-lifecycle"},
    )
    assert departed.status_code == 200
    assert departed.json()["state"] == "departed"
    assert departed.json()["terminal_reason"] == "NORMAL_DEPARTURE"


def test_journey_api_returns_structured_version_conflict() -> None:
    client = TestClient(create_app())
    response = client.get("/api/v2/journeys/missing-journey")
    assert response.status_code == 404
    assert response.json()["code"] == "JOURNEY_NOT_FOUND"


def test_journey_api_selects_alternative_with_consistent_route_and_replay() -> None:
    client = TestClient(create_app())
    created = client.post("/api/v2/journeys/recommendations", json=_journey_payload(suffix="alternative"))
    assert created.status_code == 200
    body = created.json()
    alternative = body["recommendation"]["alternative_space_ids"][0]
    command = {"schema_version": "2.0.0", "expected_version": body["journey"]["version"], "idempotency_key": "select-alternative-api", "space_id": alternative}
    switched = client.post("/api/v2/journeys/journey-alternative/select-alternative", json=command)
    replay = client.post("/api/v2/journeys/journey-alternative/select-alternative", json=command)
    assert switched.status_code == 200
    assert replay.json() == switched.json()
    switched_body = switched.json()
    assert switched_body["journey"]["space_id"] == alternative
    assert switched_body["recommendation"]["recommended_space_id"] == alternative
    layout = client.get("/api/v2/parking-lots/lot-school/layout").json()
    target = next(item for item in layout["spaces"] if item["space_id"] == alternative)
    assert switched_body["recommendation"]["route"]["to_node_id"] == target["access_node_id"]
    assert switched_body["journey"]["expires_at"] == body["journey"]["expires_at"]


def test_waiting_journey_changes_only_on_explicit_retry() -> None:
    app = create_app()
    client = TestClient(app)
    source = app.state.data_source
    bundle = source.get_bundle("lot-school")
    slow = bundle.cost_snapshot.model_copy(
        update={"cost_version": "cost-api-too-slow", "edge_travel_time_s": {key: 300.0 for key in bundle.cost_snapshot.edge_travel_time_s}}
    )
    source._by_lot["lot-school"] = bundle.model_copy(update={"cost_snapshot": slow})  # type: ignore[attr-defined]
    created = client.post("/api/v2/journeys/recommendations", json=_journey_payload(suffix="waiting"))
    assert created.status_code == 200
    waiting = created.json()["journey"]
    assert waiting["state"] == "waiting"
    queried = client.get("/api/v2/journeys/journey-waiting")
    assert queried.json()["version"] == waiting["version"]
    retry = client.post(
        "/api/v2/journeys/journey-waiting/retry-recommendation",
        json={"schema_version": "2.0.0", "expected_version": waiting["version"], "idempotency_key": "retry-waiting-api"},
    )
    assert retry.status_code == 200
    assert retry.json()["journey"]["state"] == "waiting"
    assert retry.json()["journey"]["version"] == waiting["version"] + 1
