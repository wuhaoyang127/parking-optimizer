from __future__ import annotations
from datetime import UTC, datetime, timedelta
import pytest
from parking_opt.api.sessions import (
    IllegalTransitionError,
    InMemorySessionStore,
    JourneyState,
    SessionNamespace,
    SessionTiming,
    VersionConflictError,
)
class FakeClock:
    def __init__(self) -> None:
        self.elapsed_s = 0.0
        self.origin = datetime(2026, 8, 13, 0, 0, tzinfo=UTC)
    def monotonic(self) -> float:
        return self.elapsed_s
    def utcnow(self) -> datetime:
        return self.origin + timedelta(seconds=self.elapsed_s)
    def advance(self, seconds: float) -> None:
        self.elapsed_s += seconds
@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()
@pytest.fixture
def store(clock: FakeClock) -> InMemorySessionStore:
    return InMemorySessionStore(
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
def _hold(store, *, session_id="session-1", namespace=SessionNamespace.DRIVER, journey_id="journey-1", attempt_id="attempt-1", space_id="A-01", key="hold-1"):  # type: ignore[no-untyped-def]
    return store.soft_hold(session_id=session_id, namespace=namespace, scenario_id="school-demo", parking_lot_id="lot-school", journey_id=journey_id, attempt_id=attempt_id, space_id=space_id, idempotency_key=key)
def test_waiting_cancel_and_normal_departure_release_resources(
    store: InMemorySessionStore,
) -> None:
    waiting = store.start_waiting(
        session_id="waiting-session",
        namespace=SessionNamespace.DRIVER,
        scenario_id="school-demo",
        parking_lot_id="lot-school",
        journey_id="waiting-journey",
        attempt_id="waiting-attempt",
        idempotency_key="waiting-start",
    )
    assert waiting.state is JourneyState.WAITING
    assert waiting.space_id is None
    cancelled = store.cancel(
        journey_id=waiting.journey_id,
        expected_version=waiting.version,
        idempotency_key="waiting-cancel",
    )
    assert cancelled.state is JourneyState.CANCELLED
    held = _hold(store)
    reserved = store.confirm(
        journey_id=held.journey_id,
        accepted=True,
        expected_version=held.version,
        idempotency_key="depart-confirm",
    )
    navigating = store.start_navigation(
        journey_id=held.journey_id,
        expected_version=reserved.version,
        idempotency_key="depart-navigate",
    )
    occupied = store.occupy(
        journey_id=held.journey_id,
        expected_version=navigating.version,
        idempotency_key="depart-occupy",
    )
    departed = store.depart(
        journey_id=held.journey_id,
        expected_version=occupied.version,
        idempotency_key="depart",
    )
    assert departed.state is JourneyState.DEPARTED
    assert departed.terminal_reason == "NORMAL_DEPARTURE"
    assert store.active_claims() == ()
def test_stale_version_and_terminal_reactivation_are_rejected(
    store: InMemorySessionStore,
) -> None:
    held = _hold(store)
    reserved = store.confirm(
        journey_id=held.journey_id,
        accepted=True,
        expected_version=held.version,
        idempotency_key="confirm-version",
    )
    with pytest.raises(VersionConflictError):
        store.start_navigation(
            journey_id=held.journey_id,
            expected_version=held.version,
            idempotency_key="stale-navigation",
        )
    cancelled = store.cancel(
        journey_id=held.journey_id,
        expected_version=reserved.version,
        idempotency_key="cancel-version",
    )
    with pytest.raises(IllegalTransitionError):
        store.start_navigation(
            journey_id=held.journey_id,
            expected_version=cancelled.version,
            idempotency_key="reactivate",
        )
def test_demo_reset_maps_to_departed_and_clears_only_current_scope(
    store: InMemorySessionStore,
) -> None:
    external = _hold(
        store,
        journey_id="journey-reset-external",
        attempt_id="attempt-reset-external",
        space_id="A-02",
        key="hold-reset-external",
    )
    store.report_external_occupancy(
        journey_id=external.journey_id,
        expected_version=external.version,
        idempotency_key="report-reset-external",
    )
    other_external = _hold(
        store,
        session_id="session-reset-other",
        journey_id="journey-reset-other-external",
        attempt_id="attempt-reset-other-external",
        space_id="B-02",
        key="hold-reset-other-external",
    )
    store.report_external_occupancy(
        journey_id=other_external.journey_id,
        expected_version=other_external.version,
        idempotency_key="report-reset-other-external",
    )
    held = _hold(
        store,
        journey_id="journey-reset-current",
        attempt_id="attempt-reset-current",
        space_id="A-03",
        key="hold-reset-current",
    )
    reserved = store.confirm(
        journey_id=held.journey_id,
        accepted=True,
        expected_version=held.version,
        idempotency_key="reset-confirm",
    )
    navigating = store.start_navigation(
        journey_id=held.journey_id,
        expected_version=reserved.version,
        idempotency_key="reset-navigate",
    )
    occupied = store.occupy(
        journey_id=held.journey_id,
        expected_version=navigating.version,
        idempotency_key="reset-occupy",
    )
    result = store.reset_demo(
        journey_id=held.journey_id,
        expected_version=occupied.version,
        idempotency_key="reset-demo",
    )
    replay = store.reset_demo(
        journey_id=held.journey_id,
        expected_version=occupied.version,
        idempotency_key="reset-demo",
    )
    assert replay == result
    assert result.state is JourneyState.DEPARTED
    assert result.terminal_reason == "DEMO_RESET"
    assert store.active_claims() == ()
    assert store.events()[-1].reason_code == "DEMO_RESET"
    current = store.availability_snapshot(
        session_id="session-1",
        namespace=SessionNamespace.DRIVER,
        scopes=(("school-demo", "lot-school"),),
    )
    other = store.availability_snapshot(
        session_id="session-reset-other",
        namespace=SessionNamespace.DRIVER,
        scopes=(("school-demo", "lot-school"),),
    )
    assert current.scopes[0].unavailable_space_ids == frozenset()
    assert other.scopes[0].unavailable_space_ids == frozenset({"B-02"})
