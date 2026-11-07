from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from parking_opt.api.adapters.v1 import V1OnlineRuleAdapter
from parking_opt.api.models import CostSnapshot, DriverRequest
from parking_opt.api.routing import RouteCostService
from parking_opt.api.scenarios import built_in_scenarios
from parking_opt.api.services.journey import JourneyRecommendationService
from parking_opt.api.services.online_rule import OnlineRuleServiceV2
from parking_opt.api.sessions import (
    ActiveJourneyConflictError,
    IdempotencyConflictError,
    IllegalTransitionError,
    InMemorySessionStore,
    JourneyState,
    SessionNamespace,
    SessionTiming,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _store() -> InMemorySessionStore:
    return InMemorySessionStore(
        timing=SessionTiming(
            driver_idle_ttl_s=1800,
            defense_idle_ttl_s=7200,
            soft_hold_ttl_s=30,
            driver_reservation_ttl_s=300,
            defense_reservation_ttl_s=60,
        )
    )


def _clocked_store() -> tuple[InMemorySessionStore, list[float]]:
    elapsed = [0.0]
    origin = datetime(2026, 8, 13, tzinfo=UTC)
    return (
        InMemorySessionStore(
            timing=SessionTiming(
                driver_idle_ttl_s=1800,
                defense_idle_ttl_s=7200,
                soft_hold_ttl_s=30,
                driver_reservation_ttl_s=300,
                defense_reservation_ttl_s=60,
            ),
            monotonic_clock=lambda: elapsed[0],
            utc_clock=lambda: origin + timedelta(seconds=elapsed[0]),
        ),
        elapsed,
    )


def _service(store: InMemorySessionStore) -> JourneyRecommendationService:
    routes = RouteCostService()
    online = OnlineRuleServiceV2(
        v1_adapter=V1OnlineRuleAdapter(
            schema_dir=REPO_ROOT / "schemas" / "v1",
            route_service=routes,
        ),
        route_service=routes,
    )
    return JourneyRecommendationService(
        online_rule=online,
        route_service=routes,
        session_store=store,
        eta_safety_margin_s=60,
        driver_reservation_ttl_s=300,
    )


def _driver(request_id: str, *, session_id: str = "session-1") -> DriverRequest:
    return DriverRequest(
        request_id=request_id,
        idempotency_key=f"idem-{request_id}",
        session_id=session_id,
        parking_lot_id="lot-school",
        entrance_node_id="entry",
        requested_at=datetime(2026, 8, 13, tzinfo=UTC),
    )


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
        item
        for item in second.recommendation.assessments
        if item.space_id == first.journey.space_id
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
    routed = [
        item for item in result.recommendation.assessments if item.dynamic_eta_s is not None
    ]
    assert routed
    assert all(
        "ETA_EXCEEDS_RESERVATION" in item.reason_codes
        for item in routed
    )


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


def test_success_exposes_at_most_one_alternative_and_tandem_prefers_independent() -> None:
    bundle = built_in_scenarios()["school-demo"]
    store = _store()
    service = _service(store)
    for index, space_id in enumerate(("C-01", "A-02", "A-03"), start=1):
        store.soft_hold(
            session_id="defense-alternative",
            namespace=SessionNamespace.DEFENSE,
            scenario_id=bundle.scenario_id,
            parking_lot_id=bundle.parking_lot.parking_lot_id,
            journey_id=f"occupied-ranking-{index}",
            attempt_id=f"occupied-ranking-{index}",
            space_id=space_id,
            idempotency_key=f"occupied-ranking-{index}",
        )
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
        space_id
        for group in bundle.layout.tandem_groups
        for space_id in group.space_ids_near_to_deep
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
        store.soft_hold(
            session_id="defense-normal-alt",
            namespace=SessionNamespace.DEFENSE,
            scenario_id=bundle.scenario_id,
            parking_lot_id=bundle.parking_lot.parking_lot_id,
            journey_id=f"block-primary-{index}",
            attempt_id=f"block-primary-{index}",
            space_id=space_id,
            idempotency_key=f"block-primary-{index}",
        )
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
        store.soft_hold(
            session_id="defense-decline-wait",
            namespace=SessionNamespace.DEFENSE,
            scenario_id=bundle.scenario_id,
            parking_lot_id=bundle.parking_lot.parking_lot_id,
            journey_id=f"block-normal-{index}",
            attempt_id=f"block-normal-{index}",
            space_id=space_id,
            idempotency_key=f"block-normal-{index}",
        )
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
        store.soft_hold(
            session_id="defense-decline-wait",
            namespace=SessionNamespace.DEFENSE,
            scenario_id=bundle.scenario_id,
            parking_lot_id=bundle.parking_lot.parking_lot_id,
            journey_id=f"block-tandem-{index}",
            attempt_id=f"block-tandem-{index}",
            space_id=space_id,
            idempotency_key=f"block-tandem-{index}",
        )
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
    assessment = next(
        item for item in retried.recommendation.assessments if item.space_id == rejected_space
    )
    assert "USER_DECLINED_TANDEM" in assessment.reason_codes
    assert retried.journey.state is JourneyState.WAITING


def test_consecutive_tandem_declines_accumulate_history_and_replay() -> None:
    bundle = built_in_scenarios()["school-demo"]
    store = _store()
    service = _service(store)
    for index, space_id in enumerate(("C-01", "A-02", "A-03"), start=1):
        store.soft_hold(
            session_id="defense-double-decline",
            namespace=SessionNamespace.DEFENSE,
            scenario_id=bundle.scenario_id,
            parking_lot_id=bundle.parking_lot.parking_lot_id,
            journey_id=f"block-double-{index}",
            attempt_id=f"block-double-{index}",
            space_id=space_id,
            idempotency_key=f"block-double-{index}",
        )
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
    reserved = store.confirm(
        journey_id=first.journey.journey_id,
        accepted=True,
        expected_version=first.journey.version,
        idempotency_key=f"confirm-reassign-{reason}-1",
    )
    navigating = store.start_navigation(
        journey_id=reserved.journey_id,
        expected_version=reserved.version,
        idempotency_key=f"navigate-reassign-{reason}-1",
    )
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
        service.reassign_after_driver_issue(
            **{**kwargs, "replacement_request_id": "changed-request"}
        )

    assert replacement.replacement.journey.state is JourneyState.SOFT_HELD
    reserved_2 = store.confirm(
        journey_id=replacement.replacement.journey.journey_id,
        accepted=True,
        expected_version=replacement.replacement.journey.version,
        idempotency_key=f"confirm-reassign-{reason}-2",
    )
    navigating_2 = store.start_navigation(
        journey_id=reserved_2.journey_id,
        expected_version=reserved_2.version,
        idempotency_key=f"navigate-reassign-{reason}-2",
    )
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
        item.space_id: item.reason_codes
        for item in second.replacement.recommendation.assessments
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
    reserved = store.confirm(
        journey_id=first.journey.journey_id,
        accepted=True,
        expected_version=first.journey.version,
        idempotency_key="confirm-reassign-waiting",
    )
    navigating = store.start_navigation(
        journey_id=reserved.journey_id,
        expected_version=reserved.version,
        idempotency_key="navigate-reassign-waiting",
    )
    constrained_layout = bundle.layout.model_copy(
        update={
            "spaces": tuple(
                space
                if space.space_id == first.journey.space_id
                else space.model_copy(
                    update={
                        "status": "occupied",
                        "assignable": False,
                        "assignability_reasons": ("SPACE_OCCUPIED",),
                    }
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
