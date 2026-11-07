from __future__ import annotations

import json
import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from parking_opt.api.app import create_app as _create_app
from parking_opt.api.models import DataMode
from parking_opt.api.sessions import SessionNamespace
from parking_opt.api.sources import ScenarioProfile

REPO_ROOT = Path(__file__).resolve().parents[2]


def create_app(*, data_mode: DataMode = DataMode.SYNTHETIC) -> FastAPI:
    profile = ScenarioProfile.LEGACY if data_mode is DataMode.SYNTHETIC else None
    return _create_app(data_mode=data_mode, scenario_profile=profile)


def _journey_payload(*, suffix: str, namespace: str = "driver") -> dict[str, object]:
    return {
        "schema_version": "2.0.0",
        "namespace": namespace,
        "scenario_id": "school-demo",
        "journey_id": f"journey-{suffix}",
        "attempt_id": f"attempt-{suffix}",
        "algorithm_id": "online-rule-v2",
        "idempotency_key": f"recommend-{suffix}",
        "driver": {
            "schema_version": "2.0.0",
            "request_id": f"request-{suffix}",
            "idempotency_key": f"driver-{suffix}",
            "session_id": f"session-{suffix}",
            "parking_lot_id": "lot-school",
            "entrance_node_id": "entry",
            "requires_charging": False,
            "requested_at": "2026-08-13T09:00:00Z",
            "expected_departure_at": None,
        },
    }


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
    initial = next(
        item for item in initial_response.json() if item["parking_lot_id"] == "lot-school"
    )

    created = client.post(
        "/api/v2/journeys/recommendations",
        json=_journey_payload(suffix="availability-api"),
    ).json()
    assert created["journey"]["session_id"] == "session-availability-api"
    held = next(
        item
        for item in client.get("/api/v2/parking-lots", headers=session_headers).json()
        if item["parking_lot_id"] == "lot-school"
    )
    other = next(
        item
        for item in client.get("/api/v2/parking-lots", headers=other_headers).json()
        if item["parking_lot_id"] == "lot-school"
    )
    single = client.get("/api/v2/parking-lots/lot-school", headers=session_headers)
    assert held["available_spaces"] == initial["available_spaces"] - 1
    assert single.json()["available_spaces"] == held["available_spaces"]
    assert single.headers["Cache-Control"] == "no-store"
    assert other["available_spaces"] == initial["available_spaces"]

    cancelled = client.post(
        "/api/v2/journeys/journey-availability-api/cancel",
        json={
            "schema_version": "2.0.0",
            "expected_version": created["journey"]["version"],
            "idempotency_key": "cancel-availability-api",
        },
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
    invalid_single = client.get(
        "/api/v2/parking-lots/lot-school", headers={"X-Session-ID": "bad id"}
    )
    assert invalid_single.status_code == 422
    assert invalid_single.json()["code"] == "CONTRACT_VALIDATION_FAILED"


def test_driver_context_exposes_server_derived_scenario_and_entrance() -> None:
    client = TestClient(create_app())
    response = client.get(
        "/api/v2/parking-lots/lot-school/driver-context",
        headers={"X-Session-ID": "session-driver-context"},
    )
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
    response = client.get(
        "/api/v2/driver-session/current-journey",
        headers={"X-Session-ID": f"session-{suffix}"},
    )
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
    response = client.get(
        "/api/v2/driver-session/current-journey",
        headers={"X-Session-ID": "session-without-journey"},
    )
    assert response.status_code == 200
    assert response.json()["journey"] is None
    assert response.json()["recommendation"] is None
    assert response.json()["driver"] is None


def test_driver_mutation_rejects_a_mismatched_session_header() -> None:
    client = TestClient(create_app())
    payload = _journey_payload(suffix="header-match")
    mismatched = client.post(
        "/api/v2/journeys/recommendations",
        json=payload,
        headers={"X-Session-ID": "another-driver-session"},
    )
    assert mismatched.status_code == 409
    created = client.post(
        "/api/v2/journeys/recommendations",
        json=payload,
        headers={"X-Session-ID": "session-header-match"},
    ).json()["journey"]
    cancelled = client.post(
        f"/api/v2/journeys/{created['journey_id']}/cancel",
        headers={"X-Session-ID": "another-driver-session"},
        json={
            "schema_version": "2.0.0",
            "expected_version": created["version"],
            "idempotency_key": "cancel-header-mismatch",
        },
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
    rejected = next(
        item
        for item in body["replacement"]["recommendation"]["assessments"]
        if item["space_id"] == rejected_space
    )
    assert "USER_DECLINED_TANDEM" in rejected["reason_codes"]


def test_session_aware_count_persists_through_occupancy_and_recovers_on_departure() -> None:
    client = TestClient(create_app())
    headers = {"X-Session-ID": "session-occupied-availability"}
    initial = client.get("/api/v2/parking-lots/lot-school", headers=headers).json()
    created = client.post(
        "/api/v2/journeys/recommendations",
        json=_journey_payload(suffix="occupied-availability"),
    ).json()["journey"]
    confirmed = client.post(
        f"/api/v2/journeys/{created['journey_id']}/confirm",
        json={
            "schema_version": "2.0.0",
            "expected_version": created["version"],
            "idempotency_key": "confirm-occupied-availability",
            "accepted": True,
        },
    ).json()
    reserved_count = client.get(
        "/api/v2/parking-lots/lot-school", headers=headers
    ).json()
    assert reserved_count["available_spaces"] == initial["available_spaces"] - 1
    navigating = client.post(
        f"/api/v2/journeys/{created['journey_id']}/start-navigation",
        json={
            "schema_version": "2.0.0",
            "expected_version": confirmed["version"],
            "idempotency_key": "navigate-occupied-availability",
        },
    ).json()
    navigating_count = client.get(
        "/api/v2/parking-lots/lot-school", headers=headers
    ).json()
    assert navigating_count["available_spaces"] == initial["available_spaces"] - 1
    occupied = client.post(
        f"/api/v2/journeys/{created['journey_id']}/occupy",
        json={
            "schema_version": "2.0.0",
            "expected_version": navigating["version"],
            "idempotency_key": "occupy-availability",
        },
    ).json()
    during = client.get("/api/v2/parking-lots/lot-school", headers=headers).json()
    assert during["available_spaces"] == initial["available_spaces"] - 1

    departed = client.post(
        f"/api/v2/journeys/{created['journey_id']}/depart",
        json={
            "schema_version": "2.0.0",
            "expected_version": occupied["version"],
            "idempotency_key": "depart-availability",
        },
    )
    assert departed.status_code == 200
    restored = client.get("/api/v2/parking-lots/lot-school", headers=headers).json()
    assert restored["available_spaces"] == initial["available_spaces"]


def test_external_occupancy_and_replacement_remove_two_distinct_spaces() -> None:
    client = TestClient(create_app())
    headers = {"X-Session-ID": "session-external-count"}
    initial = client.get("/api/v2/parking-lots/lot-school", headers=headers).json()
    created = client.post(
        "/api/v2/journeys/recommendations",
        json=_journey_payload(suffix="external-count"),
    ).json()["journey"]
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
    response = client.post(
        "/api/v2/recommendations",
        json={"schema_version": "2.0.0", "algorithm_id": "online-rule-v2", "driver": driver},
    )
    assert response.status_code == 200
    assert response.json()["claim_status"] == "not_created_m2"
    assert response.json()["data_source"]["mode"] == "synthetic"
    pending = client.post(
        "/api/v2/recommendations",
        json={"schema_version": "2.0.0", "algorithm_id": "simulated-annealing", "driver": driver},
    )
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
        json={
            "schema_version": "2.0.0",
            "expected_version": body["journey"]["version"],
            "idempotency_key": "confirm-api-lifecycle",
            "accepted": True,
        },
    )
    assert confirm.status_code == 200
    assert confirm.json()["state"] == "session_reserved"
    original_expiry = confirm.json()["expires_at"]

    navigation = client.post(
        "/api/v2/journeys/journey-api-lifecycle/start-navigation",
        json={
            "schema_version": "2.0.0",
            "expected_version": confirm.json()["version"],
            "idempotency_key": "navigate-api-lifecycle",
        },
    )
    assert navigation.status_code == 200
    assert navigation.json()["state"] == "navigating"
    assert navigation.json()["expires_at"] == original_expiry

    occupied = client.post(
        "/api/v2/journeys/journey-api-lifecycle/occupy",
        json={
            "schema_version": "2.0.0",
            "expected_version": navigation.json()["version"],
            "idempotency_key": "occupy-api-lifecycle",
        },
    )
    assert occupied.status_code == 200
    assert occupied.json()["state"] == "occupied"
    assert occupied.json()["expires_at"] is None

    departed = client.post(
        "/api/v2/journeys/journey-api-lifecycle/depart",
        json={
            "schema_version": "2.0.0",
            "expected_version": occupied.json()["version"],
            "idempotency_key": "depart-api-lifecycle",
        },
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
    created = client.post(
        "/api/v2/journeys/recommendations",
        json=_journey_payload(suffix="alternative"),
    )
    assert created.status_code == 200
    body = created.json()
    alternative = body["recommendation"]["alternative_space_ids"][0]
    command = {
        "schema_version": "2.0.0",
        "expected_version": body["journey"]["version"],
        "idempotency_key": "select-alternative-api",
        "space_id": alternative,
    }
    switched = client.post(
        "/api/v2/journeys/journey-alternative/select-alternative", json=command
    )
    replay = client.post(
        "/api/v2/journeys/journey-alternative/select-alternative", json=command
    )
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
        update={
            "cost_version": "cost-api-too-slow",
            "edge_travel_time_s": {
                key: 300.0 for key in bundle.cost_snapshot.edge_travel_time_s
            },
        }
    )
    source._by_lot["lot-school"] = bundle.model_copy(  # type: ignore[attr-defined]
        update={"cost_snapshot": slow}
    )
    created = client.post(
        "/api/v2/journeys/recommendations",
        json=_journey_payload(suffix="waiting"),
    )
    assert created.status_code == 200
    waiting = created.json()["journey"]
    assert waiting["state"] == "waiting"
    queried = client.get("/api/v2/journeys/journey-waiting")
    assert queried.json()["version"] == waiting["version"]
    retry = client.post(
        "/api/v2/journeys/journey-waiting/retry-recommendation",
        json={
            "schema_version": "2.0.0",
            "expected_version": waiting["version"],
            "idempotency_key": "retry-waiting-api",
        },
    )
    assert retry.status_code == 200
    assert retry.json()["journey"]["state"] == "waiting"
    assert retry.json()["journey"]["version"] == waiting["version"] + 1


def test_journey_api_replans_navigation_from_visible_channel_load() -> None:
    client = TestClient(create_app())
    created = client.post(
        "/api/v2/journeys/recommendations",
        json=_journey_payload(suffix="replan-api"),
    ).json()
    confirmed = client.post(
        "/api/v2/journeys/journey-replan-api/confirm",
        json={
            "schema_version": "2.0.0",
            "expected_version": created["journey"]["version"],
            "idempotency_key": "confirm-replan-api",
            "accepted": True,
        },
    ).json()
    navigating = client.post(
        "/api/v2/journeys/journey-replan-api/start-navigation",
        json={
            "schema_version": "2.0.0",
            "expected_version": confirmed["version"],
            "idempotency_key": "navigate-replan-api",
        },
    ).json()
    layout = client.get("/api/v2/parking-lots/lot-school/layout").json()
    load = {
        zone["channel_zone_id"]: 0 for zone in layout["channel_zones"]
    }
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
    assert set(body["decision"]["cost_snapshot"]["edge_travel_time_s"]) == {
        edge["edge_id"] for edge in layout["edges"]
    }
    trip = client.get(
        "/api/v2/driver-session/current-trip",
        headers={"X-Session-ID": "session-replan-api"},
    )
    assert trip.status_code == 200
    assert trip.headers["Cache-Control"] == "no-store"
    assert trip.json()["journey"]["state"] == "navigating"
    assert trip.json()["current_route"] == body["decision"]["route"]
    assert trip.json()["last_replan"]["status"] == "success"
    assert trip.json()["current_node_id"] == "entry"


def test_driver_demo_replan_derives_inputs_and_exposes_action_capabilities() -> None:
    client = TestClient(create_app())
    headers = {"X-Session-ID": "session-driver-demo-api"}
    created = client.post(
        "/api/v2/journeys/recommendations",
        headers=headers,
        json=_journey_payload(suffix="driver-demo-api"),
    ).json()
    confirmed = client.post(
        "/api/v2/journeys/journey-driver-demo-api/confirm",
        headers=headers,
        json={
            "schema_version": "2.0.0",
            "expected_version": created["journey"]["version"],
            "idempotency_key": "confirm-driver-demo-api",
            "accepted": True,
        },
    ).json()
    navigating = client.post(
        "/api/v2/journeys/journey-driver-demo-api/start-navigation",
        headers=headers,
        json={
            "schema_version": "2.0.0",
            "expected_version": confirmed["version"],
            "idempotency_key": "navigate-driver-demo-api",
        },
    ).json()
    assert {
        "driver_demo_replan",
        "report_external_occupancy",
        "reassign",
        "occupy",
    }.issubset(navigating["legal_operations"])
    payload = {
        "schema_version": "2.0.0",
        "expected_version": navigating["version"],
        "idempotency_key": "driver-demo-api",
        "action": "simulate_deviation",
    }
    first = client.post(
        "/api/v2/journeys/journey-driver-demo-api/driver-demo-replan",
        headers=headers,
        json=payload,
    )
    replay = client.post(
        "/api/v2/journeys/journey-driver-demo-api/driver-demo-replan",
        headers=headers,
        json=payload,
    )
    assert first.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["decision"]["trigger"] == "deviation"
    mismatch = client.post(
        "/api/v2/journeys/journey-driver-demo-api/driver-demo-replan",
        headers=headers,
        json={**payload, "action": "simulate_cost_update"},
    )
    assert mismatch.status_code == 409
    version_mismatch = client.post(
        "/api/v2/journeys/journey-driver-demo-api/driver-demo-replan",
        headers=headers,
        json={
            **payload,
            "expected_version": first.json()["journey"]["version"],
        },
    )
    assert version_mismatch.status_code == 409


def test_demo_actions_fail_closed_outside_synthetic_mode() -> None:
    app = create_app()
    client = TestClient(app)
    headers = {"X-Session-ID": "session-demo-guard"}
    created = client.post(
        "/api/v2/journeys/recommendations",
        headers=headers,
        json=_journey_payload(suffix="demo-guard"),
    ).json()
    confirmed = client.post(
        "/api/v2/journeys/journey-demo-guard/confirm",
        headers=headers,
        json={
            "schema_version": "2.0.0",
            "expected_version": created["journey"]["version"],
            "idempotency_key": "confirm-demo-guard",
            "accepted": True,
        },
    ).json()
    navigating = client.post(
        "/api/v2/journeys/journey-demo-guard/start-navigation",
        headers=headers,
        json={
            "schema_version": "2.0.0",
            "expected_version": confirmed["version"],
            "idempotency_key": "navigate-demo-guard",
        },
    ).json()
    app.state.data_mode = DataMode.REAL
    denied = client.post(
        "/api/v2/journeys/journey-demo-guard/driver-demo-replan",
        headers=headers,
        json={
            "schema_version": "2.0.0",
            "expected_version": navigating["version"],
            "idempotency_key": "demo-guard",
            "action": "simulate_deviation",
        },
    )
    assert denied.status_code == 409
    assert "synthetic" in denied.json()["message"]


def test_reset_demo_fails_closed_outside_synthetic_mode_without_side_effects() -> None:
    app = create_app()
    client = TestClient(app)
    headers = {"X-Session-ID": "session-reset-demo-guard"}
    created = client.post(
        "/api/v2/journeys/recommendations",
        headers=headers,
        json=_journey_payload(suffix="reset-demo-guard"),
    ).json()
    confirmed = client.post(
        "/api/v2/journeys/journey-reset-demo-guard/confirm",
        headers=headers,
        json={
            "schema_version": "2.0.0",
            "expected_version": created["journey"]["version"],
            "idempotency_key": "confirm-reset-demo-guard",
            "accepted": True,
        },
    ).json()
    navigating = client.post(
        "/api/v2/journeys/journey-reset-demo-guard/start-navigation",
        headers=headers,
        json={
            "schema_version": "2.0.0",
            "expected_version": confirmed["version"],
            "idempotency_key": "navigate-reset-demo-guard",
        },
    ).json()
    occupied = client.post(
        "/api/v2/journeys/journey-reset-demo-guard/occupy",
        headers=headers,
        json={
            "schema_version": "2.0.0",
            "expected_version": navigating["version"],
            "idempotency_key": "occupy-reset-demo-guard",
        },
    ).json()
    store = app.state.session_store
    before_journey = store.get_journey("journey-reset-demo-guard")
    assert before_journey is not None
    before_events = store.events()
    before_lot = client.get("/api/v2/parking-lots/lot-school", headers=headers).json()

    app.state.data_mode = DataMode.REAL
    denied = client.post(
        "/api/v2/journeys/journey-reset-demo-guard/reset-demo",
        headers=headers,
        json={
            "schema_version": "2.0.0",
            "expected_version": occupied["version"],
            "idempotency_key": "reset-demo-guard",
        },
    )

    assert denied.status_code == 409
    assert "synthetic" in denied.json()["message"]
    after_journey = store.get_journey("journey-reset-demo-guard")
    assert after_journey == before_journey
    assert after_journey is not None
    assert after_journey.state.value == "occupied"
    assert store.events() == before_events
    after_lot = client.get("/api/v2/parking-lots/lot-school", headers=headers).json()
    assert after_lot["available_spaces"] == before_lot["available_spaces"]


def test_current_trip_snapshot_is_atomic_during_concurrent_lifecycle_change() -> None:
    app = create_app()
    client = TestClient(app)
    headers = {"X-Session-ID": "session-trip-atomic"}
    created = client.post(
        "/api/v2/journeys/recommendations",
        headers=headers,
        json=_journey_payload(suffix="trip-atomic"),
    ).json()
    confirmed = client.post(
        "/api/v2/journeys/journey-trip-atomic/confirm",
        headers=headers,
        json={
            "schema_version": "2.0.0",
            "expected_version": created["journey"]["version"],
            "idempotency_key": "confirm-trip-atomic",
            "accepted": True,
        },
    ).json()
    navigating = client.post(
        "/api/v2/journeys/journey-trip-atomic/start-navigation",
        headers=headers,
        json={
            "schema_version": "2.0.0",
            "expected_version": confirmed["version"],
            "idempotency_key": "navigate-trip-atomic",
        },
    ).json()
    started = threading.Event()
    finished = threading.Event()
    failures: list[BaseException] = []
    original_recover = app.state.replan_service.recover_navigation
    worker: threading.Thread | None = None

    def occupy_concurrently() -> None:
        try:
            started.set()
            app.state.session_store.occupy(
                journey_id="journey-trip-atomic",
                expected_version=navigating["version"],
                idempotency_key="occupy-trip-atomic-concurrent",
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)
        finally:
            finished.set()

    def interleaved_recovery(journey_id: str):  # type: ignore[no-untyped-def]
        nonlocal worker
        worker = threading.Thread(target=occupy_concurrently)
        worker.start()
        assert started.wait(timeout=1)
        assert not finished.wait(timeout=0.05)
        return original_recover(journey_id)

    app.state.replan_service.recover_navigation = interleaved_recovery
    try:
        response = client.get(
            "/api/v2/driver-session/current-trip", headers=headers
        )
    finally:
        app.state.replan_service.recover_navigation = original_recover
    assert worker is not None
    worker.join(timeout=1)
    assert not worker.is_alive()
    assert failures == []
    assert response.status_code == 200
    body = response.json()
    assert body["journey"]["state"] == "navigating"
    assert all(item["event_type"] != "OCCUPIED" for item in body["recent_events"])
    assert app.state.session_store.get_journey(
        "journey-trip-atomic"
    ).state.value == "occupied"


def test_all_p3_driver_commands_reject_a_mismatched_session_header() -> None:
    client = TestClient(create_app())
    headers = {"X-Session-ID": "session-header-p3"}
    wrong_headers = {"X-Session-ID": "another-session"}
    created = client.post(
        "/api/v2/journeys/recommendations",
        headers=headers,
        json=_journey_payload(suffix="header-p3"),
    ).json()
    confirmed = client.post(
        "/api/v2/journeys/journey-header-p3/confirm",
        headers=headers,
        json={
            "schema_version": "2.0.0",
            "expected_version": created["journey"]["version"],
            "idempotency_key": "confirm-header-p3",
            "accepted": True,
        },
    ).json()
    bad_start = client.post(
        "/api/v2/journeys/journey-header-p3/start-navigation",
        headers=wrong_headers,
        json={
            "schema_version": "2.0.0",
            "expected_version": confirmed["version"],
            "idempotency_key": "bad-start-header-p3",
        },
    )
    assert bad_start.status_code == 409
    navigating = client.post(
        "/api/v2/journeys/journey-header-p3/start-navigation",
        headers=headers,
        json={
            "schema_version": "2.0.0",
            "expected_version": confirmed["version"],
            "idempotency_key": "navigate-header-p3",
        },
    ).json()
    layout = client.get("/api/v2/parking-lots/lot-school/layout").json()
    command = {
        "schema_version": "2.0.0",
        "expected_version": navigating["version"],
        "idempotency_key": "bad-command-header-p3",
    }
    replan = {
        **command,
        "current_node_id": "entry",
        "trigger": "deviation",
        "channel_load": {
            "schema_version": "2.0.0",
            "parking_lot_id": "lot-school",
            "layout_version": layout["layout_version"],
            "observed_at": navigating["updated_at"],
            "active_units_by_zone": {
                item["channel_zone_id"]: 0 for item in layout["channel_zones"]
            },
        },
    }
    external = {
        **command,
        "replacement_journey_id": "journey-header-p3-external",
        "replacement_attempt_id": "attempt-header-p3-external",
        "replacement_request_id": "request-header-p3-external",
    }
    reassign = {
        **command,
        "reason": "unable_to_park",
        "replacement_journey_id": "journey-header-p3-reassign",
        "replacement_attempt_id": "attempt-header-p3-reassign",
        "replacement_request_id": "request-header-p3-reassign",
    }
    for endpoint, payload in (
        ("replan", replan),
        ("report-external-occupancy", external),
        ("occupy", command),
        ("reassign", reassign),
    ):
        response = client.post(
            f"/api/v2/journeys/journey-header-p3/{endpoint}",
            headers=wrong_headers,
            json=payload,
        )
        assert response.status_code == 409, endpoint
    occupied = client.post(
        "/api/v2/journeys/journey-header-p3/occupy",
        headers=headers,
        json={**command, "idempotency_key": "occupy-header-p3"},
    ).json()
    for endpoint in ("depart", "reset-demo"):
        response = client.post(
            f"/api/v2/journeys/journey-header-p3/{endpoint}",
            headers=wrong_headers,
            json={
                "schema_version": "2.0.0",
                "expected_version": occupied["version"],
                "idempotency_key": f"bad-{endpoint}-header-p3",
            },
        )
        assert response.status_code == 409, endpoint


def test_replan_stale_or_non_navigating_state_returns_contract_conflict() -> None:
    client = TestClient(create_app())
    created = client.post(
        "/api/v2/journeys/recommendations",
        json=_journey_payload(suffix="replan-conflict"),
    ).json()
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
            "active_units_by_zone": {
                item["channel_zone_id"]: 0 for item in layout["channel_zones"]
            },
        },
    }
    state_conflict = client.post(
        "/api/v2/journeys/journey-replan-conflict/replan", json=payload
    )
    assert state_conflict.status_code == 409
    assert state_conflict.json()["code"] == "ILLEGALTRANSITIONERROR"
    confirmed = client.post(
        "/api/v2/journeys/journey-replan-conflict/confirm",
        json={
            "schema_version": "2.0.0",
            "expected_version": created["journey"]["version"],
            "idempotency_key": "confirm-replan-conflict",
            "accepted": True,
        },
    ).json()
    navigating = client.post(
        "/api/v2/journeys/journey-replan-conflict/start-navigation",
        json={
            "schema_version": "2.0.0",
            "expected_version": confirmed["version"],
            "idempotency_key": "navigate-replan-conflict",
        },
    ).json()
    stale = client.post(
        "/api/v2/journeys/journey-replan-conflict/replan",
        json={**payload, "idempotency_key": "stale-replan-conflict"},
    )
    assert navigating["version"] > payload["expected_version"]
    assert stale.status_code == 409
    assert stale.json()["code"] == "VERSIONCONFLICTERROR"
    future_load = {
        **payload,
        "expected_version": navigating["version"],
        "idempotency_key": "future-load-replan-conflict",
        "channel_load": {
            **payload["channel_load"],
            "observed_at": "2099-01-01T00:00:00Z",
        },
    }
    future = client.post(
        "/api/v2/journeys/journey-replan-conflict/replan", json=future_load
    )
    assert future.status_code == 409
    assert future.json()["code"] == "ILLEGALTRANSITIONERROR"


def test_demo_reset_is_audited_as_departed() -> None:
    client = TestClient(create_app())
    headers = {"X-Session-ID": "session-reset-api"}
    created = client.post(
        "/api/v2/journeys/recommendations",
        headers=headers,
        json=_journey_payload(suffix="reset-api"),
    ).json()
    confirmed = client.post(
        "/api/v2/journeys/journey-reset-api/confirm",
        headers=headers,
        json={
            "schema_version": "2.0.0",
            "expected_version": created["journey"]["version"],
            "idempotency_key": "confirm-reset-api",
            "accepted": True,
        },
    ).json()
    navigating = client.post(
        "/api/v2/journeys/journey-reset-api/start-navigation",
        headers=headers,
        json={
            "schema_version": "2.0.0",
            "expected_version": confirmed["version"],
            "idempotency_key": "navigate-reset-api",
        },
    ).json()
    occupied = client.post(
        "/api/v2/journeys/journey-reset-api/occupy",
        headers=headers,
        json={
            "schema_version": "2.0.0",
            "expected_version": navigating["version"],
            "idempotency_key": "occupy-reset-api",
        },
    ).json()
    reset = client.post(
        "/api/v2/journeys/journey-reset-api/reset-demo",
        headers=headers,
        json={
            "schema_version": "2.0.0",
            "expected_version": occupied["version"],
            "idempotency_key": "reset-api",
        },
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


def test_unable_to_park_reassigns_without_marking_physical_occupancy() -> None:
    client = TestClient(create_app())
    headers = {"X-Session-ID": "session-reassign-api"}
    created = client.post(
        "/api/v2/journeys/recommendations",
        headers=headers,
        json=_journey_payload(suffix="reassign-api"),
    ).json()
    original_space = created["journey"]["space_id"]
    confirmed = client.post(
        "/api/v2/journeys/journey-reassign-api/confirm",
        headers=headers,
        json={
            "schema_version": "2.0.0",
            "expected_version": created["journey"]["version"],
            "idempotency_key": "confirm-reassign-api",
            "accepted": True,
        },
    ).json()
    navigating = client.post(
        "/api/v2/journeys/journey-reassign-api/start-navigation",
        headers=headers,
        json={
            "schema_version": "2.0.0",
            "expected_version": confirmed["version"],
            "idempotency_key": "navigate-reassign-api",
        },
    ).json()
    response = client.post(
        "/api/v2/journeys/journey-reassign-api/reassign",
        headers=headers,
        json={
            "schema_version": "2.0.0",
            "expected_version": navigating["version"],
            "idempotency_key": "reassign-api",
            "reason": "unable_to_park",
            "replacement_journey_id": "journey-reassign-api-new",
            "replacement_attempt_id": "attempt-reassign-api-new",
            "replacement_request_id": "request-reassign-api-new",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ended_journey"]["terminal_reason"] == "USER_UNABLE_TO_PARK"
    assert body["replacement"]["journey"]["space_id"] != original_space
    snapshot = client.get(
        "/api/v2/parking-lots/lot-school", headers=headers
    ).json()
    assert snapshot["available_spaces"] >= 1


def test_journey_api_replaces_attempt_after_external_occupancy() -> None:
    client = TestClient(create_app())
    created = client.post(
        "/api/v2/journeys/recommendations",
        json=_journey_payload(suffix="external-api"),
    ).json()
    original_space = created["journey"]["space_id"]
    response = client.post(
        "/api/v2/journeys/journey-external-api/report-external-occupancy",
        json={
            "schema_version": "2.0.0",
            "expected_version": created["journey"]["version"],
            "idempotency_key": "external-api",
            "replacement_journey_id": "journey-external-api-new",
            "replacement_attempt_id": "attempt-external-api-new",
            "replacement_request_id": "request-external-api-new",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["failed_journey"]["state"] == "failed"
    assert body["failed_journey"]["terminal_reason"] == "EXTERNAL_SPACE_OCCUPIED"
    assert body["replacement"]["journey"]["journey_id"] == "journey-external-api-new"
    assert body["replacement"]["journey"]["space_id"] != original_space


def test_simulation_api_runs_and_replays_tandem_departure() -> None:
    client = TestClient(create_app())
    command_types = (
        "ARRIVAL",
        "SOFT_HELD",
        "SESSION_RESERVED",
        "NAVIGATING",
        "OCCUPIED",
        "DEPARTURE_REQUEST",
    )
    commands = []
    for index, event_type in enumerate(command_types, start=1):
        commands.append(
            {
                "simulation_time_s": index,
                "priority": index,
                "sequence_hint": index,
                "event_type": event_type,
                "vehicle_id": "vehicle-api-sim",
                "payload": {"space_id": "B-02"} if event_type == "SOFT_HELD" else {},
            }
        )
    request = {
        "schema_version": "2.0.0",
        "parking_lot_id": "lot-school",
        "seed": 2026,
        "wall_time_origin": "2026-08-13T00:00:00Z",
        "commands": commands,
    }
    response = client.post("/api/v2/simulations/run", json=request)
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["relocation_count"] == 1
    assert body["summary"]["failure_count"] == 0
    replay = client.post(
        "/api/v2/simulations/replay",
        json={
            "schema_version": "2.0.0",
            "parking_lot_id": "lot-school",
            "seed": 2026,
            "wall_time_origin": "2026-08-13T00:00:00Z",
            "events": body["events"],
        },
    )
    assert replay.status_code == 200
    assert replay.json() == body["summary"]

    tampered = body["events"]
    tampered[0]["after_sha256"] = "0" * 64
    rejected = client.post(
        "/api/v2/simulations/replay",
        json={
            "schema_version": "2.0.0",
            "parking_lot_id": "lot-school",
            "seed": 2026,
            "wall_time_origin": "2026-08-13T00:00:00Z",
            "events": tampered,
        },
    )
    assert rejected.status_code == 409
    assert rejected.json()["code"] == "CAPABILITY_CONFLICT"
