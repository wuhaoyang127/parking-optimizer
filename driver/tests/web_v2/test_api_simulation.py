from __future__ import annotations

from fastapi.testclient import TestClient

from api_fixtures import create_app, _journey_payload


def test_unable_to_park_reassigns_without_marking_physical_occupancy() -> None:
    client = TestClient(create_app())
    headers = {"X-Session-ID": "session-reassign-api"}
    created = client.post("/api/v2/journeys/recommendations", headers=headers, json=_journey_payload(suffix="reassign-api")).json()
    original_space = created["journey"]["space_id"]
    confirmed = client.post(
        "/api/v2/journeys/journey-reassign-api/confirm",
        headers=headers,
        json={"schema_version": "2.0.0", "expected_version": created["journey"]["version"], "idempotency_key": "confirm-reassign-api", "accepted": True},
    ).json()
    navigating = client.post(
        "/api/v2/journeys/journey-reassign-api/start-navigation",
        headers=headers,
        json={"schema_version": "2.0.0", "expected_version": confirmed["version"], "idempotency_key": "navigate-reassign-api"},
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
    snapshot = client.get("/api/v2/parking-lots/lot-school", headers=headers).json()
    assert snapshot["available_spaces"] >= 1


def test_journey_api_replaces_attempt_after_external_occupancy() -> None:
    client = TestClient(create_app())
    created = client.post("/api/v2/journeys/recommendations", json=_journey_payload(suffix="external-api")).json()
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
    command_types = ("ARRIVAL", "SOFT_HELD", "SESSION_RESERVED", "NAVIGATING", "OCCUPIED", "DEPARTURE_REQUEST")
    commands = [
        {
            "simulation_time_s": index,
            "priority": index,
            "sequence_hint": index,
            "event_type": event_type,
            "vehicle_id": "vehicle-api-sim",
            "payload": {"space_id": "B-02"} if event_type == "SOFT_HELD" else {},
        }
        for index, event_type in enumerate(command_types, start=1)
    ]
    request = {"schema_version": "2.0.0", "parking_lot_id": "lot-school", "seed": 2026, "wall_time_origin": "2026-08-13T00:00:00Z", "commands": commands}
    response = client.post("/api/v2/simulations/run", json=request)
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["relocation_count"] == 1
    assert body["summary"]["failure_count"] == 0
    replay = client.post(
        "/api/v2/simulations/replay",
        json={"schema_version": "2.0.0", "parking_lot_id": "lot-school", "seed": 2026, "wall_time_origin": "2026-08-13T00:00:00Z", "events": body["events"]},
    )
    assert replay.status_code == 200
    assert replay.json() == body["summary"]
    tampered = body["events"]
    tampered[0]["after_sha256"] = "0" * 64
    rejected = client.post(
        "/api/v2/simulations/replay",
        json={"schema_version": "2.0.0", "parking_lot_id": "lot-school", "seed": 2026, "wall_time_origin": "2026-08-13T00:00:00Z", "events": tampered},
    )
    assert rejected.status_code == 409
    assert rejected.json()["code"] == "CAPABILITY_CONFLICT"
