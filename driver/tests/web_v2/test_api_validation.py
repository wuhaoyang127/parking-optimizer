from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from api_fixtures import REPO_ROOT, create_app


def test_naive_request_time_is_a_contract_error() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/v2/recommendations",
        json={
            "schema_version": "2.0.0",
            "algorithm_id": "online-rule-v2",
            "driver": {
                "schema_version": "2.0.0",
                "request_id": "request-naive-api",
                "idempotency_key": "idem-naive-api",
                "session_id": "session-naive-api",
                "parking_lot_id": "lot-school",
                "entrance_node_id": "entry",
                "requires_charging": False,
                "requested_at": "2026-08-12T09:01:00",
                "expected_departure_at": None,
            },
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "CONTRACT_VALIDATION_FAILED"


def test_unknown_entrance_is_a_capability_conflict_not_an_algorithm_failure() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/v2/recommendations",
        json={
            "schema_version": "2.0.0",
            "algorithm_id": "online-rule-v2",
            "driver": {
                "schema_version": "2.0.0",
                "request_id": "request-bad-entry",
                "idempotency_key": "idem-bad-entry",
                "session_id": "session-bad-entry",
                "parking_lot_id": "lot-school",
                "entrance_node_id": "missing-entry",
                "requires_charging": False,
                "requested_at": "2026-08-12T09:01:00Z",
                "expected_departure_at": None,
            },
        },
    )
    assert response.status_code == 409
    assert response.json()["code"] == "CAPABILITY_CONFLICT"


def test_unexpected_failure_is_structured_and_does_not_leak_details() -> None:
    class Bomb:
        def recommend(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("secret internal detail")

    app = create_app()
    app.state.recommender = Bomb()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post(
        "/api/v2/recommendations",
        json={
            "schema_version": "2.0.0",
            "algorithm_id": "online-rule-v2",
            "driver": {
                "schema_version": "2.0.0",
                "request_id": "request-bomb",
                "idempotency_key": "idem-bomb",
                "session_id": "session-bomb",
                "parking_lot_id": "lot-school",
                "entrance_node_id": "entry",
                "requires_charging": False,
                "requested_at": "2026-08-12T09:01:00Z",
                "expected_departure_at": None,
            },
        },
    )
    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_SERVER_ERROR"
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    assert "secret" not in response.text


def test_validation_error_and_openapi_snapshot_are_versioned() -> None:
    client = TestClient(create_app())
    response = client.post("/api/v2/recommendations", json={})
    assert response.status_code == 422
    assert response.json()["code"] == "CONTRACT_VALIDATION_FAILED"
    assert response.json()["details"]
    expected = json.loads((REPO_ROOT / "schemas" / "v2" / "openapi.json").read_text())
    assert create_app().openapi() == expected
