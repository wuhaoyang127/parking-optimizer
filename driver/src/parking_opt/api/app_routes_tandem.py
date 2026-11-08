"""Tandem arrival/departure replay routes for web-v2."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request

from parking_opt.api.app_contracts import ERROR_RESPONSES, RequiredSessionIdHeader
from parking_opt.api.app_helpers import require_driver_session
from parking_opt.api.facility_scenarios import PublicFacilityDataSource
from parking_opt.api.models import (
    DriverTandemArrivalReplay,
    DriverTandemArrivalRequest,
    DriverTandemDepartureReplay,
    DriverTandemDepartureRequest,
)
from parking_opt.api.services.journey import journey_to_contract
from parking_opt.api.services.tandem_arrival import (
    TandemArrivalConflictError,
    TandemArrivalUnavailableError,
    build_tandem_arrival_draft,
)
from parking_opt.api.services.tandem_departure import (
    TandemDepartureConflictError,
    TandemDepartureUnavailableError,
    build_tandem_departure_draft,
)
from parking_opt.api.sessions import InMemorySessionStore, JourneyNotFoundError, VersionConflictError


def register_tandem_routes(app: FastAPI) -> None:
    @app.post(
        "/api/v2/journeys/{journey_id}/tandem-arrival-replay",
        response_model=DriverTandemArrivalReplay,
        responses={404: ERROR_RESPONSES[404], 409: ERROR_RESPONSES[409], 503: ERROR_RESPONSES[503]},
        tags=["journeys"],
    )
    def tandem_arrival_replay(
        journey_id: str,
        payload: DriverTandemArrivalRequest,
        request: Request,
        session_id: RequiredSessionIdHeader,
    ) -> DriverTandemArrivalReplay:
        store: InMemorySessionStore = request.app.state.session_store
        canonical_payload = {"journey_id": journey_id, **payload.model_dump(mode="json")}
        with store.atomic():
            record = store.refresh_journey(journey_id)
            if record is None:
                raise JourneyNotFoundError(f"unknown journey: {journey_id}")
            require_driver_session(record, session_id)
            remembered = store.replay_tandem_arrival_command(session_id=session_id, idempotency_key=payload.idempotency_key, payload=canonical_payload)
            if remembered is not None:
                if not isinstance(remembered, DriverTandemArrivalReplay):
                    raise RuntimeError("stored tandem arrival replay has an invalid type")
                return remembered
            if not request.app.state.driver_tandem_arrival_replay_enabled:
                raise HTTPException(status_code=409, detail="tandem arrival replay is disabled")
            source = request.app.state.public_source
            if not isinstance(source, PublicFacilityDataSource):
                raise HTTPException(status_code=409, detail="tandem arrival replay requires the synthetic public source")
            if record.version != payload.expected_version:
                raise VersionConflictError(f"expected journey version {payload.expected_version}, current is {record.version}")
            try:
                draft = build_tandem_arrival_draft(
                    journey=record,
                    expected_state_version=payload.expected_state_version,
                    profile=source.get_driver_demo_profile(record.parking_lot_id, session_id=session_id),
                    layout=source.get_layout(record.parking_lot_id),
                    state=source.get_state(record.parking_lot_id, session_id=session_id),
                    bundle=source.get_driver_bundle(record.parking_lot_id, session_id=session_id),
                    route_service=request.app.state.route_service,
                    created_at=store.current_wall_time(),
                )
            except TandemArrivalConflictError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except TandemArrivalUnavailableError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            occupied_record = store.occupy(journey_id=journey_id, expected_version=payload.expected_version, idempotency_key=payload.idempotency_key)
            store.remember_tandem_coordination(draft.coordination)
            after_state = source.get_state(occupied_record.parking_lot_id, session_id=session_id)
            replay = draft.finalize(after_facility_state=after_state, final_journey=journey_to_contract(occupied_record))
            store.remember_tandem_arrival_replay(journey_id=journey_id, session_id=session_id, idempotency_key=payload.idempotency_key, payload=canonical_payload, replay=replay)
            return replay

    @app.post(
        "/api/v2/journeys/{journey_id}/tandem-departure-replay",
        response_model=DriverTandemDepartureReplay,
        responses={404: ERROR_RESPONSES[404], 409: ERROR_RESPONSES[409], 503: ERROR_RESPONSES[503]},
        tags=["journeys"],
    )
    def tandem_departure_replay(
        journey_id: str,
        payload: DriverTandemDepartureRequest,
        request: Request,
        session_id: RequiredSessionIdHeader,
    ) -> DriverTandemDepartureReplay:
        store: InMemorySessionStore = request.app.state.session_store
        canonical_payload = {"journey_id": journey_id, **payload.model_dump(mode="json")}
        with store.atomic():
            record = store.get_journey(journey_id)
            if record is None:
                raise JourneyNotFoundError(f"unknown journey: {journey_id}")
            require_driver_session(record, session_id)
            remembered = store.replay_tandem_departure_command(session_id=session_id, idempotency_key=payload.idempotency_key, payload=canonical_payload)
            if remembered is not None:
                if not isinstance(remembered, DriverTandemDepartureReplay):
                    raise RuntimeError("stored tandem departure replay has an invalid type")
                return remembered
            if not request.app.state.driver_tandem_departure_replay_enabled:
                raise HTTPException(status_code=409, detail="tandem departure replay is disabled")
            source = request.app.state.public_source
            if not isinstance(source, PublicFacilityDataSource):
                raise HTTPException(status_code=409, detail="tandem departure replay requires the synthetic public source")
            if record.version != payload.expected_version:
                raise VersionConflictError(f"expected journey version {payload.expected_version}, current is {record.version}")
            try:
                draft = build_tandem_departure_draft(
                    journey=record,
                    expected_state_version=payload.expected_state_version,
                    profile=source.get_driver_demo_profile(record.parking_lot_id, session_id=session_id),
                    layout=source.get_layout(record.parking_lot_id),
                    state=source.get_state(record.parking_lot_id, session_id=session_id),
                    bundle=source.get_driver_bundle(record.parking_lot_id, session_id=session_id),
                    route_service=request.app.state.route_service,
                    created_at=store.current_wall_time(),
                    coordination=store.tandem_coordination(journey_id),
                )
            except TandemDepartureConflictError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except TandemDepartureUnavailableError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            departed_record = store.depart(journey_id=journey_id, expected_version=payload.expected_version, idempotency_key=payload.idempotency_key)
            replay = draft.finalize(journey_to_contract(departed_record))
            store.remember_tandem_departure_replay(journey_id=journey_id, session_id=session_id, idempotency_key=payload.idempotency_key, payload=canonical_payload, replay=replay)
            store.advance_driver_demo_profile_after_terminal(journey_id=journey_id, profile_count=source.driver_demo_profile_count(departed_record.parking_lot_id))
            return replay
