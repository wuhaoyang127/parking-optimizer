from __future__ import annotations

from dataclasses import replace
from typing import Any

from fastapi.testclient import TestClient

from parking_opt.api.app import create_app
from parking_opt.api.facility_scenarios import PublicFacilityDataSource
from parking_opt.api.models import FacilityClaimStatus, SpaceStatus
from parking_opt.api.routing import RouteNotFoundError
from parking_opt.api.services.tandem_arrival import build_tandem_arrival_draft
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

    def get_state_with_busy_buffer(
        parking_lot_id: str, *, session_id: str
    ):  # type: ignore[no-untyped-def]
        current = original_get_state(parking_lot_id, session_id=session_id)
        return current.model_copy(
            update={
                "buffers": tuple(
                    item.model_copy(
                        update={
                            "status": SpaceStatus.OCCUPIED,
                            "reason_codes": ("BUFFER_OCCUPIED",),
                        }
                    )
                    for item in current.buffers
                )
            }
        )

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


def test_tandem_arrival_draft_orders_multiple_blockers_and_buffers() -> None:
    app = _app()
    client = TestClient(app)
    headers = {"X-Session-ID": "session-tandem-arrival-multi"}
    navigating, _state_payload = _navigate_deep_tandem(
        client, headers, "arrival-multi"
    )
    source = app.state.public_source
    assert isinstance(source, PublicFacilityDataSource)
    layout = source.get_layout("lot-school")
    state = source.get_state("lot-school", session_id=headers["X-Session-ID"])
    group = next(item for item in layout.tandem_groups if "P-22" in item.space_ids_near_to_deep)
    p22 = next(item for item in layout.spaces if item.space_id == "P-22")
    p23 = p22.model_copy(update={"space_id": "P-23", "depth": 3})
    buffer1 = next(item for item in layout.buffers if item.buffer_id == group.buffer_ids[0])
    buffer2 = buffer1.model_copy(update={"buffer_id": "BUF-02"})
    multi_group = group.model_copy(
        update={
            "space_ids_near_to_deep": ("P-21", "P-22", "P-23"),
            "buffer_ids": (buffer1.buffer_id, buffer2.buffer_id),
        }
    )
    multi_layout = layout.model_copy(
        update={
            "spaces": (*layout.spaces, p23),
            "tandem_groups": tuple(
                multi_group if item.stack_group_id == group.stack_group_id else item
                for item in layout.tandem_groups
            ),
            "buffers": (*layout.buffers, buffer2),
        }
    )
    p22_state = next(item for item in state.spaces if item.space_id == "P-22")
    p22_reserved = p22_state.model_copy(
        update={
            "observed_status": SpaceStatus.UNAVAILABLE,
            "claim_status": FacilityClaimStatus.NONE,
            "effective_status": SpaceStatus.UNAVAILABLE,
            "assignable": False,
            "reason_codes": ("DEMO_TANDEM_OUTER_RESERVED",),
        }
    )
    p23_state = p22_state.model_copy(update={"space_id": "P-23"})
    buffer2_state = state.buffers[0].model_copy(update={"buffer_id": "BUF-02"})
    multi_state = state.model_copy(
        update={
            "spaces": (
                *(
                    p22_reserved if item.space_id == "P-22" else item
                    for item in state.spaces
                ),
                p23_state,
            ),
            "buffers": (*state.buffers, buffer2_state),
        }
    ).require_layout(multi_layout)
    journey_record = app.state.session_store.get_journey(navigating["journey_id"])
    assert journey_record is not None
    multi_journey = replace(journey_record, space_id="P-23")
    draft = build_tandem_arrival_draft(
        journey=multi_journey,
        expected_state_version=multi_state.state_version,
        profile=source.get_driver_demo_profile(
            "lot-school", session_id=headers["X-Session-ID"]
        ),
        layout=multi_layout,
        state=multi_state,
        bundle=source.get_driver_bundle(
            "lot-school", session_id=headers["X-Session-ID"]
        ),
        route_service=app.state.route_service,
        created_at=app.state.session_store.current_wall_time(),
    )
    assert draft.blocker_space_ids == ("P-21", "P-22")
    assert draft.buffer_ids == (buffer1.buffer_id, buffer2.buffer_id)
    assert [item.action for item in draft.steps] == [
        "relocate_to_buffer",
        "relocate_to_buffer",
        "direct_entry",
        "restore_original",
        "restore_original",
    ]
    assert [item.actor_id for item in draft.steps[:2]] == [
        "blocker-P-21",
        "blocker-P-22",
    ]
    assert [item.actor_id for item in draft.steps[-2:]] == [
        "blocker-P-22",
        "blocker-P-21",
    ]


def test_disabled_tandem_arrival_keeps_ordinary_occupy_available() -> None:
    client = TestClient(_app(enabled=False))
    headers = {"X-Session-ID": "session-tandem-arrival-disabled"}
    navigating, state = _navigate_deep_tandem(client, headers, "arrival-disabled")
    replay = client.post(
        f"/api/v2/journeys/{navigating['journey_id']}/tandem-arrival-replay",
        headers=headers,
        json=_payload(navigating, state, "arrival-disabled"),
    )
    assert replay.status_code == 409
    current = client.get("/api/v2/driver-session/current-trip", headers=headers).json()
    assert current["tandem_arrival_replay_enabled"] is False
    occupied = client.post(
        f"/api/v2/journeys/{navigating['journey_id']}/occupy",
        headers=headers,
        json={
            "schema_version": "2.0.0",
            "expected_version": navigating["version"],
            "idempotency_key": "ordinary-occupy-disabled",
        },
    )
    assert occupied.status_code == 200
    assert occupied.json()["state"] == "occupied"


def test_tandem_arrival_rolls_back_journey_coordination_replay_and_idempotency(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    app = _app()
    client = TestClient(app, raise_server_exceptions=False)
    headers = {"X-Session-ID": "session-tandem-arrival-rollback"}
    navigating, state = _navigate_deep_tandem(client, headers, "arrival-rollback")
    store = app.state.session_store
    original_remember = store.remember_tandem_arrival_replay

    def fail_remember(**kwargs) -> None:  # type: ignore[no-untyped-def]
        original_remember(**kwargs)
        raise RuntimeError("injected tandem arrival persistence failure")

    monkeypatch.setattr(store, "remember_tandem_arrival_replay", fail_remember)
    payload = _payload(navigating, state, "arrival-rollback")
    response = client.post(
        f"/api/v2/journeys/{navigating['journey_id']}/tandem-arrival-replay",
        headers=headers,
        json=payload,
    )
    assert response.status_code == 500
    current = client.get("/api/v2/driver-session/current-trip", headers=headers).json()
    assert current["journey"]["state"] == "navigating"
    assert current["journey"]["version"] == navigating["version"]
    assert current["tandem_arrival_replay"] is None
    assert store.tandem_coordination(navigating["journey_id"]) is None
    assert store.tandem_arrival_replay(navigating["journey_id"]) is None

    monkeypatch.setattr(store, "remember_tandem_arrival_replay", original_remember)
    repeated = client.post(
        f"/api/v2/journeys/{navigating['journey_id']}/tandem-arrival-replay",
        headers=headers,
        json=payload,
    )
    assert repeated.status_code == 200
