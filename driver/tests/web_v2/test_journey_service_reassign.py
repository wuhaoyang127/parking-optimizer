from __future__ import annotations
import pytest
from parking_opt.api.scenarios import built_in_scenarios
from parking_opt.api.sessions import (
    ActiveJourneyConflictError,
    IdempotencyConflictError,
    JourneyState,
    SessionNamespace,
)
from journey_fixtures import _driver, _service, _store
@pytest.mark.parametrize(
    ("reason", "terminal_reason"),
    [
        ("unable_to_park", "USER_UNABLE_TO_PARK"),
        ("eta_exceeds_reservation", "ETA_EXCEEDS_RESERVATION"),
    ],
)
def test_reassign_replays_and_preserves_reasoned_exclusion_chain(
    reason: str, terminal_reason: str
) -> None:
    bundle = built_in_scenarios()["school-demo"]
    store = _store()
    service = _service(store)
    first = service.recommend_and_hold(
        driver=_driver(f"request-reassign-{reason}"),
        namespace=SessionNamespace.DRIVER,
        scenario_id=bundle.scenario_id,
        journey_id=f"journey-reassign-{reason}-1",
        attempt_id=f"attempt-reassign-{reason}-1",
        layout=bundle.layout,
        costs=bundle.cost_snapshot,
        data_source=bundle.parking_lot.data_source,
        idempotency_key=f"recommend-reassign-{reason}-1",
    )
    reserved = store.confirm(journey_id=first.journey.journey_id, accepted=True, expected_version=first.journey.version, idempotency_key=f"confirm-reassign-{reason}-1")
    navigating = store.start_navigation(journey_id=reserved.journey_id, expected_version=reserved.version, idempotency_key=f"navigate-reassign-{reason}-1")
    kwargs = {
        "journey_id": navigating.journey_id,
        "expected_version": navigating.version,
        "reason": reason,
        "replacement_journey_id": f"journey-reassign-{reason}-2",
        "replacement_attempt_id": f"attempt-reassign-{reason}-2",
        "replacement_request_id": f"request-reassign-{reason}-2",
        "layout": bundle.layout,
        "costs": bundle.cost_snapshot,
        "data_source": bundle.parking_lot.data_source,
        "idempotency_key": f"reassign-{reason}-1",
    }
    replacement = service.reassign_after_driver_issue(**kwargs)
    assert service.reassign_after_driver_issue(**kwargs) == replacement
    assert replacement.ended_journey.terminal_reason == terminal_reason
    first_space = first.journey.space_id
    assert replacement.replacement.journey.space_id != first_space
    with pytest.raises(IdempotencyConflictError):
        service.reassign_after_driver_issue(**{**kwargs, "replacement_request_id": "changed-request"})
    assert replacement.replacement.journey.state is JourneyState.SOFT_HELD
    reserved_2 = store.confirm(journey_id=replacement.replacement.journey.journey_id, accepted=True, expected_version=replacement.replacement.journey.version, idempotency_key=f"confirm-reassign-{reason}-2")
    navigating_2 = store.start_navigation(journey_id=reserved_2.journey_id, expected_version=reserved_2.version, idempotency_key=f"navigate-reassign-{reason}-2")
    second = service.reassign_after_driver_issue(
        journey_id=navigating_2.journey_id,
        expected_version=navigating_2.version,
        reason=reason,
        replacement_journey_id=f"journey-reassign-{reason}-3",
        replacement_attempt_id=f"attempt-reassign-{reason}-3",
        replacement_request_id=f"request-reassign-{reason}-3",
        layout=bundle.layout,
        costs=bundle.cost_snapshot,
        data_source=bundle.parking_lot.data_source,
        idempotency_key=f"reassign-{reason}-2",
    )
    assessments = {
        item.space_id: item.reason_codes for item in second.replacement.recommendation.assessments
    }
    assert terminal_reason in assessments[first_space]
    assert terminal_reason in assessments[replacement.replacement.journey.space_id]
def test_reassign_enters_waiting_when_only_the_rejected_space_remains() -> None:
    bundle = built_in_scenarios()["school-demo"]
    store = _store()
    service = _service(store)
    first = service.recommend_and_hold(
        driver=_driver("request-reassign-waiting"),
        namespace=SessionNamespace.DRIVER,
        scenario_id=bundle.scenario_id,
        journey_id="journey-reassign-waiting-1",
        attempt_id="attempt-reassign-waiting-1",
        layout=bundle.layout,
        costs=bundle.cost_snapshot,
        data_source=bundle.parking_lot.data_source,
        idempotency_key="recommend-reassign-waiting-1",
    )
    reserved = store.confirm(journey_id=first.journey.journey_id, accepted=True, expected_version=first.journey.version, idempotency_key="confirm-reassign-waiting")
    navigating = store.start_navigation(journey_id=reserved.journey_id, expected_version=reserved.version, idempotency_key="navigate-reassign-waiting")
    constrained_layout = bundle.layout.model_copy(
        update={
            "spaces": tuple(
                space
                if space.space_id == first.journey.space_id
                else space.model_copy(
                    update={"status": "occupied", "assignable": False, "assignability_reasons": ("SPACE_OCCUPIED",)}
                )
                for space in bundle.layout.spaces
            )
        }
    )
    replacement = service.reassign_after_driver_issue(
        journey_id=navigating.journey_id,
        expected_version=navigating.version,
        reason="unable_to_park",
        replacement_journey_id="journey-reassign-waiting-2",
        replacement_attempt_id="attempt-reassign-waiting-2",
        replacement_request_id="request-reassign-waiting-2",
        layout=constrained_layout,
        costs=bundle.cost_snapshot,
        data_source=bundle.parking_lot.data_source,
        idempotency_key="reassign-waiting",
    )
    assert replacement.ended_journey.state is JourneyState.FAILED
    assert replacement.replacement.journey.state is JourneyState.WAITING
    assert replacement.replacement.journey.space_id is None
    rejected = next(
        item
        for item in replacement.replacement.recommendation.assessments
        if item.space_id == first.journey.space_id
    )
    assert "USER_UNABLE_TO_PARK" in rejected.reason_codes
def test_external_occupancy_rolls_back_if_replacement_cannot_be_created() -> None:
    bundle = built_in_scenarios()["school-demo"]
    store = _store()
    duplicate = store.start_waiting(
        session_id="other-session",
        namespace=SessionNamespace.DRIVER,
        scenario_id=bundle.scenario_id,
        parking_lot_id=bundle.layout.parking_lot_id,
        journey_id="journey-duplicate",
        attempt_id="attempt-duplicate",
        idempotency_key="duplicate-start",
    )
    store.cancel(
        journey_id=duplicate.journey_id,
        expected_version=duplicate.version,
        idempotency_key="duplicate-cancel",
    )
    service = _service(store)
    first = service.recommend_and_hold(
        driver=_driver("request-rollback"),
        namespace=SessionNamespace.DRIVER,
        scenario_id=bundle.scenario_id,
        journey_id="journey-rollback-old",
        attempt_id="attempt-rollback-old",
        layout=bundle.layout,
        costs=bundle.cost_snapshot,
        data_source=bundle.parking_lot.data_source,
        idempotency_key="recommend-rollback",
    )
    before_events = store.events()
    before_claims = store.active_claims()
    with pytest.raises(ActiveJourneyConflictError):
        service.handle_external_occupancy(
            journey_id=first.journey.journey_id,
            expected_version=first.journey.version,
            replacement_journey_id="journey-duplicate",
            replacement_attempt_id="replacement-attempt",
            replacement_request_id="replacement-request",
            layout=bundle.layout,
            costs=bundle.cost_snapshot,
            data_source=bundle.parking_lot.data_source,
            idempotency_key="external-rollback",
        )
    assert store.get_journey(first.journey.journey_id) == first.journey
    assert store.active_claims() == before_claims
    assert store.events() == before_events
    assert store.unavailable_space_reasons(
        session_id=first.journey.session_id,
        namespace=first.journey.namespace,
        scenario_id=first.journey.scenario_id,
        parking_lot_id=first.journey.parking_lot_id,
    ) == {}
