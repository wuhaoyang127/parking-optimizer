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


def test_sessions_and_namespaces_have_isolated_synthetic_claims(
    store: InMemorySessionStore,
) -> None:
    driver = _hold(store)
    defense = _hold(
        store,
        namespace=SessionNamespace.DEFENSE,
        journey_id="defense-1",
        attempt_id="defense-attempt-1",
        key="defense-1",
    )
    other_session = _hold(
        store,
        session_id="session-2",
        journey_id="journey-other",
        attempt_id="attempt-other",
        key="other-1",
    )
    assert {driver.space_id, defense.space_id, other_session.space_id} == {"A-01"}
    assert len(store.active_claims()) == 3


def test_defense_reservation_uses_sixty_second_mapping(
    store: InMemorySessionStore, clock: FakeClock
) -> None:
    held = _hold(
        store,
        namespace=SessionNamespace.DEFENSE,
        journey_id="defense-1",
        attempt_id="defense-attempt-1",
        key="defense-hold",
    )
    reserved = store.confirm(
        journey_id=held.journey_id,
        accepted=True,
        expected_version=held.version,
        idempotency_key="defense-confirm",
    )
    assert reserved.expires_at == clock.origin + timedelta(seconds=60)


def test_gc_releases_occupied_demo_resource_with_audited_reason(
    store: InMemorySessionStore, clock: FakeClock
) -> None:
    held = _hold(store)
    reserved = store.confirm(
        journey_id=held.journey_id,
        accepted=True,
        expected_version=held.version,
        idempotency_key="confirm",
    )
    navigating = store.start_navigation(
        journey_id=held.journey_id,
        expected_version=reserved.version,
        idempotency_key="navigate",
    )
    store.occupy(
        journey_id=held.journey_id,
        expected_version=navigating.version,
        idempotency_key="occupy",
    )
    clock.advance(1800)
    collected = store.collect_idle_sessions()
    assert collected[0].state is JourneyState.FAILED
    assert collected[0].terminal_reason == "DEMO_SESSION_GC"
    assert store.active_claims() == ()
    assert store.events()[-1].reason_code == "DEMO_SESSION_GC"
