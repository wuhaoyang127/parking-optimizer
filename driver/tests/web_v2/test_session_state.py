from __future__ import annotations
from datetime import UTC, datetime, timedelta
import pytest
from parking_opt.api.sessions import (
    InMemorySessionStore,
    JourneyState,
    SessionNamespace,
    SessionTiming,
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

def _hold(
    store: InMemorySessionStore,
    *,
    session_id: str = "session-1",
    namespace: SessionNamespace = SessionNamespace.DRIVER,
    journey_id: str = "journey-1",
    attempt_id: str = "attempt-1",
    space_id: str = "A-01",
    key: str = "hold-1",
):  # type: ignore[no-untyped-def]
    return store.soft_hold(
        session_id=session_id,
        namespace=namespace,
        scenario_id="school-demo",
        parking_lot_id="lot-school",
        journey_id=journey_id,
        attempt_id=attempt_id,
        space_id=space_id,
        idempotency_key=key,
    )

def test_soft_hold_expires_exactly_at_thirty_seconds(
    store: InMemorySessionStore, clock: FakeClock
) -> None:
    held = _hold(store)
    assert held.state is JourneyState.SOFT_HELD
    assert held.expires_at == clock.origin + timedelta(seconds=30)
    clock.advance(29.999)
    assert store.expire_due() == ()
    assert store.get_journey("journey-1").state is JourneyState.SOFT_HELD
    clock.advance(0.001)
    expired = store.expire_due()
    assert expired[0].state is JourneyState.EXPIRED

def test_external_occupancy_at_expiry_does_not_create_an_unavailable_space(
    store: InMemorySessionStore, clock: FakeClock
) -> None:
    held = _hold(store, space_id="A-02")
    reserved = store.confirm(
        journey_id=held.journey_id,
        accepted=True,
        expected_version=held.version,
        idempotency_key="external-expiry-confirm",
    )
    clock.advance(300)
    result = store.report_external_occupancy(
        journey_id=held.journey_id,
        expected_version=reserved.version,
        idempotency_key="external-at-expiry",
    )
    snapshot = store.availability_snapshot(
        session_id=held.session_id,
        namespace=held.namespace,
        scopes=((held.scenario_id, held.parking_lot_id),),
    )
    assert result.state is JourneyState.EXPIRED
    assert snapshot.scopes[0].unavailable_space_reasons == ()
    assert store.active_claims() == ()

def test_availability_snapshot_expires_without_renewing_and_is_scope_isolated(
    store: InMemorySessionStore, clock: FakeClock
) -> None:
    _hold(store, session_id="session-snapshot", space_id="A-02")
    defense = _hold(
        store,
        session_id="session-snapshot",
        namespace=SessionNamespace.DEFENSE,
        journey_id="journey-defense-snapshot",
        attempt_id="attempt-defense-snapshot",
        space_id="A-03",
        key="hold-defense-snapshot",
    )
    clock.advance(29.999)
    before = store.availability_snapshot(
        session_id="session-snapshot",
        namespace=SessionNamespace.DRIVER,
        scopes=(("school-demo", "lot-school"),),
    )
    assert before.scopes[0].claimed_space_ids == frozenset({"A-02"})
    assert store.get_journey(defense.journey_id) == defense
    clock.advance(0.001)
    expired = store.availability_snapshot(
        session_id="session-snapshot",
        namespace=SessionNamespace.DRIVER,
        scopes=(("school-demo", "lot-school"),),
    )
    assert expired.scopes[0].claimed_space_ids == frozenset()
    assert store.get_journey("journey-1").state is JourneyState.EXPIRED
    assert store.get_journey("journey-defense-snapshot") == defense

def test_idle_gc_clears_external_unavailable_space(
    store: InMemorySessionStore, clock: FakeClock
) -> None:
    held = _hold(store, session_id="session-external-gc", space_id="A-02")
    failed = store.report_external_occupancy(
        journey_id=held.journey_id,
        expected_version=held.version,
        idempotency_key="external-gc",
    )
    assert failed.state is JourneyState.FAILED
    current = store.availability_snapshot(
        session_id="session-external-gc",
        namespace=SessionNamespace.DRIVER,
        scopes=(("school-demo", "lot-school"),),
    )
    assert current.scopes[0].unavailable_space_ids == frozenset({"A-02"})
    clock.advance(1800)
    collected = store.availability_snapshot(
        session_id="session-external-gc",
        namespace=SessionNamespace.DRIVER,
        scopes=(("school-demo", "lot-school"),),
    )
    assert collected.scopes[0].unavailable_space_ids == frozenset()

def test_defense_gc_keeps_unavailable_space_while_another_journey_is_active(
    store: InMemorySessionStore, clock: FakeClock
) -> None:
    external = _hold(
        store,
        session_id="defense-shared",
        namespace=SessionNamespace.DEFENSE,
        journey_id="defense-external",
        attempt_id="defense-external-attempt",
        space_id="A-02",
        key="defense-external-hold",
    )
    store.report_external_occupancy(
        journey_id=external.journey_id,
        expected_version=external.version,
        idempotency_key="defense-external-report",
    )
    clock.advance(7200)
    active = _hold(
        store,
        session_id="defense-shared",
        namespace=SessionNamespace.DEFENSE,
        journey_id="defense-active",
        attempt_id="defense-active-attempt",
        space_id="A-03",
        key="defense-active-hold",
    )
    snapshot = store.availability_snapshot(
        session_id="defense-shared",
        namespace=SessionNamespace.DEFENSE,
        scopes=(("school-demo", "lot-school"),),
    )
    assert store.get_journey(active.journey_id).state is JourneyState.SOFT_HELD
    assert snapshot.scopes[0].unavailable_space_ids == frozenset({"A-02"})
    cancelled = store.cancel(
        journey_id=active.journey_id,
        expected_version=active.version,
        idempotency_key="defense-active-cancel",
    )
    assert cancelled.state is JourneyState.CANCELLED
    clock.advance(7200)
    cleared = store.availability_snapshot(
        session_id="defense-shared",
        namespace=SessionNamespace.DEFENSE,
        scopes=(("school-demo", "lot-school"),),
    )
    assert cleared.scopes[0].unavailable_space_ids == frozenset()
