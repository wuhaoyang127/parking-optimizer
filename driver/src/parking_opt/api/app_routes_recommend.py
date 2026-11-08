"""Journey recommendation and driver-context routes for web-v2."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request, Response

from parking_opt.api.app_contracts import (
    ERROR_RESPONSES,
    RequiredSessionIdHeader,
    SessionIdHeader,
)
from parking_opt.api.app_helpers import driver_bundle
from parking_opt.api.facility import FacilityDataUnavailableError, FacilityNotFoundError, FacilityVersionConflictError
from parking_opt.api.facility_scenarios import PublicFacilityDataSource
from parking_opt.api.models import (
    DataMode,
    DriverDemoProfileAdvanceRequest,
    DriverDemoProfileAdvanceResponse,
    DriverEntrance,
    DriverJourneySnapshot,
    DriverRecommendationContext,
    Journey,
    JourneyRecommendationRequest,
    JourneyRecommendationResponse,
)
from parking_opt.api.registry import require_online_algorithm
from parking_opt.api.services.journey import JourneyRecommendationService, journey_to_contract
from parking_opt.api.sessions import InMemorySessionStore, JourneyNotFoundError, SessionNamespace
from parking_opt.api.sources import ParkingDataSource, ParkingDataUnavailableError, ParkingLotNotFoundError


def register_recommend_routes(app: FastAPI) -> None:
    @app.post(
        "/api/v2/journeys/recommendations",
        response_model=JourneyRecommendationResponse,
        responses={404: ERROR_RESPONSES[404], 409: ERROR_RESPONSES[409], 422: ERROR_RESPONSES[422], 503: ERROR_RESPONSES[503]},
        tags=["journeys"],
    )
    def recommend_journey(
        payload: JourneyRecommendationRequest,
        request: Request,
        session_id: SessionIdHeader = None,
    ) -> JourneyRecommendationResponse:
        source: ParkingDataSource = request.app.state.data_source
        service: JourneyRecommendationService = request.app.state.journey_service
        require_online_algorithm(payload.algorithm_id)
        if session_id is not None and (payload.namespace != "driver" or payload.driver.session_id != session_id):
            raise HTTPException(status_code=409, detail="session header does not match driver request")
        try:
            bundle = driver_bundle(source, payload.driver.parking_lot_id, payload.driver.session_id if payload.namespace == "driver" else None)
        except ParkingLotNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ParkingDataUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if payload.scenario_id != bundle.scenario_id:
            raise HTTPException(status_code=409, detail="scenario_id does not match parking lot")
        store: InMemorySessionStore = request.app.state.session_store
        with store.atomic():
            bundle = driver_bundle(source, payload.driver.parking_lot_id, payload.driver.session_id if payload.namespace == "driver" else None)
            if payload.scenario_id != bundle.scenario_id:
                raise HTTPException(status_code=409, detail="scenario_id does not match parking lot")
            result = service.recommend_and_hold(
                driver=payload.driver,
                namespace=SessionNamespace(payload.namespace),
                scenario_id=payload.scenario_id,
                journey_id=payload.journey_id,
                attempt_id=payload.attempt_id,
                layout=bundle.layout,
                costs=bundle.cost_snapshot,
                data_source=bundle.parking_lot.data_source,
                idempotency_key=payload.idempotency_key,
            )
        replan_service = request.app.state.replan_service
        if result.recommendation.route is not None:
            replan_service.register_route(result.journey.journey_id, result.recommendation.route)
        return JourneyRecommendationResponse(
            recommendation=result.recommendation,
            journey=journey_to_contract(result.journey, recommendation_id=result.recommendation.recommendation_id),
        )

    @app.get(
        "/api/v2/parking-lots/{parking_lot_id}/driver-context",
        response_model=DriverRecommendationContext,
        responses={404: ERROR_RESPONSES[404], 503: ERROR_RESPONSES[503]},
        tags=["journeys"],
    )
    def driver_recommendation_context(
        parking_lot_id: str,
        request: Request,
        response: Response,
        session_id: SessionIdHeader = None,
    ) -> DriverRecommendationContext:
        response.headers["Cache-Control"] = "no-store"
        response.headers["Vary"] = "X-Session-ID"
        source: ParkingDataSource = request.app.state.data_source
        try:
            bundle = driver_bundle(source, parking_lot_id, session_id)
        except ParkingLotNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ParkingDataUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        nodes = {item.node_id: item for item in bundle.layout.nodes}
        return DriverRecommendationContext(
            observed_at=request.app.state.session_store.current_wall_time(),
            scenario_id=bundle.scenario_id,
            parking_lot_id=parking_lot_id,
            layout_version=bundle.layout.layout_version,
            entrances=tuple(DriverEntrance(node_id=node_id, label=nodes[node_id].label) for node_id in bundle.layout.entrance_node_ids),
            spaces=bundle.layout.spaces,
            tandem_groups=bundle.layout.tandem_groups,
            data_source=bundle.parking_lot.data_source,
            demo_profile=(
                source.get_driver_demo_profile(parking_lot_id, session_id=session_id)
                if session_id is not None and isinstance(source, PublicFacilityDataSource)
                else None
            ),
        )

    @app.post(
        "/api/v2/parking-lots/{parking_lot_id}/driver-demo-profile/advance",
        response_model=DriverDemoProfileAdvanceResponse,
        responses={404: ERROR_RESPONSES[404], 409: ERROR_RESPONSES[409], 422: ERROR_RESPONSES[422], 503: ERROR_RESPONSES[503]},
        tags=["parking-lots"],
    )
    def advance_driver_demo_profile(
        parking_lot_id: str,
        payload: DriverDemoProfileAdvanceRequest,
        request: Request,
        session_id: RequiredSessionIdHeader,
    ) -> DriverDemoProfileAdvanceResponse:
        source = request.app.state.public_source
        if (
            request.app.state.data_mode is not DataMode.SYNTHETIC
            or not isinstance(source, PublicFacilityDataSource)
            or not source.driver_demo_profiles_enabled
        ):
            raise HTTPException(status_code=409, detail="driver demo profiles require the synthetic public source")
        store: InMemorySessionStore = request.app.state.session_store
        try:
            with store.atomic():
                state = source.get_state(parking_lot_id, session_id=session_id)
                expected_index = source.driver_demo_profile_index(parking_lot_id, profile_id=payload.expected_profile_id)
                store.advance_driver_demo_profile(
                    session_id=session_id,
                    parking_lot_id=parking_lot_id,
                    expected_profile_index=expected_index,
                    expected_state_version=payload.expected_state_version,
                    current_state_version=state.state_version,
                    profile_count=source.driver_demo_profile_count(parking_lot_id),
                    idempotency_key=payload.idempotency_key,
                )
                next_state = source.get_state(parking_lot_id, session_id=session_id)
                next_bundle = source.get_driver_bundle(parking_lot_id, session_id=session_id)
                if next_state.demo_profile is None:
                    raise FacilityDataUnavailableError("synthetic driver facility state has no demo profile")
                return DriverDemoProfileAdvanceResponse(demo_profile=next_state.demo_profile, facility_state=next_state, parking_lot=next_bundle.parking_lot)
        except (ParkingLotNotFoundError, FacilityNotFoundError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FacilityVersionConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ParkingDataUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get(
        "/api/v2/driver-session/current-journey",
        response_model=DriverJourneySnapshot,
        responses={422: ERROR_RESPONSES[422]},
        tags=["journeys"],
    )
    def current_driver_journey(
        request: Request,
        response: Response,
        session_id: RequiredSessionIdHeader,
    ) -> DriverJourneySnapshot:
        response.headers["Cache-Control"] = "no-store"
        recovery = request.app.state.journey_service.current_driver_recovery(session_id)
        if recovery is None:
            return DriverJourneySnapshot(observed_at=request.app.state.session_store.current_wall_time())
        return DriverJourneySnapshot(
            observed_at=recovery.observed_at,
            journey=journey_to_contract(recovery.result.journey, recommendation_id=recovery.result.recommendation.recommendation_id),
            recommendation=recovery.result.recommendation,
            driver=recovery.driver,
            waiting_since=(recovery.result.journey.created_at if recovery.result.journey.state.value == "waiting" else None),
        )

    @app.get(
        "/api/v2/journeys/{journey_id}",
        response_model=Journey,
        responses={404: ERROR_RESPONSES[404]},
        tags=["journeys"],
    )
    def get_journey(journey_id: str, request: Request) -> Journey:
        store: InMemorySessionStore = request.app.state.session_store
        record = store.refresh_journey(journey_id)
        if record is None:
            raise JourneyNotFoundError(f"unknown journey: {journey_id}")
        return journey_to_contract(record)
