"""Journey command and alternative-selection routes for web-v2."""

from __future__ import annotations

from fastapi import FastAPI, Request

from parking_opt.api.app_contracts import ERROR_RESPONSES, SessionIdHeader
from parking_opt.api.app_helpers import apply_command, get_journey_bundle, require_driver_session
from parking_opt.api.models import (
    Journey,
    JourneyAlternativeRequest,
    JourneyCommandRequest,
    JourneyConfirmRequest,
    JourneyDeclineRequest,
    JourneyDeclineResponse,
    JourneyRecommendationResponse,
)
from parking_opt.api.services.journey import JourneyRecommendationService, journey_to_contract
from parking_opt.api.sessions import InMemorySessionStore, JourneyNotFoundError


def register_journey_routes(app: FastAPI) -> None:
    @app.post(
        "/api/v2/journeys/{journey_id}/decline-tandem",
        response_model=JourneyDeclineResponse,
        responses={404: ERROR_RESPONSES[404], 409: ERROR_RESPONSES[409], 503: ERROR_RESPONSES[503]},
        tags=["journeys"],
    )
    def decline_tandem(
        journey_id: str,
        payload: JourneyDeclineRequest,
        request: Request,
        session_id: SessionIdHeader = None,
    ) -> JourneyDeclineResponse:
        service: JourneyRecommendationService = request.app.state.journey_service
        record, bundle = get_journey_bundle(journey_id, request)
        require_driver_session(record, session_id)
        result = service.decline_tandem_and_recommend(
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
        return JourneyDeclineResponse(
            declined_journey=journey_to_contract(result.declined_journey),
            replacement=JourneyRecommendationResponse(
                recommendation=result.replacement.recommendation,
                journey=journey_to_contract(result.replacement.journey, recommendation_id=result.replacement.recommendation.recommendation_id),
            ),
        )

    @app.post(
        "/api/v2/journeys/{journey_id}/select-alternative",
        response_model=JourneyRecommendationResponse,
        responses={404: ERROR_RESPONSES[404], 409: ERROR_RESPONSES[409], 503: ERROR_RESPONSES[503]},
        tags=["journeys"],
    )
    def select_alternative(
        journey_id: str,
        payload: JourneyAlternativeRequest,
        request: Request,
        session_id: SessionIdHeader = None,
    ) -> JourneyRecommendationResponse:
        service: JourneyRecommendationService = request.app.state.journey_service
        record, bundle = get_journey_bundle(journey_id, request)
        require_driver_session(record, session_id)
        result = service.select_alternative(
            journey_id=journey_id,
            space_id=payload.space_id,
            expected_version=payload.expected_version,
            layout=bundle.layout,
            costs=bundle.cost_snapshot,
            idempotency_key=payload.idempotency_key,
        )
        assert result.recommendation.route is not None
        request.app.state.replan_service.register_route(result.journey.journey_id, result.recommendation.route)
        return JourneyRecommendationResponse(
            recommendation=result.recommendation,
            journey=journey_to_contract(result.journey, recommendation_id=result.recommendation.recommendation_id),
        )

    @app.post(
        "/api/v2/journeys/{journey_id}/retry-recommendation",
        response_model=JourneyRecommendationResponse,
        responses={404: ERROR_RESPONSES[404], 409: ERROR_RESPONSES[409], 503: ERROR_RESPONSES[503]},
        tags=["journeys"],
    )
    def retry_recommendation(
        journey_id: str,
        payload: JourneyCommandRequest,
        request: Request,
        session_id: SessionIdHeader = None,
    ) -> JourneyRecommendationResponse:
        service: JourneyRecommendationService = request.app.state.journey_service
        record, bundle = get_journey_bundle(journey_id, request)
        require_driver_session(record, session_id)
        result = service.retry_waiting(
            journey_id=journey_id,
            expected_version=payload.expected_version,
            layout=bundle.layout,
            costs=bundle.cost_snapshot,
            data_source=bundle.parking_lot.data_source,
            idempotency_key=payload.idempotency_key,
        )
        if result.recommendation.route is not None:
            request.app.state.replan_service.register_route(result.journey.journey_id, result.recommendation.route)
        return JourneyRecommendationResponse(
            recommendation=result.recommendation,
            journey=journey_to_contract(result.journey, recommendation_id=result.recommendation.recommendation_id),
        )

    @app.post(
        "/api/v2/journeys/{journey_id}/confirm",
        response_model=Journey,
        responses={404: ERROR_RESPONSES[404], 409: ERROR_RESPONSES[409]},
        tags=["journeys"],
    )
    def confirm_journey(
        journey_id: str,
        payload: JourneyConfirmRequest,
        request: Request,
        session_id: SessionIdHeader = None,
    ) -> Journey:
        store: InMemorySessionStore = request.app.state.session_store
        record = store.refresh_journey(journey_id)
        if record is None:
            raise JourneyNotFoundError(f"unknown journey: {journey_id}")
        require_driver_session(record, session_id)
        return journey_to_contract(
            store.confirm(journey_id=journey_id, accepted=payload.accepted, expected_version=payload.expected_version, idempotency_key=payload.idempotency_key)
        )

    @app.post(
        "/api/v2/journeys/{journey_id}/start-navigation",
        response_model=Journey,
        responses={404: ERROR_RESPONSES[404], 409: ERROR_RESPONSES[409]},
        tags=["journeys"],
    )
    def start_navigation(
        journey_id: str,
        payload: JourneyCommandRequest,
        request: Request,
        session_id: SessionIdHeader = None,
    ) -> Journey:
        return apply_command("start-navigation", journey_id, payload, request, session_id)
