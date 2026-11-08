from __future__ import annotations

from fastapi.testclient import TestClient

from parking_opt.api.models import DataMode
from parking_opt.api.sessions import SessionNamespace
from api_fixtures import create_app, _journey_payload


def test_driver_mutation_rejects_a_mismatched_session_header() -> None:
    client = TestClient(create_app())
    payload = _journey_payload(suffix="header-match")
    mismatched = client.post("/api/v2/journeys/recommendations", json=payload, headers={"X-Session-ID": "another-driver-session"})
    assert mismatched.status_code == 409
    created = client.post("/api/v2/journeys/recommendations", json=payload, headers={"X-Session-ID": "session-header-match"}).json()["journey"]
    cancelled = client.post(
        f"/api/v2/journeys/{created['journey_id']}/cancel",
        headers={"X-Session-ID": "another-driver-session"},
        json={"schema_version": "2.0.0", "expected_version": created["version"], "idempotency_key": "cancel-header-mismatch"},
    )
    assert cancelled.status_code == 409


def test_tandem_decline_creates_fresh_attempt_and_excludes_rejected_space() -> None:
    client = TestClient(create_app())
    suffix = "decline-api"
    payload = _journey_payload(suffix=suffix, namespace="defense")
    store = client.app.state.session_store
    for index, space_id in enumerate(("C-01", "A-02", "A-03"), start=1):
        store.soft_hold(
            session_id=f"session-{suffix}",
            namespace=SessionNamespace.DEFENSE,
            scenario_id="school-demo",
            parking_lot_id="lot-school",
            journey_id=f"defense-decline-{index}",
            attempt_id=f"defense-attempt-{index}",
            space_id=space_id,
            idempotency_key=f"defense-hold-{index}",
        )
    first = client.post("/api/v2/journeys/recommendations", json=payload).json()
    rejected_space = first["journey"]["space_id"]
    assert rejected_space in {"B-02", "B-03", "B-04"}
    response = client.post(
        f"/api/v2/journeys/{first['journey']['journey_id']}/decline-tandem",
        json={
            "schema_version": "2.0.0",
            "expected_version": first["journey"]["version"],
            "idempotency_key": "decline-api-command",
            "replacement_journey_id": "journey-decline-api-next",
            "replacement_attempt_id": "attempt-decline-api-next",
            "replacement_request_id": "request-decline-api-next",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["declined_journey"]["state"] == "cancelled"
    assert body["declined_journey"]["terminal_reason"] == "USER_REJECTED"
    assert body["replacement"]["journey"]["attempt_id"] == "attempt-decline-api-next"
    assert body["replacement"]["journey"]["space_id"] != rejected_space
    rejected = next(item for item in body["replacement"]["recommendation"]["assessments"] if item["space_id"] == rejected_space)
    assert "USER_DECLINED_TANDEM" in rejected["reason_codes"]


def test_session_aware_count_persists_through_occupancy_and_recovers_on_departure() -> None:
    client = TestClient(create_app())
    headers = {"X-Session-ID": "session-occupied-availability"}
    initial = client.get("/api/v2/parking-lots/lot-school", headers=headers).json()
    created = client.post("/api/v2/journeys/recommendations", json=_journey_payload(suffix="occupied-availability")).json()["journey"]
    confirmed = client.post(
        f"/api/v2/journeys/{created['journey_id']}/confirm",
        json={"schema_version": "2.0.0", "expected_version": created["version"], "idempotency_key": "confirm-occupied-availability", "accepted": True},
    ).json()
    reserved_count = client.get("/api/v2/parking-lots/lot-school", headers=headers).json()
    assert reserved_count["available_spaces"] == initial["available_spaces"] - 1
    navigating = client.post(
        f"/api/v2/journeys/{created['journey_id']}/start-navigation",
        json={"schema_version": "2.0.0", "expected_version": confirmed["version"], "idempotency_key": "navigate-occupied-availability"},
    ).json()
    navigating_count = client.get("/api/v2/parking-lots/lot-school", headers=headers).json()
    assert navigating_count["available_spaces"] == initial["available_spaces"] - 1
    occupied = client.post(
        f"/api/v2/journeys/{created['journey_id']}/occupy",
        json={"schema_version": "2.0.0", "expected_version": navigating["version"], "idempotency_key": "occupy-availability"},
    ).json()
    during = client.get("/api/v2/parking-lots/lot-school", headers=headers).json()
    assert during["available_spaces"] == initial["available_spaces"] - 1
    departed = client.post(
        f"/api/v2/journeys/{created['journey_id']}/depart",
        json={"schema_version": "2.0.0", "expected_version": occupied["version"], "idempotency_key": "depart-availability"},
    )
    assert departed.status_code == 200
    restored = client.get("/api/v2/parking-lots/lot-school", headers=headers).json()
    assert restored["available_spaces"] == initial["available_spaces"]


def test_external_occupancy_and_replacement_remove_two_distinct_spaces() -> None:
    client = TestClient(create_app())
    headers = {"X-Session-ID": "session-external-count"}
    initial = client.get("/api/v2/parking-lots/lot-school", headers=headers).json()
    created = client.post("/api/v2/journeys/recommendations", json=_journey_payload(suffix="external-count")).json()["journey"]
    replaced = client.post(
        f"/api/v2/journeys/{created['journey_id']}/report-external-occupancy",
        json={
            "schema_version": "2.0.0",
            "expected_version": created["version"],
            "idempotency_key": "external-count",
            "replacement_journey_id": "journey-external-count-new",
            "replacement_attempt_id": "attempt-external-count-new",
            "replacement_request_id": "request-external-count-new",
        },
    )
    assert replaced.status_code == 200
    body = replaced.json()
    assert body["replacement"]["journey"]["space_id"] != created["space_id"]
    projected = client.get("/api/v2/parking-lots/lot-school", headers=headers).json()
    assert projected["available_spaces"] == initial["available_spaces"] - 2


def test_online_rule_can_recommend_but_pending_algorithm_cannot_be_selected() -> None:
    client = TestClient(create_app())
    driver = {
        "schema_version": "2.0.0",
        "request_id": "request-api",
        "idempotency_key": "idem-api",
        "session_id": "session-api",
        "parking_lot_id": "lot-school",
        "entrance_node_id": "entry",
        "requires_charging": False,
        "requested_at": "2026-08-12T09:01:00Z",
        "expected_departure_at": None,
    }
    response = client.post("/api/v2/recommendations", json={"schema_version": "2.0.0", "algorithm_id": "online-rule-v2", "driver": driver})
    assert response.status_code == 200
    assert response.json()["claim_status"] == "not_created_m2"
    assert response.json()["data_source"]["mode"] == "synthetic"
    pending = client.post("/api/v2/recommendations", json={"schema_version": "2.0.0", "algorithm_id": "simulated-annealing", "driver": driver})
    assert pending.status_code == 409
    assert pending.json()["code"] == "CAPABILITY_CONFLICT"
    assert "pending" in pending.json()["message"]
    assert pending.json()["request_id"] == pending.headers["X-Request-ID"]


def test_real_mode_fails_closed_without_synthetic_fallback() -> None:
    client = TestClient(create_app(data_mode=DataMode.REAL))
    assert client.get("/api/v2/health").json()["data_mode"] == "real"
    response = client.get("/api/v2/parking-lots")
    assert response.status_code == 503
    assert response.json()["code"] == "DATA_SOURCE_UNAVAILABLE"
    assert "not configured" in response.json()["message"]
    assert client.get("/api/v2/parking-lots/lot-school").status_code == 503
    assert client.get("/api/v2/parking-lots/lot-school/layout").status_code == 503
    assert client.get("/api/v2/discovery-area").status_code == 503
    recommendation = client.post(
        "/api/v2/recommendations",
        json={
            "schema_version": "2.0.0",
            "algorithm_id": "online-rule-v2",
            "driver": {
                "schema_version": "2.0.0",
                "request_id": "request-real",
                "idempotency_key": "idem-real",
                "session_id": "session-real",
                "parking_lot_id": "lot-school",
                "entrance_node_id": "entry",
                "requires_charging": False,
                "requested_at": "2026-08-12T09:01:00Z",
                "expected_departure_at": None,
            },
        },
    )
    assert recommendation.status_code == 503
    assert recommendation.json()["code"] == "DATA_SOURCE_UNAVAILABLE"
