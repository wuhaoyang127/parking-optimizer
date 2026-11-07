from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from parking_opt.api.dynamic_costs import DynamicCostService
from parking_opt.api.models import ChannelLoadSnapshot
from parking_opt.api.routing import RouteCostService
from parking_opt.api.scenarios import built_in_scenarios
from parking_opt.api.services.replanning import JourneyReplanService
from parking_opt.api.sessions import (
    IllegalTransitionError,
    InMemorySessionStore,
    SessionNamespace,
    SessionTiming,
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


def test_replan_unreachable_returns_previous_route_and_audited_failure() -> None:
    store, _, service, journey_id, bundle = _navigating()
    before = store.get_journey(journey_id)
    assert before is not None
    result = service.replan(
        journey_id=journey_id,
        expected_version=before.version,
        current_node_id=bundle.layout.entrance_node_ids[0],  # type: ignore[attr-defined]
        trigger="manual_refresh",
        layout=bundle.layout,  # type: ignore[attr-defined]
        channel_load=_load(bundle, full=True),
        idempotency_key="replan-failed",
    )
    assert result.decision.status == "failed"
    assert result.decision.route is None
    assert result.decision.previous_route.to_node_id == bundle.layout.spaces[0].access_node_id  # type: ignore[attr-defined]
    assert result.journey.expires_at == before.expires_at
    assert store.events()[-1].reason_code == "DYNAMIC_ROUTE_UNREACHABLE"


def test_replan_rejects_future_channel_load_without_mutation() -> None:
    store, _, service, journey_id, bundle = _navigating()
    before = store.get_journey(journey_id)
    before_events = store.events()
    assert before is not None
    future = _load(bundle).model_copy(
        update={"observed_at": datetime(2026, 8, 14, tzinfo=UTC)}
    )
    with pytest.raises(IllegalTransitionError, match="future"):
        service.replan(
            journey_id=journey_id,
            expected_version=before.version,
            current_node_id=bundle.layout.entrance_node_ids[0],  # type: ignore[attr-defined]
            trigger="cost_update",
            layout=bundle.layout,  # type: ignore[attr-defined]
            channel_load=future,
            idempotency_key="replan-future",
        )
    assert store.get_journey(journey_id) == before
    assert store.events() == before_events


def test_replan_at_expiry_returns_no_new_route_and_keeps_original_recovery(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    store, clock, service, journey_id, bundle = _navigating()
    before = store.get_journey(journey_id)
    recovery_before = service.recover_navigation(journey_id)
    assert before is not None
    assert recovery_before is not None
    route_calls = 0

    def forbidden_route(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal route_calls
        route_calls += 1
        raise AssertionError("expired navigation must not calculate a new route")

    monkeypatch.setattr(service._routes, "route", forbidden_route)  # type: ignore[attr-defined]
    clock.advance(300)
    result = service.replan(
        journey_id=journey_id,
        expected_version=before.version,
        current_node_id=bundle.layout.entrance_node_ids[0],  # type: ignore[attr-defined]
        trigger="deviation",
        layout=bundle.layout,  # type: ignore[attr-defined]
        channel_load=_load(bundle),
        idempotency_key="replan-at-expiry",
    )
    assert result.journey.state.value == "expired"
    assert result.decision.status == "failed"
    assert result.decision.route is None
    assert result.decision.reason_codes == ("RESERVATION_EXPIRED",)
    assert service.recover_navigation(journey_id) == recovery_before
    assert route_calls == 0
