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
    assert by_scope[("school-demo", "lot-school")] == (
        frozenset(),
        frozenset({"A-02"}),
    )
    assert by_scope[("hospital-demo", "lot-hospital")] == (
        frozenset({"C-01"}),
        frozenset(),
    )
    assert by_scope[("commercial-demo", "lot-commercial")] == (
        frozenset(),
        frozenset(),
    )


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
