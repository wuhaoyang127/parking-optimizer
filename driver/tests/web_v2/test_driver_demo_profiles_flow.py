from __future__ import annotations

from fastapi.testclient import TestClient

from parking_opt.api.app import create_app
from parking_opt.api.models import DataMode
from parking_opt.api.sources import ScenarioProfile


def _public_app():  # type: ignore[no-untyped-def]
    return create_app(scenario_profile=ScenarioProfile.PUBLIC)


def _recommendation_payload(context: dict[str, object], suffix: str) -> dict[str, object]:
    entrances = context["entrances"]
    assert isinstance(entrances, list)
    entrance = entrances[0]
    assert isinstance(entrance, dict)
    return {
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
            "session_id": f"session-{suffix}",
            "parking_lot_id": context["parking_lot_id"],
            "entrance_node_id": entrance["node_id"],
            "requires_charging": False,
            "requested_at": "2026-08-21T09:00:00Z",
            "expected_departure_at": None,
        },
    }


def _advance_payload(profile: dict[str, object], state: dict[str, object], key: str):
    return {
        "schema_version": "1.0.0",
        "expected_profile_id": profile["profile_id"],
        "expected_state_version": state["state_version"],
        "idempotency_key": key,
    }


def test_normal_departure_advances_once_for_the_next_driver_run() -> None:
    client = TestClient(_public_app())
    lot_id = "lot-school"
    suffix = "terminal-profile"
    headers = {"X-Session-ID": f"session-{suffix}"}
    context = client.get(
        f"/api/v2/parking-lots/{lot_id}/driver-context", headers=headers
    ).json()
    assert context["demo_profile"]["profile_id"] == "normal-flow"
    created = client.post(
        "/api/v2/journeys/recommendations",
        headers=headers,
        json=_recommendation_payload(context, suffix),
    ).json()["journey"]
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
    occupied = client.post(
        f"/api/v2/journeys/{created['journey_id']}/occupy",
        headers=headers,
        json={
            "schema_version": "2.0.0",
            "expected_version": navigating["version"],
            "idempotency_key": f"occupy-{suffix}",
        },
    ).json()
    depart_payload = {
        "schema_version": "2.0.0",
        "expected_version": occupied["version"],
        "idempotency_key": f"depart-{suffix}",
    }
    departed = client.post(
        f"/api/v2/journeys/{created['journey_id']}/depart",
        headers=headers,
        json=depart_payload,
    )
    assert departed.status_code == 200
    next_context = client.get(
        f"/api/v2/parking-lots/{lot_id}/driver-context", headers=headers
    ).json()
    assert next_context["demo_profile"]["profile_id"] == "peak-remote"
    replay = client.post(
        f"/api/v2/journeys/{created['journey_id']}/depart",
        headers=headers,
        json=depart_payload,
    )
    assert replay.status_code == 200
    assert (
        client.get(
            f"/api/v2/parking-lots/{lot_id}/driver-context", headers=headers
        ).json()["demo_profile"]["profile_id"]
        == "peak-remote"
    )


def test_demo_profile_command_fails_closed_for_real_mode() -> None:
    client = TestClient(create_app(data_mode=DataMode.REAL, scenario_profile=None))
    response = client.post(
        "/api/v2/parking-lots/lot-school/driver-demo-profile/advance",
        headers={"X-Session-ID": "real-profile-session"},
        json={
            "schema_version": "1.0.0",
            "expected_profile_id": "normal-flow",
            "expected_state_version": "state-real",
            "idempotency_key": "advance-real-profile",
        },
    )
    assert response.status_code == 409
    assert "synthetic public source" in response.json()["message"]


def test_disabled_profile_rotation_keeps_the_default_and_rejects_advance() -> None:
    client = TestClient(
        create_app(
            scenario_profile=ScenarioProfile.PUBLIC,
            driver_demo_profiles_enabled=False,
        )
    )
    headers = {"X-Session-ID": "disabled-profile-session"}
    context = client.get(
        "/api/v2/parking-lots/lot-school/driver-context", headers=headers
    ).json()
    state = client.get(
        "/api/v2/parking-lots/lot-school/facility-state", headers=headers
    ).json()
    assert context["demo_profile"]["profile_id"] == "normal-flow"
    response = client.post(
        "/api/v2/parking-lots/lot-school/driver-demo-profile/advance",
        headers=headers,
        json=_advance_payload(
            context["demo_profile"], state, "advance-disabled-profile"
        ),
    )
    assert response.status_code == 409
    assert "synthetic public source" in response.json()["message"]
