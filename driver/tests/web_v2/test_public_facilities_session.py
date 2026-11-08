from __future__ import annotations

from parking_opt.api.facility_scenarios import PublicFacilityDataSource
from parking_opt.api.models import RoutePreviewRequest, SpaceStatus
from parking_opt.api.routing import RouteCostService
from parking_opt.api.sessions import InMemorySessionStore, SessionNamespace, SessionTiming


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
