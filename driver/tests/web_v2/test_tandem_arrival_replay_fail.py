from __future__ import annotations
from typing import Any
from fastapi.testclient import TestClient
from parking_opt.api.app import create_app
from parking_opt.api.facility_scenarios import PublicFacilityDataSource
from parking_opt.api.models import SpaceStatus
from parking_opt.api.routing import RouteNotFoundError
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
def _payload(navigating: dict[str, Any], state: dict[str, Any], key: str) -> dict[str, Any]:
    return {"schema_version": "1.0.0", "expected_version": navigating["version"], "expected_state_version": state["state_version"], "idempotency_key": key}
def test_tandem_arrival_fails_closed_for_stale_or_busy_buffer(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    app = _app()
    client = TestClient(app)
    headers = {"X-Session-ID": "session-tandem-arrival-failure"}
    navigating, state = _navigate_deep_tandem(client, headers, "arrival-failure")
    path = f"/api/v2/journeys/{navigating['journey_id']}/tandem-arrival-replay"
    stale = client.post(
        path,
        headers=headers,
        json={
            **_payload(navigating, state, "arrival-stale"),
            "expected_state_version": "state-stale",
        },
    )
    assert stale.status_code == 409
    source = app.state.public_source
    assert isinstance(source, PublicFacilityDataSource)
    original_get_state = source.get_state
    def get_state_with_busy_buffer(parking_lot_id: str, *, session_id: str):  # type: ignore[no-untyped-def]
        current = original_get_state(parking_lot_id, session_id=session_id)
        return current.model_copy(update={
            "buffers": tuple(
                item.model_copy(update={"status": SpaceStatus.OCCUPIED, "reason_codes": ("BUFFER_OCCUPIED",)})
                for item in current.buffers
            )
        })
    monkeypatch.setattr(source, "get_state", get_state_with_busy_buffer)
    busy = client.post(
        path,
        headers=headers,
        json=_payload(navigating, state, "arrival-busy"),
    )
    assert busy.status_code == 409
    current = client.get("/api/v2/driver-session/current-trip", headers=headers).json()
    assert current["journey"]["state"] == "navigating"
    assert current["tandem_arrival_replay"] is None
    assert app.state.session_store.tandem_coordination(navigating["journey_id"]) is None
def test_tandem_arrival_rejects_another_driver_session() -> None:
    app = _app()
    client = TestClient(app)
    headers = {"X-Session-ID": "session-tandem-arrival-owner"}
    navigating, state = _navigate_deep_tandem(client, headers, "arrival-session")
    response = client.post(
        f"/api/v2/journeys/{navigating['journey_id']}/tandem-arrival-replay",
        headers={"X-Session-ID": "session-tandem-arrival-other"},
        json=_payload(navigating, state, "arrival-wrong-session"),
    )
    assert response.status_code == 409
    current = client.get("/api/v2/driver-session/current-trip", headers=headers).json()
    assert current["journey"]["state"] == "navigating"
    assert current["tandem_arrival_replay"] is None
    assert app.state.session_store.tandem_coordination(navigating["journey_id"]) is None
def test_tandem_arrival_fails_closed_when_buffer_route_is_unreachable(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    app = _app()
    client = TestClient(app)
    headers = {"X-Session-ID": "session-tandem-arrival-route"}
    navigating, state = _navigate_deep_tandem(client, headers, "arrival-route")
    route_service = app.state.route_service
    original_route = route_service.route
    def route_without_buffer(
        layout,
        costs,
        *,
        from_node_id: str,
        to_node_id: str,
    ):  # type: ignore[no-untyped-def]
        if "buffer-access" in from_node_id or "buffer-access" in to_node_id:
            raise RouteNotFoundError("arrival buffer route is unavailable")
        return original_route(
            layout,
            costs,
            from_node_id=from_node_id,
            to_node_id=to_node_id,
        )
    monkeypatch.setattr(route_service, "route", route_without_buffer)
    response = client.post(
        f"/api/v2/journeys/{navigating['journey_id']}/tandem-arrival-replay",
        headers=headers,
        json=_payload(navigating, state, "arrival-unreachable"),
    )
    assert response.status_code == 503
    assert "arrival buffer route" in response.json()["message"]
    current = client.get("/api/v2/driver-session/current-trip", headers=headers).json()
    assert current["journey"]["state"] == "navigating"
    assert current["tandem_arrival_replay"] is None
    assert app.state.session_store.tandem_coordination(navigating["journey_id"]) is None
