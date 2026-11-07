from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from parking_opt.api.dynamic_costs import DynamicCostService
from parking_opt.api.models import ChannelLoadSnapshot
from parking_opt.api.routing import RouteCostService
from parking_opt.api.scenarios import built_in_scenarios
from parking_opt.api.services.replanning import JourneyReplanService
from parking_opt.api.sessions import (
    IdempotencyConflictError,
    IllegalTransitionError,
    InMemorySessionStore,
    SessionNamespace,
    SessionTiming,
    VersionConflictError,
)


class FakeClock:
    def __init__(self) -> None:
        self.elapsed_s = 0.0
        self.origin = datetime(2026, 8, 13, tzinfo=UTC)

    def monotonic(self) -> float:
        return self.elapsed_s

    def utcnow(self) -> datetime:
        return self.origin + timedelta(seconds=self.elapsed_s)

    def advance(self, seconds: float) -> None:
        self.elapsed_s += seconds


def _navigating() -> tuple[
    InMemorySessionStore, FakeClock, JourneyReplanService, str, object
]:
    bundle = built_in_scenarios()["school-demo"]
    clock = FakeClock()
    store = InMemorySessionStore(
        timing=SessionTiming(
            driver_idle_ttl_s=1800,
            defense_idle_ttl_s=7200,
            soft_hold_ttl_s=30,
            driver_reservation_ttl_s=300,
            defense_reservation_ttl_s=60,
        ),
        monotonic_clock=clock.monotonic,
        utc_clock=clock.utcnow,
    )
    target = bundle.layout.spaces[0]
    held = store.soft_hold(
        session_id="session-replan",
        namespace=SessionNamespace.DRIVER,
        scenario_id=bundle.scenario_id,
        parking_lot_id=bundle.layout.parking_lot_id,
        journey_id="journey-replan",
        attempt_id="attempt-replan",
        space_id=target.space_id,
        idempotency_key="hold-replan",
    )
    reserved = store.confirm(
        journey_id=held.journey_id,
        accepted=True,
        expected_version=held.version,
        idempotency_key="confirm-replan",
    )
    navigating = store.start_navigation(
        journey_id=held.journey_id,
        expected_version=reserved.version,
        idempotency_key="navigate-replan",
    )
    routes = RouteCostService()
    original = routes.route(
        bundle.layout,
        bundle.cost_snapshot,
        from_node_id=bundle.layout.entrance_node_ids[0],
        to_node_id=target.access_node_id,
    )
    service = JourneyReplanService(
        route_service=routes,
        cost_service=DynamicCostService(),
        session_store=store,
        eta_safety_margin_s=60,
    )
    service.register_route(held.journey_id, original)
    return store, clock, service, navigating.journey_id, bundle


def _load(bundle: object, *, full: bool = False) -> ChannelLoadSnapshot:
    layout = bundle.layout  # type: ignore[attr-defined]
    observed_at = bundle.cost_snapshot.observed_at  # type: ignore[attr-defined]
    return ChannelLoadSnapshot(
        parking_lot_id=layout.parking_lot_id,
        layout_version=layout.layout_version,
        observed_at=observed_at,
        active_units_by_zone={
            zone.channel_zone_id: zone.capacity if full else 0
            for zone in layout.channel_zones
        },
    )


def test_replan_success_preserves_deadline_and_is_idempotent() -> None:
    store, _, service, journey_id, bundle = _navigating()
    before = store.get_journey(journey_id)
    assert before is not None
    result = service.replan(
        journey_id=journey_id,
        expected_version=before.version,
        current_node_id=bundle.layout.entrance_node_ids[0],  # type: ignore[attr-defined]
        trigger="deviation",
        layout=bundle.layout,  # type: ignore[attr-defined]
        channel_load=_load(bundle),
        idempotency_key="replan-success",
    )
    replay = service.replan(
        journey_id=journey_id,
        expected_version=before.version,
        current_node_id=bundle.layout.entrance_node_ids[0],  # type: ignore[attr-defined]
        trigger="deviation",
        layout=bundle.layout,  # type: ignore[attr-defined]
        channel_load=_load(bundle),
        idempotency_key="replan-success",
    )
    assert replay == result
    assert result.decision.status == "success"
    assert result.journey.expires_at == before.expires_at
    assert store.events()[-1].event_type == "REPLAN_SUCCESS"


def test_driver_demo_replan_derives_complete_inputs_and_replays() -> None:
    store, clock, service, journey_id, bundle = _navigating()
    before = store.get_journey(journey_id)
    assert before is not None
    first = service.driver_demo_replan(
        journey_id=journey_id,
        expected_version=before.version,
        action="simulate_deviation",
        layout=bundle.layout,  # type: ignore[attr-defined]
        idempotency_key="driver-demo-deviation",
    )
    replay = service.driver_demo_replan(
        journey_id=journey_id,
        expected_version=before.version,
        action="simulate_deviation",
        layout=bundle.layout,  # type: ignore[attr-defined]
        idempotency_key="driver-demo-deviation",
    )
    assert replay == first
    assert first.decision.trigger == "deviation"
    assert first.decision.cost_snapshot.observed_at == clock.utcnow()
    assert set(first.decision.cost_snapshot.edge_travel_time_s) == {
        edge.edge_id for edge in bundle.layout.edges  # type: ignore[attr-defined]
    }
    recovery = service.recover_navigation(journey_id)
    assert recovery is not None
    assert recovery.current_node_id not in first.decision.previous_route.node_ids
    with pytest.raises(IdempotencyConflictError, match="different input"):
        service.driver_demo_replan(
            journey_id=journey_id,
            expected_version=before.version,
            action="simulate_cost_update",
            layout=bundle.layout,  # type: ignore[attr-defined]
            idempotency_key="driver-demo-deviation",
        )
    with pytest.raises(IdempotencyConflictError, match="different input"):
        service.driver_demo_replan(
            journey_id=journey_id,
            expected_version=first.journey.version,
            action="simulate_deviation",
            layout=bundle.layout,  # type: ignore[attr-defined]
            idempotency_key="driver-demo-deviation",
        )


def test_driver_demo_cost_update_uses_one_complete_deterministic_zone_preset() -> None:
    store, clock, service, journey_id, bundle = _navigating()
    before = store.get_journey(journey_id)
    assert before is not None
    result = service.driver_demo_replan(
        journey_id=journey_id,
        expected_version=before.version,
        action="simulate_cost_update",
        layout=bundle.layout,  # type: ignore[attr-defined]
        idempotency_key="driver-demo-cost",
    )
    assert result.decision.trigger == "cost_update"
    assert result.decision.cost_snapshot.observed_at == clock.utcnow()
    assert result.decision.cost_snapshot.unavailable_edge_ids
    assert result.journey.expires_at == before.expires_at
