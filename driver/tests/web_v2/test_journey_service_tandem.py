from __future__ import annotations
from parking_opt.api.models import CostSnapshot
from parking_opt.api.scenarios import built_in_scenarios
from parking_opt.api.sessions import JourneyState, SessionNamespace
from journey_fixtures import _driver, _service, _store
def test_success_exposes_at_most_one_alternative_and_tandem_prefers_independent() -> None:
    bundle = built_in_scenarios()["school-demo"]
    store = _store()
    service = _service(store)
    for index, space_id in enumerate(("C-01", "A-02", "A-03"), start=1):
        store.soft_hold(session_id="defense-alternative", namespace=SessionNamespace.DEFENSE, scenario_id=bundle.scenario_id, parking_lot_id=bundle.parking_lot.parking_lot_id, journey_id=f"occupied-ranking-{index}", attempt_id=f"occupied-ranking-{index}", space_id=space_id, idempotency_key=f"occupied-ranking-{index}")
    result = service.recommend_and_hold(
        driver=_driver("request-tandem-alternative", session_id="defense-alternative"),
        namespace=SessionNamespace.DEFENSE,
        scenario_id=bundle.scenario_id,
        journey_id="journey-tandem-alternative",
        attempt_id="attempt-tandem-alternative",
        layout=bundle.layout,
        costs=bundle.cost_snapshot,
        data_source=bundle.parking_lot.data_source,
        idempotency_key="recommend-tandem-alternative",
    )
    tandem_ids = {
        space_id for group in bundle.layout.tandem_groups for space_id in group.space_ids_near_to_deep
    }
    assert result.recommendation.recommended_space_id in tandem_ids
    assert result.recommendation.alternative_space_ids == ()
def test_tandem_primary_selects_independent_alternative_when_one_is_feasible() -> None:
    bundle = built_in_scenarios()["school-demo"]
    costs = CostSnapshot.model_validate(
        {
            **bundle.cost_snapshot.model_dump(),
            "cost_version": "cost-tandem-primary",
            "edge_travel_time_s": {
                **bundle.cost_snapshot.edge_travel_time_s,
                "edge-junction-a": 100.0,
                "edge-junction-b": 1.0,
            },
        }
    )
    store = _store()
    for index, space_id in enumerate(("C-01", "A-02"), start=1):
        store.soft_hold(session_id="defense-normal-alt", namespace=SessionNamespace.DEFENSE, scenario_id=bundle.scenario_id, parking_lot_id=bundle.parking_lot.parking_lot_id, journey_id=f"block-primary-{index}", attempt_id=f"block-primary-{index}", space_id=space_id, idempotency_key=f"block-primary-{index}")
    result = _service(store).recommend_and_hold(
        driver=_driver("request-tandem-normal-alt", session_id="defense-normal-alt"),
        namespace=SessionNamespace.DEFENSE,
        scenario_id=bundle.scenario_id,
        journey_id="journey-tandem-normal-alt",
        attempt_id="attempt-tandem-normal-alt",
        layout=bundle.layout,
        costs=costs,
        data_source=bundle.parking_lot.data_source,
        idempotency_key="recommend-tandem-normal-alt",
    )
    assert result.recommendation.recommended_space_id == "B-03"
    assert result.recommendation.alternative_space_ids == ("A-03",)
def test_declined_tandem_exclusion_survives_waiting_retry() -> None:
    bundle = built_in_scenarios()["school-demo"]
    store = _store()
    service = _service(store)
    for index, space_id in enumerate(("C-01", "A-02", "A-03"), start=1):
        store.soft_hold(session_id="defense-decline-wait", namespace=SessionNamespace.DEFENSE, scenario_id=bundle.scenario_id, parking_lot_id=bundle.parking_lot.parking_lot_id, journey_id=f"block-normal-{index}", attempt_id=f"block-normal-{index}", space_id=space_id, idempotency_key=f"block-normal-{index}")
    first = service.recommend_and_hold(
        driver=_driver("request-decline-wait", session_id="defense-decline-wait"),
        namespace=SessionNamespace.DEFENSE,
        scenario_id=bundle.scenario_id,
        journey_id="journey-decline-wait",
        attempt_id="attempt-decline-wait",
        layout=bundle.layout,
        costs=bundle.cost_snapshot,
        data_source=bundle.parking_lot.data_source,
        idempotency_key="recommend-decline-wait",
    )
    assert first.journey.space_id is not None
    rejected_space = first.journey.space_id
    for index, space_id in enumerate(("B-02", "B-03", "B-04"), start=1):
        if space_id == rejected_space:
            continue
        store.soft_hold(session_id="defense-decline-wait", namespace=SessionNamespace.DEFENSE, scenario_id=bundle.scenario_id, parking_lot_id=bundle.parking_lot.parking_lot_id, journey_id=f"block-tandem-{index}", attempt_id=f"block-tandem-{index}", space_id=space_id, idempotency_key=f"block-tandem-{index}")
    declined = service.decline_tandem_and_recommend(
        journey_id=first.journey.journey_id,
        expected_version=first.journey.version,
        replacement_journey_id="journey-decline-wait-next",
        replacement_attempt_id="attempt-decline-wait-next",
        replacement_request_id="request-decline-wait-next",
        layout=bundle.layout,
        costs=bundle.cost_snapshot,
        data_source=bundle.parking_lot.data_source,
        idempotency_key="decline-wait",
    )
    assert declined.replacement.journey.state is JourneyState.WAITING
    retried = service.retry_waiting(
        journey_id=declined.replacement.journey.journey_id,
        expected_version=declined.replacement.journey.version,
        layout=bundle.layout,
        costs=bundle.cost_snapshot,
        data_source=bundle.parking_lot.data_source,
        idempotency_key="retry-decline-wait",
    )
    assessment = next(item for item in retried.recommendation.assessments if item.space_id == rejected_space)
    assert "USER_DECLINED_TANDEM" in assessment.reason_codes
    assert retried.journey.state is JourneyState.WAITING
def test_consecutive_tandem_declines_accumulate_history_and_replay() -> None:
    bundle = built_in_scenarios()["school-demo"]
    store = _store()
    service = _service(store)
    for index, space_id in enumerate(("C-01", "A-02", "A-03"), start=1):
        store.soft_hold(session_id="defense-double-decline", namespace=SessionNamespace.DEFENSE, scenario_id=bundle.scenario_id, parking_lot_id=bundle.parking_lot.parking_lot_id, journey_id=f"block-double-{index}", attempt_id=f"block-double-{index}", space_id=space_id, idempotency_key=f"block-double-{index}")
    first = service.recommend_and_hold(
        driver=_driver("request-double-decline", session_id="defense-double-decline"),
        namespace=SessionNamespace.DEFENSE,
        scenario_id=bundle.scenario_id,
        journey_id="journey-double-decline-1",
        attempt_id="attempt-double-decline-1",
        layout=bundle.layout,
        costs=bundle.cost_snapshot,
        data_source=bundle.parking_lot.data_source,
        idempotency_key="recommend-double-decline",
    )
    first_rejected = first.journey.space_id
    assert first_rejected is not None
    second = service.decline_tandem_and_recommend(
        journey_id=first.journey.journey_id,
        expected_version=first.journey.version,
        replacement_journey_id="journey-double-decline-2",
        replacement_attempt_id="attempt-double-decline-2",
        replacement_request_id="request-double-decline-2",
        layout=bundle.layout,
        costs=bundle.cost_snapshot,
        data_source=bundle.parking_lot.data_source,
        idempotency_key="decline-double-1",
    )
    second_rejected = second.replacement.journey.space_id
    assert second_rejected is not None and second_rejected != first_rejected
    third = service.decline_tandem_and_recommend(
        journey_id=second.replacement.journey.journey_id,
        expected_version=second.replacement.journey.version,
        replacement_journey_id="journey-double-decline-3",
        replacement_attempt_id="attempt-double-decline-3",
        replacement_request_id="request-double-decline-3",
        layout=bundle.layout,
        costs=bundle.cost_snapshot,
        data_source=bundle.parking_lot.data_source,
        idempotency_key="decline-double-2",
    )
    rejected_assessments = {
        item.space_id: item.reason_codes
        for item in third.replacement.recommendation.assessments
        if item.space_id in {first_rejected, second_rejected}
    }
    assert set(rejected_assessments) == {first_rejected, second_rejected}
    assert all("USER_DECLINED_TANDEM" in reasons for reasons in rejected_assessments.values())
    replay = service.decline_tandem_and_recommend(
        journey_id=second.replacement.journey.journey_id,
        expected_version=second.replacement.journey.version,
        replacement_journey_id="journey-double-decline-3",
        replacement_attempt_id="attempt-double-decline-3",
        replacement_request_id="request-double-decline-3",
        layout=bundle.layout,
        costs=bundle.cost_snapshot,
        data_source=bundle.parking_lot.data_source,
        idempotency_key="decline-double-2",
    )
    assert replay == third
