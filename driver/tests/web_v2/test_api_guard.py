from __future__ import annotations

import threading

from fastapi.testclient import TestClient

from parking_opt.api.models import DataMode
from api_fixtures import create_app, _journey_payload


def test_reset_demo_fails_closed_outside_synthetic_mode_without_side_effects() -> None:
    app = create_app()
    client = TestClient(app)
    headers = {"X-Session-ID": "session-reset-demo-guard"}
    created = client.post("/api/v2/journeys/recommendations", headers=headers, json=_journey_payload(suffix="reset-demo-guard")).json()
    confirmed = client.post(
        "/api/v2/journeys/journey-reset-demo-guard/confirm",
        headers=headers,
        json={"schema_version": "2.0.0", "expected_version": created["journey"]["version"], "idempotency_key": "confirm-reset-demo-guard", "accepted": True},
    ).json()
    navigating = client.post(
        "/api/v2/journeys/journey-reset-demo-guard/start-navigation",
        headers=headers,
        json={"schema_version": "2.0.0", "expected_version": confirmed["version"], "idempotency_key": "navigate-reset-demo-guard"},
    ).json()
    occupied = client.post(
        "/api/v2/journeys/journey-reset-demo-guard/occupy",
        headers=headers,
        json={"schema_version": "2.0.0", "expected_version": navigating["version"], "idempotency_key": "occupy-reset-demo-guard"},
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
        json={"schema_version": "2.0.0", "expected_version": occupied["version"], "idempotency_key": "reset-demo-guard"},
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
    created = client.post("/api/v2/journeys/recommendations", headers=headers, json=_journey_payload(suffix="trip-atomic")).json()
    confirmed = client.post(
        "/api/v2/journeys/journey-trip-atomic/confirm",
        headers=headers,
        json={"schema_version": "2.0.0", "expected_version": created["journey"]["version"], "idempotency_key": "confirm-trip-atomic", "accepted": True},
    ).json()
    navigating = client.post(
        "/api/v2/journeys/journey-trip-atomic/start-navigation",
        headers=headers,
        json={"schema_version": "2.0.0", "expected_version": confirmed["version"], "idempotency_key": "navigate-trip-atomic"},
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
        response = client.get("/api/v2/driver-session/current-trip", headers=headers)
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
    assert app.state.session_store.get_journey("journey-trip-atomic").state.value == "occupied"
