from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from parking_opt.api.app import create_app
from parking_opt.api.models import (
    ChannelZone,
    Coordinate,
    FacilityBounds,
    FacilityBuffer,
    FacilityBufferState,
    FacilityClaimStatus,
    FacilityEdge,
    FacilityEntrance,
    FacilityExit,
    FacilityFloor,
    FacilityInterFloorConnection,
    FacilityNode,
    FacilityObservationSource,
    FacilityProvenance,
    FacilityRectangle,
    FacilitySourceKind,
    FacilitySourceStatus,
    FacilitySpace,
    FacilitySpaceState,
    FacilityTandemGroup,
    FacilityZone,
    HealthStatus,
    ParkingFacilityLayout,
    ParkingFacilityStateSnapshot,
    Route,
    RouteInstruction,
    RoutePreview,
    RoutePreviewRequest,
    SpaceStatus,
)
from parking_opt.api.scenarios import built_in_scenarios
from parking_opt.api.sources import ScenarioProfile, SyntheticParkingDataSource

REPO_ROOT = Path(__file__).resolve().parents[2]
OBSERVED_AT = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)


def _coordinate(x_m: float, y_m: float) -> Coordinate:
    return Coordinate(x_m=x_m, y_m=y_m)


def _facility_layout() -> ParkingFacilityLayout:
    bounds = FacilityBounds(min_x_m=0, min_y_m=0, max_x_m=40, max_y_m=30)
    return ParkingFacilityLayout(
        parking_lot_id="lot-school",
        layout_version="facility-school-v1",
        provenance=FacilityProvenance(
            source_kind=FacilitySourceKind.SYNTHETIC,
            source_name="m4-contract-test",
            source_revision="fixture-v1",
            published_at=OBSERVED_AT,
        ),
        coordinate_origin_note="South-west corner, x east, y north.",
        bounds=bounds,
        default_floor_id="floor-1",
        floors=(
            FacilityFloor(
                floor_id="floor-1",
                label="一层",
                elevation_m=0,
                bounds=bounds,
            ),
        ),
        zones=(
            FacilityZone(
                zone_id="zone-parking",
                floor_id="floor-1",
                label="停车区",
                kind="parking",
                polygon=(
                    _coordinate(0, 0),
                    _coordinate(40, 0),
                    _coordinate(40, 25),
                    _coordinate(0, 25),
                ),
            ),
            FacilityZone(
                zone_id="zone-buffer",
                floor_id="floor-1",
                label="缓冲区",
                kind="buffer",
                polygon=(
                    _coordinate(25, 20),
                    _coordinate(35, 20),
                    _coordinate(35, 30),
                    _coordinate(25, 30),
                ),
            ),
        ),
        nodes=(
            FacilityNode(
                node_id="entry",
                floor_id="floor-1",
                coordinate=_coordinate(0, 10),
                kind="entrance",
                label="入口",
            ),
            FacilityNode(
                node_id="junction",
                floor_id="floor-1",
                coordinate=_coordinate(10, 10),
                kind="junction",
                label="主通道",
            ),
            FacilityNode(
                node_id="access-1",
                floor_id="floor-1",
                coordinate=_coordinate(20, 10),
                kind="space_access",
                label="纵深近位接入",
            ),
            FacilityNode(
                node_id="access-2",
                floor_id="floor-1",
                coordinate=_coordinate(25, 10),
                kind="space_access",
                label="纵深深位接入",
            ),
            FacilityNode(
                node_id="buffer-access",
                floor_id="floor-1",
                coordinate=_coordinate(30, 10),
                kind="buffer_access",
                label="缓冲位接入",
            ),
            FacilityNode(
                node_id="exit",
                floor_id="floor-1",
                coordinate=_coordinate(40, 10),
                kind="exit",
                label="出口",
            ),
        ),
        edges=(
            FacilityEdge(
                edge_id="edge-entry",
                from_node_id="entry",
                to_node_id="junction",
                centerline=(_coordinate(0, 10), _coordinate(10, 10)),
                width_m=6,
                distance_m=10,
                base_travel_time_s=5,
                directed=True,
                channel_zone_ids=("channel-main",),
            ),
            FacilityEdge(
                edge_id="edge-access-1",
                from_node_id="junction",
                to_node_id="access-1",
                centerline=(_coordinate(10, 10), _coordinate(20, 10)),
                width_m=6,
                distance_m=10,
                base_travel_time_s=5,
                directed=True,
                channel_zone_ids=("channel-main",),
            ),
            FacilityEdge(
                edge_id="edge-access-2",
                from_node_id="access-1",
                to_node_id="access-2",
                centerline=(_coordinate(20, 10), _coordinate(25, 10)),
                width_m=6,
                distance_m=5,
                base_travel_time_s=3,
                directed=True,
                channel_zone_ids=("channel-main",),
            ),
            FacilityEdge(
                edge_id="edge-buffer",
                from_node_id="access-2",
                to_node_id="buffer-access",
                centerline=(_coordinate(25, 10), _coordinate(30, 10)),
                width_m=6,
                distance_m=5,
                base_travel_time_s=3,
                directed=True,
                channel_zone_ids=("channel-main",),
            ),
            FacilityEdge(
                edge_id="edge-exit",
                from_node_id="buffer-access",
                to_node_id="exit",
                centerline=(_coordinate(30, 10), _coordinate(40, 10)),
                width_m=6,
                distance_m=10,
                base_travel_time_s=5,
                directed=True,
                channel_zone_ids=("channel-main",),
            ),
        ),
        channel_zones=(ChannelZone(channel_zone_id="channel-main", capacity=2),),
        entrances=(
            FacilityEntrance(
                entrance_id="entrance-south",
                node_id="entry",
                label="南入口",
                initial_heading_deg=0,
            ),
        ),
        exits=(FacilityExit(exit_id="exit-east", node_id="exit", label="东出口"),),
        default_entrance_id="entrance-south",
        spaces=(
            FacilitySpace(
                parking_lot_id="lot-school",
                space_id="T-01",
                floor_id="floor-1",
                zone_id="zone-parking",
                geometry=FacilityRectangle(
                    center=_coordinate(20, 16), width_m=2.5, length_m=5, heading_deg=90
                ),
                access_node_id="access-1",
                stack_group_id="stack-1",
                depth=1,
            ),
            FacilitySpace(
                parking_lot_id="lot-school",
                space_id="T-02",
                floor_id="floor-1",
                zone_id="zone-parking",
                geometry=FacilityRectangle(
                    center=_coordinate(20, 22), width_m=2.5, length_m=5, heading_deg=90
                ),
                access_node_id="access-2",
                stack_group_id="stack-1",
                depth=2,
            ),
        ),
        tandem_groups=(
            FacilityTandemGroup(
                stack_group_id="stack-1",
                space_ids_near_to_deep=("T-01", "T-02"),
                buffer_ids=("buffer-1",),
            ),
        ),
        buffers=(
            FacilityBuffer(
                parking_lot_id="lot-school",
                buffer_id="buffer-1",
                floor_id="floor-1",
                zone_id="zone-buffer",
                geometry=FacilityRectangle(
                    center=_coordinate(30, 25), width_m=2.5, length_m=5, heading_deg=90
                ),
                access_node_id="buffer-access",
                stack_group_ids=("stack-1",),
            ),
        ),
    )


def _facility_state() -> ParkingFacilityStateSnapshot:
    return ParkingFacilityStateSnapshot(
        parking_lot_id="lot-school",
        layout_version="facility-school-v1",
        scenario_id="school-full-demo",
        scenario_version="scenario-school-v1",
        state_version="state-1",
        observed_at=OBSERVED_AT,
        source=FacilitySourceStatus(
            source_kind=FacilitySourceKind.SYNTHETIC,
            health=HealthStatus.HEALTHY,
            source_name="m4-contract-test",
            updated_at=OBSERVED_AT,
        ),
        spaces=(
            FacilitySpaceState(
                space_id="T-01",
                observed_status=SpaceStatus.AVAILABLE,
                observation_source=FacilityObservationSource.SYNTHETIC_TRUTH,
                effective_status=SpaceStatus.AVAILABLE,
                assignable=True,
            ),
            FacilitySpaceState(
                space_id="T-02",
                observed_status=SpaceStatus.OCCUPIED,
                observation_source=FacilityObservationSource.SYNTHETIC_TRUTH,
                effective_status=SpaceStatus.OCCUPIED,
                assignable=False,
                reason_codes=("OCCUPIED",),
            ),
        ),
        buffers=(
            FacilityBufferState(
                buffer_id="buffer-1",
                status=SpaceStatus.AVAILABLE,
                observation_source=FacilityObservationSource.SYNTHETIC_TRUTH,
            ),
        ),
    )


def _two_floor_layout() -> ParkingFacilityLayout:
    payload = _facility_layout().model_dump(mode="json")
    payload["floors"].append(
        {
            "floor_id": "floor-2",
            "label": "二层",
            "elevation_m": 3,
            "bounds": payload["bounds"],
        }
    )
    payload["nodes"].extend(
        [
            {
                "node_id": "ramp-floor-1",
                "floor_id": "floor-1",
                "coordinate": {"x_m": 35, "y_m": 5},
                "kind": "inter_floor",
                "label": "坡道一层",
            },
            {
                "node_id": "ramp-floor-2",
                "floor_id": "floor-2",
                "coordinate": {"x_m": 5, "y_m": 5},
                "kind": "inter_floor",
                "label": "坡道二层",
            },
        ]
    )
    payload["edges"].append(
        {
            "edge_id": "edge-ramp",
            "from_node_id": "ramp-floor-1",
            "to_node_id": "ramp-floor-2",
            "centerline": [{"x_m": 35, "y_m": 5}, {"x_m": 5, "y_m": 5}],
            "width_m": 4,
            "distance_m": 30,
            "base_travel_time_s": 20,
            "directed": True,
            "traversal_kind": "ramp",
            "channel_zone_ids": [],
        }
    )
    payload["inter_floor_connections"] = [
        FacilityInterFloorConnection(
            connection_id="connection-ramp",
            from_floor_id="floor-1",
            to_floor_id="floor-2",
            kind="ramp",
            edge_ids=("edge-ramp",),
        ).model_dump(mode="json")
    ]
    return ParkingFacilityLayout.model_validate(payload)


def _route_preview() -> RoutePreview:
    return RoutePreview(
        parking_lot_id="lot-school",
        layout_version="facility-school-v1",
        scenario_version="scenario-school-v1",
        state_version="state-1",
        observed_at=OBSERVED_AT,
        entrance_id="entrance-south",
        target_space_id="T-01",
        route=Route(
            parking_lot_id="lot-school",
            layout_version="facility-school-v1",
            cost_version="cost-1",
            from_node_id="entry",
            to_node_id="access-1",
            node_ids=("entry", "junction", "access-1"),
            edge_ids=("edge-entry", "edge-access-1"),
            distance_m=20,
            dynamic_eta_s=10,
            instructions=(
                RouteInstruction(
                    sequence=1,
                    edge_id="edge-entry",
                    text="沿入口通道直行",
                    distance_m=10,
                    travel_time_s=5,
                ),
                RouteInstruction(
                    sequence=2,
                    edge_id="edge-access-1",
                    text="继续前往目标车位",
                    distance_m=10,
                    travel_time_s=5,
                ),
            ),
        ),
    )


class StubFacilitySource:
    def __init__(self) -> None:
        self.sessions: list[str] = []
        self.preview_requests: list[RoutePreviewRequest] = []

    def get_layout(self, parking_lot_id: str) -> ParkingFacilityLayout:
        assert parking_lot_id == "lot-school"
        return _facility_layout()

    def get_state(
        self, parking_lot_id: str, *, session_id: str
    ) -> ParkingFacilityStateSnapshot:
        assert parking_lot_id == "lot-school"
        self.sessions.append(session_id)
        return _facility_state()

    def preview_route(
        self,
        parking_lot_id: str,
        *,
        session_id: str,
        request: RoutePreviewRequest,
    ) -> RoutePreview:
        assert parking_lot_id == "lot-school"
        self.sessions.append(session_id)
        self.preview_requests.append(request)
        return _route_preview()


class CorruptRouteSource(StubFacilitySource):
    def preview_route(
        self,
        parking_lot_id: str,
        *,
        session_id: str,
        request: RoutePreviewRequest,
    ) -> RoutePreview:
        preview = super().preview_route(
            parking_lot_id,
            session_id=session_id,
            request=request,
        )
        route = preview.route.model_copy(update={"edge_ids": ("missing-edge",)})
        return preview.model_copy(update={"route": route})


class StaleStateSource(StubFacilitySource):
    def get_state(
        self, parking_lot_id: str, *, session_id: str
    ) -> ParkingFacilityStateSnapshot:
        state = super().get_state(parking_lot_id, session_id=session_id)
        return state.model_copy(update={"state_version": "state-2"})


class UnavailableTargetSource(StubFacilitySource):
    def get_state(
        self, parking_lot_id: str, *, session_id: str
    ) -> ParkingFacilityStateSnapshot:
        state = super().get_state(parking_lot_id, session_id=session_id)
        unavailable_target = state.spaces[0].model_copy(
            update={"assignable": False, "reason_codes": ("ROUTE_BLOCKED",)}
        )
        return state.model_copy(update={"spaces": (unavailable_target, *state.spaces[1:])})


def _session_store_fingerprint(client: TestClient) -> tuple[object, object]:
    store = client.app.state.session_store
    return store.active_claims(), store.events()


def _without_observation_time(payload: dict[str, object]) -> dict[str, object]:
    stable = deepcopy(payload)
    stable.pop("updated_at")
    return stable


def test_facility_layout_accepts_complete_meter_geometry() -> None:
    layout = _facility_layout()
    assert layout.coordinate_system == "local_meters"
    assert layout.spaces[1].depth == 2
    assert layout.tandem_groups[0].buffer_ids == ("buffer-1",)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["spaces"][0].update(access_node_id="missing-node"),
        lambda value: value["spaces"][0].update(access_node_id="entry"),
        lambda value: value["spaces"][1].update(depth=3),
        lambda value: value["buffers"][0].update(stack_group_ids=["missing-group"]),
        lambda value: value["edges"][0].update(
            centerline=[{"x_m": 1, "y_m": 1}, {"x_m": 10, "y_m": 10}]
        ),
        lambda value: value["zones"][0]["polygon"][0].update(x_m=-1),
    ],
)
def test_facility_layout_rejects_invalid_geometry_and_references(mutate) -> None:  # type: ignore[no-untyped-def]
    payload = deepcopy(_facility_layout().model_dump(mode="json"))
    mutate(payload)
    with pytest.raises(ValidationError):
        ParkingFacilityLayout.model_validate(payload)


def test_inter_floor_connection_matches_edge_direction_and_traversal_kind() -> None:
    layout = _two_floor_layout()
    assert layout.inter_floor_connections[0].kind == "ramp"

    wrong_kind = layout.model_dump(mode="json")
    wrong_kind["inter_floor_connections"][0]["kind"] = "lift"
    with pytest.raises(ValidationError, match="traversal kind mismatch"):
        ParkingFacilityLayout.model_validate(wrong_kind)

    wrong_direction = layout.model_dump(mode="json")
    connection = wrong_direction["inter_floor_connections"][0]
    connection["from_floor_id"], connection["to_floor_id"] = (
        connection["to_floor_id"],
        connection["from_floor_id"],
    )
    with pytest.raises(ValidationError, match="direction mismatch"):
        ParkingFacilityLayout.model_validate(wrong_direction)


def test_facility_state_keeps_observation_claim_and_effective_status_separate() -> None:
    claimed = FacilitySpaceState(
        space_id="T-01",
        observed_status=SpaceStatus.AVAILABLE,
        observation_source=FacilityObservationSource.SYNTHETIC_TRUTH,
        claim_status=FacilityClaimStatus.SOFT_HELD,
        effective_status=SpaceStatus.UNAVAILABLE,
        assignable=False,
        reason_codes=("SOFT_HELD",),
    )
    assert claimed.observed_status is SpaceStatus.AVAILABLE
    assert claimed.effective_status is SpaceStatus.UNAVAILABLE

    with pytest.raises(ValidationError):
        FacilitySpaceState(
            space_id="T-unknown",
            observed_status=SpaceStatus.UNKNOWN,
            observation_source=FacilityObservationSource.OBSERVATION,
            effective_status=SpaceStatus.AVAILABLE,
            assignable=True,
        )

    with pytest.raises(ValidationError, match="must remain effectively available"):
        FacilitySpaceState(
            space_id="T-conflict",
            observed_status=SpaceStatus.AVAILABLE,
            observation_source=FacilityObservationSource.SYNTHETIC_TRUTH,
            effective_status=SpaceStatus.OCCUPIED,
            assignable=False,
            reason_codes=("CONFLICT",),
        )


def test_real_facility_state_requires_healthy_observed_truth() -> None:
    synthetic_payload = _facility_state().model_dump(mode="json")
    synthetic_payload["source"]["source_kind"] = "real"
    with pytest.raises(ValidationError, match="cannot contain synthetic"):
        ParkingFacilityStateSnapshot.model_validate(synthetic_payload)

    observed_payload = deepcopy(synthetic_payload)
    for item in (*observed_payload["spaces"], *observed_payload["buffers"]):
        item["observation_source"] = "observation"
    observed_payload["source"].update(
        health="degraded", missing_fields=["spaces.T-03"], fail_reason=None
    )
    with pytest.raises(ValidationError, match="must be healthy"):
        ParkingFacilityStateSnapshot.model_validate(observed_payload)


def test_facility_state_must_cover_layout_exactly() -> None:
    payload = _facility_state().model_dump(mode="json")
    payload["spaces"] = payload["spaces"][:-1]
    incomplete = ParkingFacilityStateSnapshot.model_validate(payload)
    with pytest.raises(ValueError, match="cover layout spaces exactly"):
        incomplete.require_layout(_facility_layout())


def test_route_preview_requires_route_scope_and_layout_identity() -> None:
    payload = _route_preview().model_dump(mode="json")
    payload["route"]["layout_version"] = "other-layout"
    with pytest.raises(ValidationError):
        RoutePreview.model_validate(payload)

    invalid_path = _route_preview().model_copy(
        update={"route": _route_preview().route.model_copy(update={"edge_ids": ("edge-exit",)})}
    )
    with pytest.raises(ValueError, match="sequence lengths differ"):
        invalid_path.require_context(
            request=RoutePreviewRequest(
                layout_version="facility-school-v1",
                scenario_version="scenario-school-v1",
                state_version="state-1",
                entrance_id="entrance-south",
                target_space_id="T-01",
            ),
            layout=_facility_layout(),
            state=_facility_state(),
        )

    mismatched_layout = _facility_layout().model_copy(update={"layout_version": "other-v1"})
    with pytest.raises(ValueError, match="layout version mismatch"):
        _route_preview().require_context(
            request=RoutePreviewRequest(
                layout_version="facility-school-v1",
                scenario_version="scenario-school-v1",
                state_version="state-1",
                entrance_id="entrance-south",
                target_space_id="T-01",
            ),
            layout=mismatched_layout,
            state=_facility_state(),
        )

    wrong_endpoints = _route_preview().model_copy(
        update={
            "route": _route_preview().route.model_copy(
                update={"node_ids": ("junction", "access-1", "entry")}
            )
        }
    )
    with pytest.raises(ValueError, match="sequence endpoints"):
        wrong_endpoints.require_context(
            request=RoutePreviewRequest(
                layout_version="facility-school-v1",
                scenario_version="scenario-school-v1",
                state_version="state-1",
                entrance_id="entrance-south",
                target_space_id="T-01",
            ),
            layout=_facility_layout(),
            state=_facility_state(),
        )

    instructions = list(_route_preview().route.instructions)
    instructions[1] = instructions[1].model_copy(update={"sequence": 3})
    wrong_sequence = _route_preview().model_copy(
        update={
            "route": _route_preview().route.model_copy(
                update={"instructions": tuple(instructions)}
            )
        }
    )
    with pytest.raises(ValueError, match="instruction sequence"):
        wrong_sequence.require_context(
            request=RoutePreviewRequest(
                layout_version="facility-school-v1",
                scenario_version="scenario-school-v1",
                state_version="state-1",
                entrance_id="entrance-south",
                target_space_id="T-01",
            ),
            layout=_facility_layout(),
            state=_facility_state(),
        )


def test_facility_endpoints_are_additive_session_scoped_and_have_no_selector() -> None:
    source = StubFacilitySource()
    client = TestClient(
        create_app(scenario_profile=ScenarioProfile.LEGACY, facility_source=source)
    )

    layout = client.get("/api/v2/parking-lots/lot-school/facility-layout")
    assert layout.status_code == 200
    assert layout.json()["layout_version"] == "facility-school-v1"

    missing_session = client.get("/api/v2/parking-lots/lot-school/facility-state")
    assert missing_session.status_code == 422
    assert set(missing_session.json()) == {"code", "message", "details", "request_id"}
    rejected_selector = client.get(
        "/api/v2/parking-lots/lot-school/facility-layout?scenario_id=school-demo"
    )
    assert rejected_selector.status_code == 422

    headers = {"X-Session-ID": "driver-contract-test"}
    before_store = _session_store_fingerprint(client)
    before_lot = client.get("/api/v2/parking-lots/lot-school", headers=headers).json()
    state = client.get(
        "/api/v2/parking-lots/lot-school/facility-state",
        headers=headers,
    )
    assert state.status_code == 200
    assert state.headers["Vary"] == "X-Session-ID"

    preview = client.post(
        "/api/v2/parking-lots/lot-school/route-previews",
        headers=headers,
        json={
            "schema_version": "1.0.0",
            "layout_version": "facility-school-v1",
            "scenario_version": "scenario-school-v1",
            "state_version": "state-1",
            "entrance_id": "entrance-south",
            "target_space_id": "T-01",
        },
    )
    assert preview.status_code == 200
    assert preview.json()["route"]["schema_version"] == "2.0.0"
    assert source.sessions == [
        "driver-contract-test",
        "driver-contract-test",
        "driver-contract-test",
    ]
    assert len(source.preview_requests) == 1
    assert _session_store_fingerprint(client) == before_store
    after_lot = client.get("/api/v2/parking-lots/lot-school", headers=headers).json()
    assert _without_observation_time(after_lot) == _without_observation_time(before_lot)


@pytest.mark.parametrize(
    ("source", "expected_status"),
    [
        (CorruptRouteSource(), 503),
        (StaleStateSource(), 409),
        (UnavailableTargetSource(), 409),
    ],
)
def test_route_preview_distinguishes_source_corruption_from_stale_state(
    source: StubFacilitySource, expected_status: int
) -> None:
    client = TestClient(
        create_app(scenario_profile=ScenarioProfile.LEGACY, facility_source=source)
    )
    headers = {"X-Session-ID": "driver-conflict-test"}
    before_store = _session_store_fingerprint(client)
    before_lot = client.get("/api/v2/parking-lots/lot-school", headers=headers).json()
    response = client.post(
        "/api/v2/parking-lots/lot-school/route-previews",
        headers=headers,
        json={
            "schema_version": "1.0.0",
            "layout_version": "facility-school-v1",
            "scenario_version": "scenario-school-v1",
            "state_version": "state-1",
            "entrance_id": "entrance-south",
            "target_space_id": "T-01",
        },
    )
    assert response.status_code == expected_status
    assert _session_store_fingerprint(client) == before_store
    after_lot = client.get("/api/v2/parking-lots/lot-school", headers=headers).json()
    assert _without_observation_time(after_lot) == _without_observation_time(before_lot)


def test_legacy_facility_source_fails_closed_and_public_profile_is_published() -> None:
    client = TestClient(create_app(scenario_profile=ScenarioProfile.LEGACY))
    response = client.get("/api/v2/parking-lots/lot-school/facility-layout")
    assert response.status_code == 503
    assert "not published" in response.json()["message"]

    public_client = TestClient(create_app(scenario_profile=ScenarioProfile.PUBLIC))
    assert public_client.get("/api/v2/parking-lots").status_code == 200
    assert public_client.get("/api/v2/discovery-area").status_code == 200
    assert public_client.get("/api/v2/parking-lots/lot-school/facility-layout").status_code == 200


def test_legacy_profile_is_internal_and_query_cannot_select_another_scenario() -> None:
    scenarios = built_in_scenarios()
    legacy = SyntheticParkingDataSource(scenarios, profile=ScenarioProfile.LEGACY)
    assert legacy.profile is ScenarioProfile.LEGACY

    client = TestClient(create_app(scenario_profile=ScenarioProfile.LEGACY))
    regular = client.get("/api/v2/parking-lots/lot-school/layout")
    attempted_switch = client.get(
        "/api/v2/parking-lots/lot-school/layout?scenario_id=commercial-demo"
    )
    assert attempted_switch.status_code == 200
    assert attempted_switch.json() == regular.json()


def test_facility_openapi_uses_the_runtime_error_model_for_422() -> None:
    schema = create_app(scenario_profile=ScenarioProfile.LEGACY).openapi()
    operations = (
        schema["paths"]["/api/v2/parking-lots/{parking_lot_id}/facility-layout"]["get"],
        schema["paths"]["/api/v2/parking-lots/{parking_lot_id}/facility-state"]["get"],
        schema["paths"]["/api/v2/parking-lots/{parking_lot_id}/route-previews"]["post"],
    )
    for operation in operations:
        error_schema = operation["responses"]["422"]["content"]["application/json"]["schema"]
        assert error_schema == {"$ref": "#/components/schemas/ErrorResponse"}


def test_r0a_legacy_hashes_remain_unchanged() -> None:
    expected = {
        "schemas/v2/layout.schema.json": (
            "47c2409fce768ea96494abea567a1fecf1e4b3970f55102f26e1861f16f68547"
        ),
        "data/synthetic/web-v2/commercial-demo.scenario.json": (
            "65a034399810f567ca59f5c6c04c9f022e62052e6816abeafaf9afe0aab79579"
        ),
        "data/synthetic/web-v2/school-demo.scenario.json": (
            "b0b0e2fe0613401eb47d987441799b6ac3756a157950302fdbbd44985ece10a0"
        ),
        "data/synthetic/web-v2/hospital-demo.scenario.json": (
            "885513da6c97dae9b9f0b3dbd1ea6d31053119a943a5890e9e0862a380261e82"
        ),
        "data/synthetic/web-v2/transport-hub-demo.scenario.json": (
            "825077594d3fec87fa2e2a4d853955d1fefe958896e39c57417203b6061bdfca"
        ),
    }
    actual = {
        relative: hashlib.sha256((REPO_ROOT / relative).read_bytes()).hexdigest()
        for relative in expected
    }
    assert actual == expected
