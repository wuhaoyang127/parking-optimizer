from __future__ import annotations

from parking_opt.api.models import CostSnapshot
from parking_opt.api.scenarios import built_in_scenarios
from parking_opt.api.sessions import JourneyState, SessionNamespace
from journey_fixtures import _driver, _service, _store


def test_successful_recommendation_is_returned_only_after_soft_hold() -> None:
    bundle = built_in_scenarios()["school-demo"]
    store = _store()
    result = _service(store).recommend_and_hold(
        driver=_driver("request-hold"),
        namespace=SessionNamespace.DRIVER,
        scenario_id=bundle.scenario_id,
        journey_id="journey-hold",
        attempt_id="attempt-hold",
        layout=bundle.layout,
        costs=bundle.cost_snapshot,
        data_source=bundle.parking_lot.data_source,
        idempotency_key="recommend-hold",
    )
    assert result.recommendation.solver_status == "success"
    assert result.journey.state is JourneyState.SOFT_HELD
    assert result.journey.space_id == result.recommendation.recommended_space_id
    assert result.recommendation.claim_status == "soft_held"
    assert result.recommendation.soft_lock_expires_at == result.journey.expires_at
    assert store.active_claims()[0].journey_id == result.journey.journey_id


def test_claimed_space_is_projected_out_for_next_vehicle_in_same_scene_copy() -> None:
    bundle = built_in_scenarios()["school-demo"]
    store = _store()
    service = _service(store)
    first = service.recommend_and_hold(
        driver=_driver("request-first", session_id="defense-session"),
        namespace=SessionNamespace.DEFENSE,
        scenario_id=bundle.scenario_id,
        journey_id="journey-first",
        attempt_id="attempt-first",
        layout=bundle.layout,
        costs=bundle.cost_snapshot,
        data_source=bundle.parking_lot.data_source,
        idempotency_key="recommend-first",
    )
    second = service.recommend_and_hold(
        driver=_driver("request-second", session_id="defense-session"),
        namespace=SessionNamespace.DEFENSE,
        scenario_id=bundle.scenario_id,
        journey_id="journey-second",
        attempt_id="attempt-second",
        layout=bundle.layout,
        costs=bundle.cost_snapshot,
        data_source=bundle.parking_lot.data_source,
        idempotency_key="recommend-second",
    )
    assert first.journey.space_id != second.journey.space_id
    excluded = next(
        item for item in second.recommendation.assessments if item.space_id == first.journey.space_id
    )
    assert excluded.feasible is False
    assert "APPLICATION_CLAIMED" in excluded.reason_codes


def test_eta_safety_margin_filters_candidates_and_enters_waiting() -> None:
    bundle = built_in_scenarios()["school-demo"]
    costs = CostSnapshot(
        parking_lot_id=bundle.parking_lot.parking_lot_id,
        layout_version=bundle.layout.layout_version,
        cost_version="cost-too-slow",
        observed_at=bundle.cost_snapshot.observed_at,
        edge_travel_time_s={key: 300.0 for key in bundle.cost_snapshot.edge_travel_time_s},
    )
    result = _service(_store()).recommend_and_hold(
        driver=_driver("request-wait"),
        namespace=SessionNamespace.DRIVER,
        scenario_id=bundle.scenario_id,
        journey_id="journey-wait",
        attempt_id="attempt-wait",
        layout=bundle.layout,
        costs=costs,
        data_source=bundle.parking_lot.data_source,
        idempotency_key="recommend-wait",
    )
    assert result.recommendation.solver_status == "no_feasible_space"
    assert result.journey.state is JourneyState.WAITING
    assert result.journey.space_id is None
    routed = [item for item in result.recommendation.assessments if item.dynamic_eta_s is not None]
    assert routed
    assert all("ETA_EXCEEDS_RESERVATION" in item.reason_codes for item in routed)


def test_recommend_and_hold_replays_identical_result() -> None:
    bundle = built_in_scenarios()["school-demo"]
    store = _store()
    service = _service(store)
    kwargs = {
        "driver": _driver("request-replay"),
        "namespace": SessionNamespace.DRIVER,
        "scenario_id": bundle.scenario_id,
        "journey_id": "journey-replay",
        "attempt_id": "attempt-replay",
        "layout": bundle.layout,
        "costs": bundle.cost_snapshot,
        "data_source": bundle.parking_lot.data_source,
        "idempotency_key": "recommend-replay",
    }
    first = service.recommend_and_hold(**kwargs)
    replay = service.recommend_and_hold(**kwargs)
    assert replay == first
    assert len(store.events()) == 1


def test_select_alternative_switches_claim_and_route_consistently() -> None:
    bundle = built_in_scenarios()["school-demo"]
    store = _store()
    service = _service(store)
    first = service.recommend_and_hold(
        driver=_driver("request-switch"),
        namespace=SessionNamespace.DRIVER,
        scenario_id=bundle.scenario_id,
        journey_id="journey-switch",
        attempt_id="attempt-switch",
        layout=bundle.layout,
        costs=bundle.cost_snapshot,
        data_source=bundle.parking_lot.data_source,
        idempotency_key="recommend-switch",
    )
    alternative = first.recommendation.alternative_space_ids[0]
    switched = service.select_alternative(
        journey_id=first.journey.journey_id,
        space_id=alternative,
        expected_version=first.journey.version,
        layout=bundle.layout,
        costs=bundle.cost_snapshot,
        idempotency_key="select-alternative",
    )
    assert switched.journey.space_id == alternative
    assert switched.recommendation.recommended_space_id == alternative
    assert switched.recommendation.route is not None
    space = next(item for item in bundle.layout.spaces if item.space_id == alternative)
    assert switched.recommendation.route.to_node_id == space.access_node_id
    assert switched.recommendation.soft_lock_expires_at == first.journey.expires_at
    assert store.active_claims()[0].space_id == alternative
