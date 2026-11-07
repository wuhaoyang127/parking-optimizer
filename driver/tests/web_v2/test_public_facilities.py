from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from math import cos, radians, sin
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from parking_opt.api.adapters.v1 import V1OnlineRuleAdapter
from parking_opt.api.app import create_app
from parking_opt.api.facility_scenarios import (
    PUBLIC_SPECS,
    PublicFacilityDataSource,
    build_public_facility_scenarios,
)
from parking_opt.api.models import (
    DriverRequest,
    ParkingFacilityLayout,
    ParkingFacilityStateSnapshot,
    RoutePreviewRequest,
    ScenarioBundle,
    SpaceStatus,
)
from parking_opt.api.routing import RouteCostService, RouteNotFoundError
from parking_opt.api.services.online_rule import OnlineRuleServiceV2
from parking_opt.api.sessions import InMemorySessionStore, SessionNamespace, SessionTiming
from parking_opt.api.sources import ScenarioProfile

REPO_ROOT = Path(__file__).resolve().parents[2]


def _store() -> InMemorySessionStore:
    return InMemorySessionStore(
        timing=SessionTiming(
            driver_idle_ttl_s=600,
            defense_idle_ttl_s=600,
            soft_hold_ttl_s=30,
            driver_reservation_ttl_s=300,
            defense_reservation_ttl_s=300,
        )
    )


def _source() -> PublicFacilityDataSource:
    return PublicFacilityDataSource(session_store=_store(), route_service=RouteCostService())


def _reachable(layout, start: str) -> set[str]:  # type: ignore[no-untyped-def]
    adjacent: dict[str, list[str]] = {item.node_id: [] for item in layout.nodes}
    for edge in layout.edges:
        adjacent[edge.from_node_id].append(edge.to_node_id)
        if not edge.directed:
            adjacent[edge.to_node_id].append(edge.from_node_id)
    found, queue = {start}, deque([start])
    while queue:
        for target in adjacent[queue.popleft()]:
            if target not in found:
                found.add(target)
                queue.append(target)
    return found


def _rectangle_axes(rectangle):  # type: ignore[no-untyped-def]
    angle = radians(rectangle.heading_deg)
    return ((cos(angle), sin(angle)), (-sin(angle), cos(angle)))


def _rectangle_corners(rectangle):  # type: ignore[no-untyped-def]
    axes = _rectangle_axes(rectangle)
    return tuple(
        (
            rectangle.center.x_m
            + width_sign * rectangle.width_m / 2 * axes[0][0]
            + length_sign * rectangle.length_m / 2 * axes[1][0],
            rectangle.center.y_m
            + width_sign * rectangle.width_m / 2 * axes[0][1]
            + length_sign * rectangle.length_m / 2 * axes[1][1],
        )
        for width_sign in (-1, 1)
        for length_sign in (-1, 1)
    )


def _overlap(left, right) -> bool:  # type: ignore[no-untyped-def]
    for axis in (*_rectangle_axes(left), *_rectangle_axes(right)):
        left_projection = tuple(x * axis[0] + y * axis[1] for x, y in _rectangle_corners(left))
        right_projection = tuple(x * axis[0] + y * axis[1] for x, y in _rectangle_corners(right))
        if max(left_projection) <= min(right_projection) or max(right_projection) <= min(
            left_projection
        ):
            return False
    return True


def _segment_crosses_rectangle(left, right, rectangle) -> bool:  # type: ignore[no-untyped-def]
    axes = _rectangle_axes(rectangle)

    def local(point):  # type: ignore[no-untyped-def]
        dx = point.x_m - rectangle.center.x_m
        dy = point.y_m - rectangle.center.y_m
        return (dx * axes[0][0] + dy * axes[0][1], dx * axes[1][0] + dy * axes[1][1])

    start, end = local(left), local(right)
    minimum, maximum = 0.0, 1.0
    for start_value, end_value, half_extent in (
        (start[0], end[0], rectangle.width_m / 2),
        (start[1], end[1], rectangle.length_m / 2),
    ):
        delta = end_value - start_value
        if delta == 0:
            if abs(start_value) < half_extent:
                continue
            return False
        lower = (-half_extent - start_value) / delta
        upper = (half_extent - start_value) / delta
        minimum = max(minimum, min(lower, upper))
        maximum = min(maximum, max(lower, upper))
        if minimum >= maximum:
            return False
    return True


def test_public_facility_counts_types_and_compatibility_projection_are_exact() -> None:
    scenarios = build_public_facility_scenarios()
    for spec in PUBLIC_SPECS:
        scenario = scenarios[spec.lot_id]
        assert len(scenario.layout.spaces) == spec.spaces
        assert sum(item.charging for item in scenario.layout.spaces) == spec.charging
        assert len(scenario.layout.tandem_groups) == spec.tandem_groups
        assert (
            sum(len(item.space_ids_near_to_deep) for item in scenario.layout.tandem_groups)
            == spec.tandem_groups * 2
        )
        assert len(scenario.layout.buffers) == spec.buffers
        assert (
            sum(item.observed_status is SpaceStatus.OCCUPIED for item in scenario.base_state.spaces)
            == spec.occupied
        )
        assert {item.space_id for item in scenario.layout.spaces} == {
            item.space_id for item in scenario.bundle.layout.spaces
        }
        assert scenario.layout.layout_version == scenario.bundle.layout.layout_version
        assert not any(item.charging and item.stack_group_id for item in scenario.layout.spaces)


def test_space_and_buffer_rectangles_do_not_overlap() -> None:
    for scenario in build_public_facility_scenarios().values():
        rectangles = [
            *((item.space_id, item.geometry) for item in scenario.layout.spaces),
            *((item.buffer_id, item.geometry) for item in scenario.layout.buffers),
        ]
        for index, (left_id, left) in enumerate(rectangles):
            for right_id, right in rectangles[index + 1 :]:
                assert not _overlap(left, right), f"{left_id} overlaps {right_id}"


def test_roads_do_not_cross_positions_and_access_nodes_are_near_targets() -> None:
    for scenario in build_public_facility_scenarios().values():
        nodes = {item.node_id: item for item in scenario.layout.nodes}
        positions = [
            *(
                (item.space_id, item.geometry, item.access_node_id)
                for item in scenario.layout.spaces
            ),
            *(
                (item.buffer_id, item.geometry, item.access_node_id)
                for item in scenario.layout.buffers
            ),
        ]
        for position_id, rectangle, access_node_id in positions:
            access = nodes[access_node_id].coordinate
            distance = (
                (access.x_m - rectangle.center.x_m) ** 2 + (access.y_m - rectangle.center.y_m) ** 2
            ) ** 0.5
            assert distance <= 12, f"{position_id} access is {distance:.2f}m away"
            for edge in scenario.layout.edges:
                assert not _segment_crosses_rectangle(
                    edge.centerline[0], edge.centerline[-1], rectangle
                ), f"{edge.edge_id} crosses {position_id}"


def test_parking_lanes_are_genuinely_one_way_without_reverse_edge_pairs() -> None:
    for scenario in build_public_facility_scenarios().values():
        lane_edges = [item for item in scenario.layout.edges if item.edge_id.startswith("lane-")]
        assert lane_edges and all(item.directed for item in lane_edges)
        pairs = {(item.from_node_id, item.to_node_id) for item in lane_edges}
        assert not any((right, left) in pairs for left, right in pairs)


def test_exported_public_resources_round_trip_to_authoritative_models() -> None:
    output = REPO_ROOT / "data" / "synthetic" / "web-v2-public"
    for scenario in build_public_facility_scenarios().values():
        stem = scenario.base_state.scenario_id
        assert (
            ParkingFacilityLayout.model_validate_json(
                (output / f"{stem}.facility-layout.json").read_text(encoding="utf-8")
            )
            == scenario.layout
        )
        assert (
            ParkingFacilityStateSnapshot.model_validate_json(
                (output / f"{stem}.facility-state.json").read_text(encoding="utf-8")
            )
            == scenario.base_state
        )
        assert (
            ScenarioBundle.model_validate_json(
                (output / f"{stem}.scenario.json").read_text(encoding="utf-8")
            )
            == scenario.bundle
        )


def test_every_entrance_reaches_every_space_buffer_and_an_exit() -> None:
    for scenario in build_public_facility_scenarios().values():
        targets = {item.access_node_id for item in scenario.layout.spaces} | {
            item.access_node_id for item in scenario.layout.buffers
        }
        exit_nodes = {item.node_id for item in scenario.layout.exits}
        for entrance in scenario.layout.entrances:
            reached = _reachable(scenario.layout, entrance.node_id)
            assert targets <= reached
            assert reached & exit_nodes
        for target in targets:
            assert _reachable(scenario.layout, target) & exit_nodes


def test_directed_entry_and_exit_edges_cannot_be_traversed_backwards() -> None:
    scenario = build_public_facility_scenarios()["lot-commercial"]
    with pytest.raises(RouteNotFoundError):
        RouteCostService().route(
            scenario.bundle.layout,
            scenario.bundle.cost_snapshot,
            from_node_id="junction-nw",
            to_node_id="entrance-west",
        )
    with pytest.raises(RouteNotFoundError):
        RouteCostService().route(
            scenario.bundle.layout,
            scenario.bundle.cost_snapshot,
            from_node_id="exit-west",
            to_node_id="junction-sw",
        )


def test_session_claim_is_projected_without_mutating_base_state() -> None:
    store = _store()
    source = PublicFacilityDataSource(session_store=store, route_service=RouteCostService())
    base = source.get_state("lot-school", session_id="session-r1")
    target = next(item for item in base.spaces if item.assignable)
    held_record = store.soft_hold(
        session_id="session-r1",
        namespace=SessionNamespace.DRIVER,
        scenario_id="school-full-v1",
        parking_lot_id="lot-school",
        journey_id="journey-r1",
        attempt_id="attempt-r1",
        space_id=target.space_id,
        idempotency_key="hold-r1",
    )
    projected = source.get_state("lot-school", session_id="session-r1")
    held = next(item for item in projected.spaces if item.space_id == target.space_id)
    assert held.observed_status is SpaceStatus.AVAILABLE
    assert held.effective_status is SpaceStatus.UNAVAILABLE
    assert held.claim_status.value == "soft_held"
    assert projected.state_version != base.state_version
    reserved_record = store.confirm(
        journey_id=held_record.journey_id,
        accepted=True,
        expected_version=held_record.version,
        idempotency_key="confirm-r1",
    )
    reserved = source.get_state("lot-school", session_id="session-r1")
    reserved_space = next(item for item in reserved.spaces if item.space_id == target.space_id)
    assert reserved_space.claim_status.value == "session_reserved"
    assert reserved.state_version != projected.state_version
    navigating_record = store.start_navigation(
        journey_id=reserved_record.journey_id,
        expected_version=reserved_record.version,
        idempotency_key="navigate-r1",
    )
    navigating = source.get_state("lot-school", session_id="session-r1")
    navigating_space = next(item for item in navigating.spaces if item.space_id == target.space_id)
    assert navigating_space.claim_status.value == "navigating"
    assert navigating.state_version != reserved.state_version
    store.occupy(
        journey_id=navigating_record.journey_id,
        expected_version=navigating_record.version,
        idempotency_key="occupy-r1",
    )
    occupied = source.get_state("lot-school", session_id="session-r1")
    occupied_space = next(item for item in occupied.spaces if item.space_id == target.space_id)
    assert occupied_space.observed_status is SpaceStatus.OCCUPIED
    assert occupied_space.effective_status is SpaceStatus.OCCUPIED
    assert occupied_space.claim_status.value == "none"
    assert occupied.state_version != navigating.state_version
    assert base.observed_at < projected.observed_at <= reserved.observed_at
    assert next(
        item
        for item in source.get_state("lot-school", session_id="other").spaces
        if item.space_id == target.space_id
    ).assignable


def test_route_preview_is_versioned_read_only_and_same_layout() -> None:
    source = _source()
    state = source.get_state("lot-hospital", session_id="route-r1")
    layout = source.get_layout("lot-hospital")
    target = next(item for item in state.spaces if item.assignable)
    request = RoutePreviewRequest(
        layout_version=layout.layout_version,
        scenario_version=state.scenario_version,
        state_version=state.state_version,
        entrance_id=layout.default_entrance_id,
        target_space_id=target.space_id,
    )
    preview = source.preview_route("lot-hospital", session_id="route-r1", request=request)
    assert preview.route.layout_version == layout.layout_version
    assert preview.route.to_node_id == next(
        item.access_node_id for item in layout.spaces if item.space_id == target.space_id
    )


def test_reused_space_projects_the_newest_journey_state() -> None:
    store = _store()
    source = PublicFacilityDataSource(session_store=store, route_service=RouteCostService())
    target = next(
        item
        for item in source.get_state("lot-school", session_id="reuse-r1").spaces
        if item.assignable
    )
    first = store.soft_hold(
        session_id="reuse-r1",
        namespace=SessionNamespace.DRIVER,
        scenario_id="school-full-v1",
        parking_lot_id="lot-school",
        journey_id="journey-reuse-old",
        attempt_id="attempt-reuse-old",
        space_id=target.space_id,
        idempotency_key="hold-reuse-old",
    )
    store.cancel(
        journey_id=first.journey_id,
        expected_version=first.version,
        idempotency_key="cancel-reuse-old",
    )
    second = store.soft_hold(
        session_id="reuse-r1",
        namespace=SessionNamespace.DRIVER,
        scenario_id="school-full-v1",
        parking_lot_id="lot-school",
        journey_id="journey-reuse-new",
        attempt_id="attempt-reuse-new",
        space_id=target.space_id,
        idempotency_key="hold-reuse-new",
    )
    before = source.get_state("lot-school", session_id="reuse-r1")
    store.confirm(
        journey_id=second.journey_id,
        accepted=True,
        expected_version=second.version,
        idempotency_key="confirm-reuse-new",
    )
    after = source.get_state("lot-school", session_id="reuse-r1")
    projected = next(item for item in after.spaces if item.space_id == target.space_id)
    assert projected.claim_status.value == "session_reserved"
    assert after.state_version != before.state_version
    assert after.observed_at >= before.observed_at


@pytest.mark.parametrize("spec", PUBLIC_SPECS)
def test_online_rule_smoke_covers_regular_charging_tandem_and_route(spec) -> None:  # type: ignore[no-untyped-def]
    scenario = build_public_facility_scenarios()[spec.lot_id]
    routes = RouteCostService()
    service = OnlineRuleServiceV2(
        v1_adapter=V1OnlineRuleAdapter(
            schema_dir=REPO_ROOT / "schemas" / "v1", route_service=routes
        ),
        route_service=routes,
    )
    entrance_node = scenario.bundle.layout.entrance_node_ids[0]
    for charging in (False, True):
        result = service.recommend(
            DriverRequest(
                request_id=f"request-{charging}",
                idempotency_key=f"idem-{charging}",
                session_id="session-smoke",
                parking_lot_id=spec.lot_id,
                entrance_node_id=entrance_node,
                requires_charging=charging,
                requested_at=datetime(2026, 8, 20, 10, 0, tzinfo=UTC),
            ),
            scenario.bundle.layout,
            scenario.bundle.cost_snapshot,
            scenario.bundle.parking_lot.data_source,
        )
        assert result.solver_status == "success"
        assert result.route is not None
        if charging:
            chosen = next(
                item
                for item in scenario.bundle.layout.spaces
                if item.space_id == result.recommended_space_id
            )
            assert chosen.charging
    tandem_ids = {
        space_id
        for group in scenario.bundle.layout.tandem_groups
        for space_id in group.space_ids_near_to_deep
    }
    assert tandem_ids
    assert tandem_ids <= {item.space_id for item in result.assessments}

    forced_spaces = tuple(
        item
        if item.space_id in tandem_ids
        else item.model_copy(
            update={
                "status": SpaceStatus.OCCUPIED,
                "assignable": False,
                "assignability_reasons": ("SPACE_OCCUPIED",),
            }
        )
        for item in scenario.bundle.layout.spaces
    )
    tandem_layout = scenario.bundle.layout.model_copy(update={"spaces": forced_spaces})
    tandem_result = service.recommend(
        DriverRequest(
            request_id="request-tandem",
            idempotency_key="idem-tandem",
            session_id="session-tandem",
            parking_lot_id=spec.lot_id,
            entrance_node_id=entrance_node,
            requested_at=datetime(2026, 8, 20, 10, 0, tzinfo=UTC),
        ),
        tandem_layout,
        scenario.bundle.cost_snapshot,
        scenario.bundle.parking_lot.data_source,
    )
    assert tandem_result.solver_status == "success"
    assert tandem_result.recommended_space_id in tandem_ids
    assert tandem_result.route is not None

    no_buffer_layout = tandem_layout.model_copy(
        update={
            "spaces": tuple(
                item.model_copy(
                    update={
                        "status": SpaceStatus.OCCUPIED,
                        "assignable": False,
                        "assignability_reasons": ("SPACE_OCCUPIED",),
                    }
                )
                if item.space_id in tandem_ids and item.depth == 2
                else item
                for item in tandem_layout.spaces
            ),
            "buffers": tuple(
                item.model_copy(update={"available": False}) for item in tandem_layout.buffers
            ),
        }
    )
    failed = service.recommend(
        DriverRequest(
            request_id="request-no-buffer",
            idempotency_key="idem-no-buffer",
            session_id="session-no-buffer",
            parking_lot_id=spec.lot_id,
            entrance_node_id=entrance_node,
            requested_at=datetime(2026, 8, 20, 10, 0, tzinfo=UTC),
        ),
        no_buffer_layout,
        scenario.bundle.cost_snapshot,
        scenario.bundle.parking_lot.data_source,
    )
    assert failed.solver_status == "no_feasible_space"
    assert all(not item.feasible for item in failed.assessments)


def test_public_profile_serves_complete_resources_by_default() -> None:
    client = TestClient(create_app(scenario_profile=ScenarioProfile.PUBLIC))
    lots = client.get("/api/v2/parking-lots")
    assert lots.status_code == 200
    assert {item["total_spaces"] for item in lots.json()} == {28, 32, 48, 52}
    layout = client.get("/api/v2/parking-lots/lot-commercial/facility-layout")
    assert layout.status_code == 200
    state = client.get(
        "/api/v2/parking-lots/lot-commercial/facility-state", headers={"X-Session-ID": "api-r1"}
    )
    assert state.status_code == 200
    target = next(item for item in state.json()["spaces"] if item["assignable"])
    preview = client.post(
        "/api/v2/parking-lots/lot-commercial/route-previews",
        headers={"X-Session-ID": "api-r1"},
        json={
            "schema_version": "1.0.0",
            "layout_version": layout.json()["layout_version"],
            "scenario_version": state.json()["scenario_version"],
            "state_version": state.json()["state_version"],
            "entrance_id": layout.json()["default_entrance_id"],
            "target_space_id": target["space_id"],
        },
    )
    assert preview.status_code == 200
