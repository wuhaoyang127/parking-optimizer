from __future__ import annotations

import pytest

from parking_opt.api.models import CostSnapshot
from parking_opt.api.scenarios import built_in_scenarios
from parking_opt.api.sessions import IllegalTransitionError, JourneyState, SessionNamespace
from journey_fixtures import _clocked_store, _driver, _service, _store


def test_waiting_retry_remains_waiting_when_costs_are_still_too_slow() -> None:
    bundle = built_in_scenarios()["school-demo"]
    costs = CostSnapshot(
        parking_lot_id=bundle.parking_lot.parking_lot_id,
        layout_version=bundle.layout.layout_version,
        cost_version="cost-too-slow",
        observed_at=bundle.cost_snapshot.observed_at,
        edge_travel_time_s={key: 300.0 for key in bundle.cost_snapshot.edge_travel_time_s},
    )
    store = _store()
    service = _service(store)
    waiting = service.recommend_and_hold(
        driver=_driver("request-retry"),
        namespace=SessionNamespace.DRIVER,
        scenario_id=bundle.scenario_id,
        journey_id="journey-retry",
        attempt_id="attempt-retry",
        layout=bundle.layout,
        costs=costs,
        data_source=bundle.parking_lot.data_source,
        idempotency_key="recommend-retry",
    )
    retried = service.retry_waiting(
        journey_id=waiting.journey.journey_id,
        expected_version=waiting.journey.version,
        layout=bundle.layout,
        costs=costs,
        data_source=bundle.parking_lot.data_source,
        idempotency_key="retry-still-waiting",
    )
    assert retried.journey.state is JourneyState.WAITING
    assert retried.journey.version == waiting.journey.version + 1
    assert retried.recommendation.solver_status == "no_feasible_space"
    assert store.active_claims() == ()


def test_waiting_retry_recovers_when_costs_become_feasible() -> None:
    bundle = built_in_scenarios()["school-demo"]
    slow = CostSnapshot(
        parking_lot_id=bundle.parking_lot.parking_lot_id,
        layout_version=bundle.layout.layout_version,
        cost_version="cost-too-slow",
        observed_at=bundle.cost_snapshot.observed_at,
        edge_travel_time_s={key: 300.0 for key in bundle.cost_snapshot.edge_travel_time_s},
    )
    store = _store()
    service = _service(store)
    waiting = service.recommend_and_hold(
        driver=_driver("request-recover"),
        namespace=SessionNamespace.DRIVER,
        scenario_id=bundle.scenario_id,
        journey_id="journey-recover",
        attempt_id="attempt-recover",
        layout=bundle.layout,
        costs=slow,
        data_source=bundle.parking_lot.data_source,
        idempotency_key="recommend-recover",
    )
    recovered = service.retry_waiting(
        journey_id=waiting.journey.journey_id,
        expected_version=waiting.journey.version,
        layout=bundle.layout,
        costs=bundle.cost_snapshot,
        data_source=bundle.parking_lot.data_source,
        idempotency_key="retry-recovered",
    )
    assert recovered.journey.state is JourneyState.SOFT_HELD
    assert recovered.recommendation.claim_status == "soft_held"
    assert recovered.journey.space_id == recovered.recommendation.recommended_space_id


def test_external_occupancy_fails_old_attempt_and_excludes_original_space() -> None:
    bundle = built_in_scenarios()["school-demo"]
    store = _store()
    service = _service(store)
    first = service.recommend_and_hold(
        driver=_driver("request-external"),
        namespace=SessionNamespace.DRIVER,
        scenario_id=bundle.scenario_id,
        journey_id="journey-external-old",
        attempt_id="attempt-external-old",
        layout=bundle.layout,
        costs=bundle.cost_snapshot,
        data_source=bundle.parking_lot.data_source,
        idempotency_key="recommend-external",
    )
    result = service.handle_external_occupancy(
        journey_id=first.journey.journey_id,
        expected_version=first.journey.version,
        replacement_journey_id="journey-external-new",
        replacement_attempt_id="attempt-external-new",
        replacement_request_id="request-external-new",
        layout=bundle.layout,
        costs=bundle.cost_snapshot,
        data_source=bundle.parking_lot.data_source,
        idempotency_key="external-occupied",
    )
    replay = service.handle_external_occupancy(
        journey_id=first.journey.journey_id,
        expected_version=first.journey.version,
        replacement_journey_id="journey-external-new",
        replacement_attempt_id="attempt-external-new",
        replacement_request_id="request-external-new",
        layout=bundle.layout,
        costs=bundle.cost_snapshot,
        data_source=bundle.parking_lot.data_source,
        idempotency_key="external-occupied",
    )
    assert replay == result
    assert result.failed_journey.state is JourneyState.FAILED
    assert result.failed_journey.terminal_reason == "EXTERNAL_SPACE_OCCUPIED"
    assert result.replacement.journey.journey_id == "journey-external-new"
    assert result.replacement.journey.space_id != first.journey.space_id
    excluded = next(
        item
        for item in result.replacement.recommendation.assessments
        if item.space_id == first.journey.space_id
    )
    assert "EXTERNAL_SPACE_OCCUPIED" in excluded.reason_codes
    assert len(store.active_claims()) == 1
    assert store.active_claims()[0].journey_id == "journey-external-new"
    cancelled = store.cancel(
        journey_id=result.replacement.journey.journey_id,
        expected_version=result.replacement.journey.version,
        idempotency_key="cancel-external-replacement",
    )
    later = service.recommend_and_hold(
        driver=_driver("request-external-later"),
        namespace=SessionNamespace.DRIVER,
        scenario_id=bundle.scenario_id,
        journey_id="journey-external-later",
        attempt_id="attempt-external-later",
        layout=bundle.layout,
        costs=bundle.cost_snapshot,
        data_source=bundle.parking_lot.data_source,
        idempotency_key="recommend-external-later",
    )
    assert cancelled.state is JourneyState.CANCELLED
    assert later.journey.space_id != first.journey.space_id


def test_external_occupancy_after_expiry_creates_no_replacement() -> None:
    bundle = built_in_scenarios()["school-demo"]
    store, elapsed = _clocked_store()
    service = _service(store)
    first = service.recommend_and_hold(
        driver=_driver("request-external-expiry"),
        namespace=SessionNamespace.DRIVER,
        scenario_id=bundle.scenario_id,
        journey_id="journey-external-expiry",
        attempt_id="attempt-external-expiry",
        layout=bundle.layout,
        costs=bundle.cost_snapshot,
        data_source=bundle.parking_lot.data_source,
        idempotency_key="recommend-external-expiry",
    )
    elapsed[0] = 30.0
    with pytest.raises(IllegalTransitionError):
        service.handle_external_occupancy(
            journey_id=first.journey.journey_id,
            expected_version=first.journey.version,
            replacement_journey_id="journey-external-expiry-new",
            replacement_attempt_id="attempt-external-expiry-new",
            replacement_request_id="request-external-expiry-new",
            layout=bundle.layout,
            costs=bundle.cost_snapshot,
            data_source=bundle.parking_lot.data_source,
            idempotency_key="external-expiry",
        )
    assert store.get_journey(first.journey.journey_id).state is JourneyState.EXPIRED
    assert store.get_journey("journey-external-expiry-new") is None
    assert store.unavailable_space_reasons(
        session_id=first.journey.session_id,
        namespace=first.journey.namespace,
        scenario_id=first.journey.scenario_id,
        parking_lot_id=first.journey.parking_lot_id,
    ) == {}
