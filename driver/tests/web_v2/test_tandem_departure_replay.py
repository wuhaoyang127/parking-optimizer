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


def test_tandem_departure_replay_is_authoritative_idempotent_and_recoverable() -> None:
    client = TestClient(_app())
    headers = {"X-Session-ID": "session-tandem-replay"}
    occupied, state = _occupy_deep_tandem(client, headers, "tandem-replay")
    path = f"/api/v2/journeys/{occupied['journey_id']}/tandem-departure-replay"
    payload = _replay_payload(occupied, state, "depart-tandem-replay")
    response = client.post(path, headers=headers, json=payload)
    assert response.status_code == 200
    replay = response.json()
    assert replay["final_journey"]["state"] == "departed"
    assert replay["final_journey"]["terminal_reason"] == "NORMAL_DEPARTURE"
    assert [item["action"] for item in replay["steps"]] == [
        "relocate_to_buffer",
        "direct_exit",
        "restore_original",
    ]
    assert replay["steps"][0]["from_location"]["location_id"] == "P-21"
    assert replay["steps"][0]["to_location"]["location_id"] == "BUF-01"
    assert replay["steps"][1]["from_location"]["location_id"] == occupied["space_id"]
    assert replay["steps"][2]["to_location"]["location_id"] == "P-21"
    assert all(
        item["route"]["layout_version"] == replay["layout_version"]
        and item["route"]["cost_version"] == replay["cost_version"]
        for item in replay["steps"]
    )
    assert replay["before_sha256"] != replay["after_sha256"]
    assert replay["facility_state"]["state_version"] == replay["state_version"]
    assert replay["facility_state"]["scenario_version"] == replay["scenario_version"]
    assert replay["facility_state"]["demo_profile"]["profile_id"] == "tandem-focus"
    repeated = client.post(path, headers=headers, json=payload)
    assert repeated.status_code == 200
    assert repeated.json() == replay
    conflicting = client.post(
        path,
        headers=headers,
        json={**payload, "expected_state_version": "state-other"},
    )
    assert conflicting.status_code == 409
    recovered = client.get(
        "/api/v2/driver-session/current-trip", headers=headers
    ).json()
    assert recovered["tandem_departure_replay"] == replay
    assert (
        recovered["tandem_departure_replay"]["facility_state"]["state_version"]
        == replay["state_version"]
    )
    assert recovered["tandem_departure_replay_enabled"] is True
    next_context = client.get(
        "/api/v2/parking-lots/lot-school/driver-context", headers=headers
    ).json()
    assert next_context["demo_profile"]["profile_id"] == "normal-flow"


def test_tandem_departure_replay_rejects_stale_state_without_departing() -> None:
    client = TestClient(_app())
    headers = {"X-Session-ID": "session-tandem-stale"}
    occupied, state = _occupy_deep_tandem(client, headers, "tandem-stale")
    wrong_session = client.post(
        f"/api/v2/journeys/{occupied['journey_id']}/tandem-departure-replay",
        headers={"X-Session-ID": "session-other"},
        json=_replay_payload(occupied, state, "depart-tandem-wrong-session"),
    )
    assert wrong_session.status_code == 409
    response = client.post(
        f"/api/v2/journeys/{occupied['journey_id']}/tandem-departure-replay",
        headers=headers,
        json={
            **_replay_payload(occupied, state, "depart-tandem-stale"),
            "expected_state_version": "state-stale",
        },
    )
    assert response.status_code == 409
    current = client.get(
        "/api/v2/driver-session/current-trip", headers=headers
    ).json()
    assert current["journey"]["state"] == "occupied"
    assert current["tandem_departure_replay"] is None
