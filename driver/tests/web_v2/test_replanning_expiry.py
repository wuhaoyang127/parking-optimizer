from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from parking_opt.api.dynamic_costs import DynamicCostService
from parking_opt.api.models import ChannelLoadSnapshot
from parking_opt.api.routing import RouteCostService
from parking_opt.api.scenarios import built_in_scenarios
from parking_opt.api.services.replanning import JourneyReplanService
from parking_opt.api.sessions import (
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


def test_expired_driver_demo_does_not_search_for_a_new_route(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    store, clock, service, journey_id, bundle = _navigating()
    before = store.get_journey(journey_id)
    assert before is not None
    calls = 0
    original_route = service._routes.route

    def counted_route(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return original_route(*args, **kwargs)

    monkeypatch.setattr(service._routes, "route", counted_route)
    clock.advance(300)
    result = service.driver_demo_replan(
        journey_id=journey_id,
        expected_version=before.version,
        action="simulate_deviation",
        layout=bundle.layout,  # type: ignore[attr-defined]
        idempotency_key="driver-demo-expired",
    )
    assert result.journey.state.value == "expired"
    assert result.decision.reason_codes == ("RESERVATION_EXPIRED",)
    assert calls == 0


def test_stale_driver_demo_fails_before_deriving_a_route(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    store, _, service, journey_id, bundle = _navigating()
    current = store.get_journey(journey_id)
    assert current is not None
    calls = 0

    def unexpected_route(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        raise AssertionError("stale driver demo must not derive a route")

    monkeypatch.setattr(service._routes, "route", unexpected_route)
    before_events = store.events()
    before_recovery = service.recover_navigation(journey_id)
    with pytest.raises(VersionConflictError, match="stale journey version"):
        service.driver_demo_replan(
            journey_id=journey_id,
            expected_version=current.version - 1,
            action="simulate_deviation",
            layout=bundle.layout,  # type: ignore[attr-defined]
            idempotency_key="driver-demo-stale",
        )
    assert calls == 0
    assert store.get_journey(journey_id) == current
    assert store.events() == before_events
    assert service.recover_navigation(journey_id) == before_recovery


def test_replan_warns_when_eta_exceeds_remaining_deadline() -> None:
    store, clock, service, journey_id, bundle = _navigating()
    before = store.get_journey(journey_id)
    assert before is not None
    clock.advance(250)
    result = service.replan(
        journey_id=journey_id,
        expected_version=before.version,
        current_node_id=bundle.layout.entrance_node_ids[0],  # type: ignore[attr-defined]
        trigger="cost_update",
        layout=bundle.layout,  # type: ignore[attr-defined]
        channel_load=_load(bundle),
        idempotency_key="replan-warning",
    )
    assert result.decision.status == "warning"
    assert result.decision.reason_codes == ("ETA_EXCEEDS_RESERVATION",)
    assert result.journey.expires_at == before.expires_at
