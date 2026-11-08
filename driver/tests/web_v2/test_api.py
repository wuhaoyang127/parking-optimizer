from __future__ import annotations

from fastapi.testclient import TestClient

from api_fixtures import create_app, _journey_payload


def test_v2_read_endpoints_expose_explicit_synthetic_status() -> None:
    client = TestClient(create_app())
    health = client.get("/api/v2/health")
    assert health.status_code == 200
    assert health.json()["data_mode"] == "synthetic"
    lots = client.get("/api/v2/parking-lots")
    assert lots.status_code == 200
    assert len(lots.json()) == 4
    assert all(item["synthetic"] is True for item in lots.json())
    discovery = client.get("/api/v2/discovery-area")
    assert discovery.status_code == 200
    assert discovery.json()["schema_version"] == "1.0.0"
    assert discovery.json()["synthetic"] is True
    assert len(discovery.json()["lots"]) == 4
    assert len(discovery.json()["references"]) == 3


def test_session_aware_parking_lots_follow_claim_lifecycle_and_remain_isolated() -> None:
    client = TestClient(create_app())
    session_headers = {"X-Session-ID": "session-availability-api"}
    other_headers = {"X-Session-ID": "session-other-api"}
    initial_response = client.get("/api/v2/parking-lots", headers=session_headers)
    assert initial_response.headers["Cache-Control"] == "no-store"
    assert initial_response.headers["Vary"] == "X-Session-ID"
    initial = next(item for item in initial_response.json() if item["parking_lot_id"] == "lot-school")
    created = client.post("/api/v2/journeys/recommendations", json=_journey_payload(suffix="availability-api")).json()
    assert created["journey"]["session_id"] == "session-availability-api"
    held = next(item for item in client.get("/api/v2/parking-lots", headers=session_headers).json() if item["parking_lot_id"] == "lot-school")
    other = next(item for item in client.get("/api/v2/parking-lots", headers=other_headers).json() if item["parking_lot_id"] == "lot-school")
    single = client.get("/api/v2/parking-lots/lot-school", headers=session_headers)
    assert held["available_spaces"] == initial["available_spaces"] - 1
    assert single.json()["available_spaces"] == held["available_spaces"]
    assert single.headers["Cache-Control"] == "no-store"
    assert other["available_spaces"] == initial["available_spaces"]
    cancelled = client.post(
        "/api/v2/journeys/journey-availability-api/cancel",
        json={"schema_version": "2.0.0", "expected_version": created["journey"]["version"], "idempotency_key": "cancel-availability-api"},
    )
    assert cancelled.status_code == 200
    restored = client.get("/api/v2/parking-lots/lot-school", headers=session_headers).json()
    assert restored["available_spaces"] == initial["available_spaces"]


def test_session_header_is_optional_and_validated() -> None:
    client = TestClient(create_app())
    baseline = client.get("/api/v2/parking-lots")
    assert baseline.status_code == 200
    assert baseline.headers["Cache-Control"] == "no-store"
    assert baseline.headers["Vary"] == "X-Session-ID"
    single = client.get("/api/v2/parking-lots/lot-school")
    assert single.headers["Cache-Control"] == "no-store"
    assert single.headers["Vary"] == "X-Session-ID"
    invalid = client.get("/api/v2/parking-lots", headers={"X-Session-ID": "bad id"})
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "CONTRACT_VALIDATION_FAILED"
    invalid_single = client.get("/api/v2/parking-lots/lot-school", headers={"X-Session-ID": "bad id"})
    assert invalid_single.status_code == 422
    assert invalid_single.json()["code"] == "CONTRACT_VALIDATION_FAILED"


def test_driver_context_exposes_server_derived_scenario_and_entrance() -> None:
    client = TestClient(create_app())
    response = client.get("/api/v2/parking-lots/lot-school/driver-context", headers={"X-Session-ID": "session-driver-context"})
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Vary"] == "X-Session-ID"
    body = response.json()
    assert body["schema_version"] == "1.0.0"
    assert body["scenario_id"] == "school-demo"
    assert body["parking_lot_id"] == "lot-school"
    assert body["entrances"] == [{"node_id": "entry", "label": "入口"}]


def test_current_driver_snapshot_recovers_full_soft_hold_without_renewal() -> None:
    client = TestClient(create_app())
    suffix = "recover-api"
    payload = _journey_payload(suffix=suffix)
    created = client.post("/api/v2/journeys/recommendations", json=payload).json()
    response = client.get("/api/v2/driver-session/current-journey", headers={"X-Session-ID": f"session-{suffix}"})
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    body = response.json()
    assert body["journey"] == created["journey"]
    assert body["recommendation"] == created["recommendation"]
    assert body["driver"] == payload["driver"]
    assert body["journey"]["expires_at"] == created["journey"]["expires_at"]
    assert body["waiting_since"] is None


def test_current_driver_snapshot_has_explicit_empty_state() -> None:
    client = TestClient(create_app())
    response = client.get("/api/v2/driver-session/current-journey", headers={"X-Session-ID": "session-without-journey"})
    assert response.status_code == 200
    assert response.json()["journey"] is None
    assert response.json()["recommendation"] is None
    assert response.json()["driver"] is None
