from __future__ import annotations
from datetime import UTC, datetime, timedelta
import pytest
from parking_opt.api.sessions import (
    InMemorySessionStore,
    JourneyState,
    ResourceClaimConflictError,
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

def test_touch_delays_gc_without_extending_reservation(
    store: InMemorySessionStore, clock: FakeClock
) -> None:
    held = _hold(store)
    reserved = store.confirm(
        journey_id=held.journey_id,
        accepted=True,
        expected_version=held.version,
        idempotency_key="touch-confirm",
    )
    navigating = store.start_navigation(
        journey_id=held.journey_id,
        expected_version=reserved.version,
        idempotency_key="touch-navigate",
    )
    occupied = store.occupy(
        journey_id=held.journey_id,
        expected_version=navigating.version,
        idempotency_key="touch-occupy",
    )
    original_expiry = occupied.expires_at
    clock.advance(1700)
    store.touch_session("session-1", SessionNamespace.DRIVER)
    touched = store.get_journey(held.journey_id)
    assert touched is not None
    assert touched.expires_at == original_expiry
    assert store.collect_idle_sessions() == ()

def test_expiry_at_command_boundary_is_idempotent(
    store: InMemorySessionStore, clock: FakeClock
) -> None:
    held = _hold(store)
    clock.advance(30)
    first = store.confirm(
        journey_id=held.journey_id,
        accepted=True,
        expected_version=held.version,
        idempotency_key="confirm-at-expiry",
    )
    replay = store.confirm(
        journey_id=held.journey_id,
        accepted=True,
        expected_version=held.version,
        idempotency_key="confirm-at-expiry",
    )
    assert first == replay
    assert first.state is JourneyState.EXPIRED
    assert len(store.events()) == 2

def test_switch_claims_alternative_without_extending_hold(
    store: InMemorySessionStore, clock: FakeClock
) -> None:
    held = _hold(store)
    clock.advance(10)
    switched = store.switch_soft_hold(
        journey_id=held.journey_id,
        expected_version=held.version,
        space_id="A-02",
        idempotency_key="switch-1",
    )
    assert switched.space_id == "A-02"
    assert switched.expires_at == held.expires_at
    assert [claim.space_id for claim in store.active_claims()] == ["A-02"]
    assert store.events()[-1].event_type == "SOFT_HOLD_SWITCHED"
    snapshot = store.availability_snapshot(
        session_id=switched.session_id,
        namespace=switched.namespace,
        scopes=((switched.scenario_id, switched.parking_lot_id),),
    )
    assert snapshot.scopes[0].claimed_space_ids == frozenset({"A-02"})

def test_failed_switch_keeps_original_claim(store: InMemorySessionStore) -> None:
    held = _hold(
        store,
        namespace=SessionNamespace.DEFENSE,
        journey_id="defense-1",
        attempt_id="attempt-1",
        space_id="A-01",
        key="hold-1",
    )
    _hold(
        store,
        namespace=SessionNamespace.DEFENSE,
        journey_id="defense-2",
        attempt_id="attempt-2",
        space_id="A-02",
        key="hold-2",
    )
    with pytest.raises(ResourceClaimConflictError):
        store.switch_soft_hold(
            journey_id=held.journey_id,
            expected_version=held.version,
            space_id="A-02",
            idempotency_key="switch-blocked",
        )
    current = store.get_journey(held.journey_id)
    assert current == held
    assert {claim.space_id for claim in store.active_claims()} == {"A-01", "A-02"}

def test_waiting_retry_is_versioned_and_can_recover_atomically(
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
    still_waiting = store.retry_waiting(
        journey_id=waiting.journey_id,
        expected_version=waiting.version,
        space_id=None,
        idempotency_key="retry-no-space",
    )
    assert still_waiting.state is JourneyState.WAITING
    assert still_waiting.version == 2
    recovered = store.retry_waiting(
        journey_id=waiting.journey_id,
        expected_version=still_waiting.version,
        space_id="A-01",
        idempotency_key="retry-recovered",
    )
    replay = store.retry_waiting(
        journey_id=waiting.journey_id,
        expected_version=still_waiting.version,
        space_id="A-01",
        idempotency_key="retry-recovered",
    )
    assert replay == recovered
    assert recovered.state is JourneyState.SOFT_HELD
    assert recovered.space_id == "A-01"
    assert store.active_claims()[0].journey_id == waiting.journey_id
