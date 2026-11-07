from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from parking_opt.api.app import create_app
from parking_opt.api.facility_scenarios import PublicFacilityDataSource
from parking_opt.api.models import DataMode, DriverRequest
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


def test_profiles_are_fixed_session_scoped_and_change_real_recommendation_inputs() -> None:
    app = _public_app()
    source = app.state.public_source
    store = app.state.session_store
    recommender = app.state.recommender
    assert isinstance(source, PublicFacilityDataSource)

    for lot_id in ("lot-commercial", "lot-school", "lot-hospital", "lot-transport-hub"):
        session_id = f"matrix-{lot_id}"
        selections: list[str | None] = []
        for index in range(source.driver_demo_profile_count(lot_id)):
            profile = source.get_driver_demo_profile(lot_id, session_id=session_id)
            bundle = source.get_driver_bundle(lot_id, session_id=session_id)
            state = source.get_state(lot_id, session_id=session_id)
            assert profile.ordinal == index + 1
            assert state.demo_profile == profile
            assert bundle.parking_lot.available_spaces == sum(
                item.assignable for item in state.spaces
            )
            driver = DriverRequest(
                request_id=f"request-{lot_id}-{index}",
                idempotency_key=f"driver-{lot_id}-{index}",
                session_id=session_id,
                parking_lot_id=lot_id,
                entrance_node_id=bundle.layout.entrance_node_ids[0],
                requested_at=datetime(2026, 8, 21, 9, 0, tzinfo=UTC),
            )
            recommendation = recommender.recommend(
                driver,
                bundle.layout,
                bundle.cost_snapshot,
                bundle.parking_lot.data_source,
            )
            selections.append(recommendation.recommended_space_id)
            if profile.profile_id == "charging-tight":
                charging = recommender.recommend(
                    driver.model_copy(
                        update={
                            "request_id": f"charge-{lot_id}",
                            "idempotency_key": f"charge-driver-{lot_id}",
                            "requires_charging": True,
                        }
                    ),
                    bundle.layout,
                    bundle.cost_snapshot,
                    bundle.parking_lot.data_source,
                )
                assert charging.solver_status == "no_feasible_space"
            if profile.profile_id == "tandem-focus":
                tandem_ids = {
                    space_id
                    for group in bundle.layout.tandem_groups
                    for space_id in group.space_ids_near_to_deep
                }
                assert recommendation.recommended_space_id in tandem_ids
                selected = next(
                    item
                    for item in bundle.layout.spaces
                    if item.space_id == recommendation.recommended_space_id
                )
                assert selected.depth > 1
                near_ids = {
                    group.space_ids_near_to_deep[0]
                    for group in bundle.layout.tandem_groups
                }
                assert all(
                    item.status.value == "unavailable"
                    and "DEMO_TANDEM_OUTER_RESERVED" in item.assignability_reasons
                    for item in bundle.layout.spaces
                    if item.space_id in near_ids
                )
            if index + 1 < source.driver_demo_profile_count(lot_id):
                store.advance_driver_demo_profile(
                    session_id=session_id,
                    parking_lot_id=lot_id,
                    expected_profile_index=index,
                    expected_state_version=state.state_version,
                    current_state_version=state.state_version,
                    profile_count=source.driver_demo_profile_count(lot_id),
                    idempotency_key=f"advance-{lot_id}-{index}",
                )
        assert len(set(selections)) >= 3
        assert (
            source.get_driver_demo_profile(lot_id, session_id=f"other-{lot_id}").profile_id
            == "normal-flow"
        )


def test_manual_profile_advance_is_atomic_idempotent_and_rejects_active_journey() -> None:
    client = TestClient(_public_app())
    lot_id = "lot-commercial"
    headers = {"X-Session-ID": "session-profile-api"}
    context = client.get(
        f"/api/v2/parking-lots/{lot_id}/driver-context", headers=headers
    ).json()
    state = client.get(
        f"/api/v2/parking-lots/{lot_id}/facility-state", headers=headers
    ).json()
    payload = _advance_payload(context["demo_profile"], state, "advance-profile-api")
    path = f"/api/v2/parking-lots/{lot_id}/driver-demo-profile/advance"
    advanced = client.post(path, headers=headers, json=payload)
    assert advanced.status_code == 200
    assert advanced.json()["demo_profile"]["profile_id"] == "peak-remote"
    assert advanced.json()["facility_state"]["demo_profile"] == advanced.json()["demo_profile"]
    assert advanced.json()["parking_lot"]["available_spaces"] == sum(
        item["assignable"] for item in advanced.json()["facility_state"]["spaces"]
    )
    replay = client.post(path, headers=headers, json=payload)
    assert replay.status_code == 200
    assert replay.json()["demo_profile"] == advanced.json()["demo_profile"]

    stale = client.post(
        path,
        headers=headers,
        json={**payload, "idempotency_key": "advance-profile-stale"},
    )
    assert stale.status_code == 409

    current = client.get(
        f"/api/v2/parking-lots/{lot_id}/driver-context", headers=headers
    ).json()
    recommendation = client.post(
        "/api/v2/journeys/recommendations",
        headers=headers,
        json=_recommendation_payload(current, "profile-api"),
    )
    assert recommendation.status_code == 200
    current_state = client.get(
        f"/api/v2/parking-lots/{lot_id}/facility-state", headers=headers
    ).json()
    denied = client.post(
        path,
        headers=headers,
        json=_advance_payload(
            current["demo_profile"], current_state, "advance-profile-active"
        ),
    )
    assert denied.status_code == 409
    assert "active journey" in denied.json()["message"]


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
