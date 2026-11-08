from __future__ import annotations
from dataclasses import replace
from typing import Any
from fastapi.testclient import TestClient
from parking_opt.api.app import create_app
from parking_opt.api.facility_scenarios import PublicFacilityDataSource
from parking_opt.api.models import FacilityClaimStatus, SpaceStatus
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
