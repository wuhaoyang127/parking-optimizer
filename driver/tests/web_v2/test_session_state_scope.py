from __future__ import annotations
from datetime import UTC, datetime, timedelta
import pytest
from parking_opt.api.sessions import (
    ActiveJourneyConflictError,
    IdempotencyConflictError,
    IllegalTransitionError,
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

def test_availability_snapshot_keeps_scenario_and_lot_scopes_separate(
    store: InMemorySessionStore,
) -> None:
    school = _hold(store, session_id="session-multi-scope", space_id="A-02")
    store.report_external_occupancy(
        journey_id=school.journey_id,
        expected_version=school.version,
        idempotency_key="external-school-scope",
    )
    store.soft_hold(
        session_id="session-multi-scope",
        namespace=SessionNamespace.DRIVER,
        scenario_id="hospital-demo",
        parking_lot_id="lot-hospital",
        journey_id="journey-hospital-scope",
        attempt_id="attempt-hospital-scope",
        space_id="C-01",
        idempotency_key="hold-hospital-scope",
    )
    snapshot = store.availability_snapshot(
        session_id="session-multi-scope",
        namespace=SessionNamespace.DRIVER,
        scopes=(
            ("school-demo", "lot-school"),
            ("hospital-demo", "lot-hospital"),
            ("commercial-demo", "lot-commercial"),
        ),
    )
    by_scope = {
        (item.scenario_id, item.parking_lot_id): (
            item.claimed_space_ids,
            item.unavailable_space_ids,
        )
        for item in snapshot.scopes
    }
    assert by_scope[("school-demo", "lot-school")] == (frozenset(), frozenset({"A-02"}))
    assert by_scope[("hospital-demo", "lot-hospital")] == (frozenset({"C-01"}), frozenset())
    assert by_scope[("commercial-demo", "lot-commercial")] == (frozenset(), frozenset())

def test_confirmation_starts_new_reservation_but_navigation_does_not_renew_it(
    store: InMemorySessionStore, clock: FakeClock
) -> None:
    held = _hold(store)
    clock.advance(20)
    reserved = store.confirm(
        journey_id=held.journey_id,
        accepted=True,
        expected_version=held.version,
        idempotency_key="confirm-1",
    )
    assert reserved.state is JourneyState.SESSION_RESERVED
    assert reserved.expires_at == clock.origin + timedelta(seconds=320)
    clock.advance(80)
    navigating = store.start_navigation(
        journey_id=held.journey_id,
        expected_version=reserved.version,
        idempotency_key="navigate-1",
    )
    assert navigating.state is JourneyState.NAVIGATING
    assert navigating.expires_at == reserved.expires_at

def test_illegal_transition_fails_without_mutating_state(store: InMemorySessionStore) -> None:
    held = _hold(store)
    with pytest.raises(IllegalTransitionError):
        store.occupy(
            journey_id=held.journey_id,
            expected_version=held.version,
            idempotency_key="occupy-too-early",
        )
    assert store.get_journey(held.journey_id) == held
    assert len(store.events()) == 1

def test_idempotency_replays_same_result_and_rejects_changed_payload(
    store: InMemorySessionStore,
) -> None:
    held = _hold(store)
    first = store.confirm(
        journey_id=held.journey_id,
        accepted=True,
        expected_version=held.version,
        idempotency_key="confirm-same",
    )
    replay = store.confirm(
        journey_id=held.journey_id,
        accepted=True,
        expected_version=held.version,
        idempotency_key="confirm-same",
    )
    assert replay == first
    assert len(store.events()) == 2
    with pytest.raises(IdempotencyConflictError):
        store.confirm(
            journey_id=held.journey_id,
            accepted=False,
            expected_version=held.version,
            idempotency_key="confirm-same",
        )

def test_driver_has_one_active_journey_and_one_claim_per_space(
    store: InMemorySessionStore,
) -> None:
    _hold(store)
    with pytest.raises(ActiveJourneyConflictError):
        _hold(
            store,
            journey_id="journey-2",
            attempt_id="attempt-2",
            space_id="A-02",
            key="hold-2",
        )
    defense = _hold(
        store,
        namespace=SessionNamespace.DEFENSE,
        journey_id="defense-1",
        attempt_id="defense-attempt-1",
        key="defense-hold-1",
    )
    with pytest.raises(ResourceClaimConflictError):
        _hold(
            store,
            namespace=SessionNamespace.DEFENSE,
            journey_id="defense-2",
            attempt_id="defense-attempt-2",
            key="defense-hold-2",
        )
    assert defense.space_id == "A-01"
