"""Replan, occupancy, and terminal-journey command routes for web-v2."""
from __future__ import annotations
from fastapi import FastAPI, Request
from parking_opt.api.app_contracts import ERROR_RESPONSES, SessionIdHeader
from parking_opt.api.app_helpers import (
    apply_command,
    get_journey_bundle,
    require_driver_session,
    require_synthetic_driver_demo,
)
from parking_opt.api.facility_scenarios import PublicFacilityDataSource
from parking_opt.api.models import (
    DriverDemoReplanRequest,
    ExternalOccupancyRequest,
    ExternalOccupancyResponse,
    Journey,
    JourneyCommandRequest,
    JourneyReassignmentRequest,
    JourneyReassignmentResponse,
    JourneyRecommendationResponse,
    JourneyReplanRequest,
    JourneyReplanResponse,
)
from parking_opt.api.services.journey import JourneyRecommendationService, journey_to_contract
from parking_opt.api.services.replanning import JourneyReplanService
from parking_opt.api.sessions import InMemorySessionStore, JourneyNotFoundError
def register_replan_routes(app: FastAPI) -> None:
    @app.post("/api/v2/journeys/{journey_id}/replan", response_model=JourneyReplanResponse, responses={404: ERROR_RESPONSES[404], 409: ERROR_RESPONSES[409], 503: ERROR_RESPONSES[503]}, tags=["journeys"])
    def replan_journey(
        journey_id: str,
        payload: JourneyReplanRequest,
        request: Request,
        session_id: SessionIdHeader = None,
    ) -> JourneyReplanResponse:
        service: JourneyReplanService = request.app.state.replan_service
        record, bundle = get_journey_bundle(journey_id, request)
        require_driver_session(record, session_id)
        result = service.replan(
            journey_id=journey_id,
            expected_version=payload.expected_version,
            current_node_id=payload.current_node_id,
            trigger=payload.trigger,
            layout=bundle.layout,
            channel_load=payload.channel_load,
            idempotency_key=payload.idempotency_key,
        )
        return JourneyReplanResponse(journey=journey_to_contract(result.journey), decision=result.decision)
    @app.post("/api/v2/journeys/{journey_id}/driver-demo-replan", response_model=JourneyReplanResponse, responses={404: ERROR_RESPONSES[404], 409: ERROR_RESPONSES[409], 503: ERROR_RESPONSES[503]}, tags=["journeys"])
    def driver_demo_replan(
        journey_id: str,
        payload: DriverDemoReplanRequest,
        request: Request,
        session_id: SessionIdHeader = None,
    ) -> JourneyReplanResponse:
        service: JourneyReplanService = request.app.state.replan_service
        record, bundle = get_journey_bundle(journey_id, request)
        require_driver_session(record, session_id)
        require_synthetic_driver_demo(record, bundle, request)
        result = service.driver_demo_replan(
            journey_id=journey_id,
            expected_version=payload.expected_version,
            action=payload.action,
            layout=bundle.layout,
            idempotency_key=payload.idempotency_key,
        )
        return JourneyReplanResponse(journey=journey_to_contract(result.journey), decision=result.decision)
    @app.post("/api/v2/journeys/{journey_id}/report-external-occupancy", response_model=ExternalOccupancyResponse, responses={404: ERROR_RESPONSES[404], 409: ERROR_RESPONSES[409], 503: ERROR_RESPONSES[503]}, tags=["journeys"])
    def report_external_occupancy(
        journey_id: str,
        payload: ExternalOccupancyRequest,
        request: Request,
        session_id: SessionIdHeader = None,
    ) -> ExternalOccupancyResponse:
        service: JourneyRecommendationService = request.app.state.journey_service
        record, bundle = get_journey_bundle(journey_id, request)
        require_driver_session(record, session_id)
        result = service.handle_external_occupancy(
            journey_id=journey_id,
            expected_version=payload.expected_version,
            replacement_journey_id=payload.replacement_journey_id,
            replacement_attempt_id=payload.replacement_attempt_id,
            replacement_request_id=payload.replacement_request_id,
            layout=bundle.layout,
            costs=bundle.cost_snapshot,
            data_source=bundle.parking_lot.data_source,
            idempotency_key=payload.idempotency_key,
        )
        if result.replacement.recommendation.route is not None:
            request.app.state.replan_service.register_route(result.replacement.journey.journey_id, result.replacement.recommendation.route)
        return ExternalOccupancyResponse(
            failed_journey=journey_to_contract(result.failed_journey),
            replacement=JourneyRecommendationResponse(
                recommendation=result.replacement.recommendation,
                journey=journey_to_contract(result.replacement.journey, recommendation_id=result.replacement.recommendation.recommendation_id),
            ),
        )
    @app.post("/api/v2/journeys/{journey_id}/occupy", response_model=Journey, responses={404: ERROR_RESPONSES[404], 409: ERROR_RESPONSES[409]}, tags=["journeys"])
    def occupy_journey(
        journey_id: str,
        payload: JourneyCommandRequest,
        request: Request,
        session_id: SessionIdHeader = None,
    ) -> Journey:
        return apply_command("occupy", journey_id, payload, request, session_id)
    @app.post("/api/v2/journeys/{journey_id}/cancel", response_model=Journey, responses={404: ERROR_RESPONSES[404], 409: ERROR_RESPONSES[409]}, tags=["journeys"])
    def cancel_journey(
        journey_id: str,
        payload: JourneyCommandRequest,
        request: Request,
        session_id: SessionIdHeader = None,
    ) -> Journey:
        record = request.app.state.session_store.refresh_journey(journey_id)
        if record is None:
            raise JourneyNotFoundError(f"unknown journey: {journey_id}")
        require_driver_session(record, session_id)
        return apply_command("cancel", journey_id, payload, request)
    @app.post("/api/v2/journeys/{journey_id}/depart", response_model=Journey, responses={404: ERROR_RESPONSES[404], 409: ERROR_RESPONSES[409]}, tags=["journeys"])
    def depart_journey(
        journey_id: str,
        payload: JourneyCommandRequest,
        request: Request,
        session_id: SessionIdHeader = None,
    ) -> Journey:
        store: InMemorySessionStore = request.app.state.session_store
        with store.atomic():
            result = apply_command("depart", journey_id, payload, request, session_id)
            source = request.app.state.public_source
            if isinstance(source, PublicFacilityDataSource):
                store.advance_driver_demo_profile_after_terminal(journey_id=journey_id, profile_count=source.driver_demo_profile_count(result.parking_lot_id))
            return result
    @app.post("/api/v2/journeys/{journey_id}/reset-demo", response_model=Journey, responses={404: ERROR_RESPONSES[404], 409: ERROR_RESPONSES[409]}, tags=["journeys"])
    def reset_demo(
        journey_id: str,
        payload: JourneyCommandRequest,
        request: Request,
        session_id: SessionIdHeader = None,
    ) -> Journey:
        store: InMemorySessionStore = request.app.state.session_store
        record = store.refresh_journey(journey_id)
        if record is None:
            raise JourneyNotFoundError(f"unknown journey: {journey_id}")
        require_driver_session(record, session_id)
        _, bundle = get_journey_bundle(journey_id, request)
        require_synthetic_driver_demo(record, bundle, request)
        with store.atomic():
            result = store.reset_demo(journey_id=journey_id, expected_version=payload.expected_version, idempotency_key=payload.idempotency_key)
            source = request.app.state.public_source
            if isinstance(source, PublicFacilityDataSource):
                store.advance_driver_demo_profile_after_terminal(journey_id=journey_id, profile_count=source.driver_demo_profile_count(result.parking_lot_id))
            return journey_to_contract(result)
    @app.post("/api/v2/journeys/{journey_id}/reassign", response_model=JourneyReassignmentResponse, responses={404: ERROR_RESPONSES[404], 409: ERROR_RESPONSES[409], 503: ERROR_RESPONSES[503]}, tags=["journeys"])
    def reassign_journey(
        journey_id: str,
        payload: JourneyReassignmentRequest,
        request: Request,
        session_id: SessionIdHeader = None,
    ) -> JourneyReassignmentResponse:
        service: JourneyRecommendationService = request.app.state.journey_service
        record, bundle = get_journey_bundle(journey_id, request)
        require_driver_session(record, session_id)
        result = service.reassign_after_driver_issue(
            journey_id=journey_id,
            expected_version=payload.expected_version,
            reason=payload.reason,
            replacement_journey_id=payload.replacement_journey_id,
            replacement_attempt_id=payload.replacement_attempt_id,
            replacement_request_id=payload.replacement_request_id,
            layout=bundle.layout,
            costs=bundle.cost_snapshot,
            data_source=bundle.parking_lot.data_source,
            idempotency_key=payload.idempotency_key,
        )
        if result.replacement.recommendation.route is not None:
            request.app.state.replan_service.register_route(result.replacement.journey.journey_id, result.replacement.recommendation.route)
        return JourneyReassignmentResponse(
            ended_journey=journey_to_contract(result.ended_journey),
            replacement=JourneyRecommendationResponse(
                recommendation=result.replacement.recommendation,
                journey=journey_to_contract(result.replacement.journey, recommendation_id=result.replacement.recommendation.recommendation_id),
            ),
        )
