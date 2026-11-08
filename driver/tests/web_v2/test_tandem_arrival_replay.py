from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from parking_opt.api.app import create_app
from parking_opt.api.sources import ScenarioProfile


def _app(*, enabled: bool = True):  # type: ignore[no-untyped-def]
    return create_app(
        scenario_profile=ScenarioProfile.PUBLIC,
        driver_tandem_arrival_replay_enabled=enabled,
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
                "idempotency_key": f"arrival-advance-{index}",
            },
        )
        assert response.status_code == 200
    context = client.get(
        f"/api/v2/parking-lots/{lot_id}/driver-context", headers=headers
    ).json()
    assert context["demo_profile"]["profile_id"] == "tandem-focus"
    return context


def _navigate_deep_tandem(
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
                "requested_at": "2026-08-31T09:00:00Z",
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
    initial_state = client.get(
        "/api/v2/parking-lots/lot-school/facility-state", headers=headers
    ).json()
    blocker_before = next(
        item for item in initial_state["spaces"] if item["space_id"] == "P-21"
    )
    assert blocker_before["observed_status"] == "unavailable"
    assert "DEMO_TANDEM_OUTER_RESERVED" in blocker_before["reason_codes"]
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
    navigating_response = client.post(
        f"/api/v2/journeys/{created['journey_id']}/start-navigation",
        headers=headers,
        json={
            "schema_version": "2.0.0",
            "expected_version": confirmed["version"],
            "idempotency_key": f"navigate-{suffix}",
        },
    )
    assert navigating_response.status_code == 200
    navigating = navigating_response.json()
    state = client.get(
        "/api/v2/parking-lots/lot-school/facility-state", headers=headers
    ).json()
    return navigating, state


def _payload(
    navigating: dict[str, Any], state: dict[str, Any], key: str
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "expected_version": navigating["version"],
        "expected_state_version": state["state_version"],
        "idempotency_key": key,
    }


def _space(state: dict[str, Any], space_id: str) -> dict[str, Any]:
    return next(item for item in state["spaces"] if item["space_id"] == space_id)


def test_tandem_arrival_is_authoritative_idempotent_and_reused_for_departure() -> None:
    app = _app()
    client = TestClient(app)
    headers = {"X-Session-ID": "session-tandem-arrival"}
    navigating, state = _navigate_deep_tandem(client, headers, "tandem-arrival")
    path = f"/api/v2/journeys/{navigating['journey_id']}/tandem-arrival-replay"
    payload = _payload(navigating, state, "arrive-tandem")
    response = client.post(path, headers=headers, json=payload)
    assert response.status_code == 200
    replay = response.json()
    assert replay["final_journey"]["state"] == "occupied"
    assert [item["action"] for item in replay["steps"]] == [
        "relocate_to_buffer",
        "direct_entry",
        "restore_original",
    ]
    assert replay["steps"][0]["from_location"]["location_id"] == "P-21"
    assert replay["steps"][0]["to_location"]["location_id"] == "BUF-01"
    assert replay["steps"][1]["to_location"]["location_id"] == navigating["space_id"]
    assert replay["steps"][2]["to_location"]["location_id"] == "P-21"
    assert _space(replay["before_facility_state"], "P-21")["observed_status"] == "occupied"
    assert _space(replay["before_facility_state"], navigating["space_id"])[
        "claim_status"
    ] == "navigating"
    assert _space(replay["after_facility_state"], "P-21")["observed_status"] == "occupied"
    assert _space(replay["after_facility_state"], navigating["space_id"])[
        "observed_status"
    ] == "occupied"
    assert replay["after_facility_state"]["buffers"][0]["status"] == "available"
    assert replay["before_sha256"] != replay["after_sha256"]
    repeated = client.post(path, headers=headers, json=payload)
    assert repeated.status_code == 200
    assert repeated.json() == replay
    current = client.get("/api/v2/driver-session/current-trip", headers=headers).json()
    assert current["tandem_arrival_replay"] == replay
    assert current["tandem_arrival_replay_enabled"] is True
    live_state = client.get(
        "/api/v2/parking-lots/lot-school/facility-state", headers=headers
    ).json()
    assert _space(live_state, "P-21")["observed_status"] == "occupied"
    assert _space(live_state, navigating["space_id"])["observed_status"] == "occupied"
    departure = client.post(
        f"/api/v2/journeys/{navigating['journey_id']}/tandem-departure-replay",
        headers=headers,
        json={
            "schema_version": "1.0.0",
            "expected_version": replay["final_journey"]["version"],
            "expected_state_version": live_state["state_version"],
            "idempotency_key": "depart-after-arrival",
        },
    )
    assert departure.status_code == 200
    departed = departure.json()
    assert departed["blocker_vehicle_ids"] == replay["blocker_vehicle_ids"]
    assert departed["buffer_ids"] == replay["buffer_ids"]
    assert app.state.session_store.tandem_coordination(navigating["journey_id"]) is None
