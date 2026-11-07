from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from parking_opt.api.app import create_app
from parking_opt.api.sources import ScenarioProfile


def _app(*, enabled: bool = True):  # type: ignore[no-untyped-def]
    return create_app(
        scenario_profile=ScenarioProfile.PUBLIC,
        driver_tandem_departure_replay_enabled=enabled,
    )


def _advance_to_tandem(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    lot_id = "lot-school"
    for index in range(3):
        context = client.get(
            f"/api/v2/parking-lots/{lot_id}/driver-context", headers=headers
        ).json()
        state = client.get(
            f"/api/v2/parking-lots/{lot_id}/facility-state", headers=headers
        ).json()
        response = client.post(
            f"/api/v2/parking-lots/{lot_id}/driver-demo-profile/advance",
            headers=headers,
            json={
                "schema_version": "1.0.0",
                "expected_profile_id": context["demo_profile"]["profile_id"],
                "expected_state_version": state["state_version"],
                "idempotency_key": f"advance-tandem-{index}",
            },
        )
        assert response.status_code == 200
    context = client.get(
        f"/api/v2/parking-lots/{lot_id}/driver-context", headers=headers
    ).json()
    assert context["demo_profile"]["profile_id"] == "tandem-focus"
    return context


def _occupy_deep_tandem(
    client: TestClient, headers: dict[str, str], suffix: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    context = _advance_to_tandem(client, headers)
    entrance = context["entrances"][0]
    created_response = client.post(
        "/api/v2/journeys/recommendations",
        headers=headers,
        json={
            "schema_version": "2.0.0",
            "namespace": "driver",
            "scenario_id": context["scenario_id"],
            "journey_id": f"journey-{suffix}",
            "attempt_id": f"attempt-{suffix}",
            "algorithm_id": "online-rule-v2",
            "idempotency_key": f"recommend-{suffix}",
            "driver": {
                "schema_version": "2.0.0",
                "request_id": f"request-{suffix}",
                "idempotency_key": f"driver-{suffix}",
                "session_id": headers["X-Session-ID"],
                "parking_lot_id": "lot-school",
                "entrance_node_id": entrance["node_id"],
                "requires_charging": False,
                "requested_at": "2026-08-21T09:00:00Z",
                "expected_departure_at": None,
            },
        },
    )
    assert created_response.status_code == 200
    created = created_response.json()["journey"]
    selected = next(
        item for item in context["spaces"] if item["space_id"] == created["space_id"]
    )
    assert selected["depth"] > 1
    confirmed = client.post(
        f"/api/v2/journeys/{created['journey_id']}/confirm",
        headers=headers,
        json={
            "schema_version": "2.0.0",
            "expected_version": created["version"],
            "idempotency_key": f"confirm-{suffix}",
            "accepted": True,
        },
    ).json()
    navigating = client.post(
        f"/api/v2/journeys/{created['journey_id']}/start-navigation",
        headers=headers,
        json={
            "schema_version": "2.0.0",
            "expected_version": confirmed["version"],
            "idempotency_key": f"navigate-{suffix}",
        },
    ).json()
    occupied_response = client.post(
        f"/api/v2/journeys/{created['journey_id']}/occupy",
        headers=headers,
        json={
            "schema_version": "2.0.0",
            "expected_version": navigating["version"],
            "idempotency_key": f"occupy-{suffix}",
        },
    )
    assert occupied_response.status_code == 200
    occupied = occupied_response.json()
    state = client.get(
        "/api/v2/parking-lots/lot-school/facility-state", headers=headers
    ).json()
    return occupied, state


def _replay_payload(occupied: dict[str, Any], state: dict[str, Any], key: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "expected_version": occupied["version"],
        "expected_state_version": state["state_version"],
        "idempotency_key": key,
    }


def test_disabled_tandem_replay_keeps_legacy_departure_available() -> None:
    client = TestClient(_app(enabled=False))
    headers = {"X-Session-ID": "session-tandem-disabled"}
    occupied, state = _occupy_deep_tandem(client, headers, "tandem-disabled")
    replay = client.post(
        f"/api/v2/journeys/{occupied['journey_id']}/tandem-departure-replay",
        headers=headers,
        json=_replay_payload(occupied, state, "depart-tandem-disabled"),
    )
    assert replay.status_code == 409
    current = client.get(
        "/api/v2/driver-session/current-trip", headers=headers
    ).json()
    assert current["journey"]["state"] == "occupied"
    assert current["tandem_departure_replay_enabled"] is False
    departed = client.post(
        f"/api/v2/journeys/{occupied['journey_id']}/depart",
        headers=headers,
        json={
            "schema_version": "2.0.0",
            "expected_version": occupied["version"],
            "idempotency_key": "legacy-depart-disabled",
        },
    )
    assert departed.status_code == 200
    assert departed.json()["state"] == "departed"


def test_tandem_departure_replay_rolls_back_every_store_projection_on_failure(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    app = _app()
    client = TestClient(app, raise_server_exceptions=False)
    headers = {"X-Session-ID": "session-tandem-rollback"}
    occupied, state = _occupy_deep_tandem(client, headers, "tandem-rollback")
    store = app.state.session_store

    def fail_profile_advance(*, journey_id: str, profile_count: int) -> int:
        del journey_id, profile_count
        raise RuntimeError("injected terminal projection failure")

    monkeypatch.setattr(
        store, "advance_driver_demo_profile_after_terminal", fail_profile_advance
    )
    response = client.post(
        f"/api/v2/journeys/{occupied['journey_id']}/tandem-departure-replay",
        headers=headers,
        json=_replay_payload(occupied, state, "depart-tandem-rollback"),
    )
    assert response.status_code == 500
    current = client.get(
        "/api/v2/driver-session/current-trip", headers=headers
    ).json()
    assert current["journey"]["state"] == "occupied"
    assert current["journey"]["version"] == occupied["version"]
    assert current["tandem_departure_replay"] is None
    assert store.tandem_departure_replay(occupied["journey_id"]) is None
    context = client.get(
        "/api/v2/parking-lots/lot-school/driver-context", headers=headers
    ).json()
    assert context["demo_profile"]["profile_id"] == "tandem-focus"
