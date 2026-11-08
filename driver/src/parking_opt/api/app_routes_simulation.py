"""Simulation run/replay routes for web-v2."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import FastAPI, HTTPException, Request

from parking_opt.api.app_contracts import ERROR_RESPONSES
from parking_opt.api.models import (
    SimulationReplayRequest,
    SimulationRunRequest,
    SimulationRunResponse,
    SimulationSummaryResponse,
)
from parking_opt.api.simulation import DeterministicSimulation, SimulationCommand
from parking_opt.api.sources import (
    ParkingDataSource,
    ParkingDataUnavailableError,
    ParkingLotNotFoundError,
)


def register_simulation_routes(app: FastAPI) -> None:
    @app.post(
        "/api/v2/simulations/run",
        response_model=SimulationRunResponse,
        responses={404: ERROR_RESPONSES[404], 409: ERROR_RESPONSES[409], 422: ERROR_RESPONSES[422], 503: ERROR_RESPONSES[503]},
        tags=["simulations"],
    )
    def run_simulation(payload: SimulationRunRequest, request: Request) -> SimulationRunResponse:
        source: ParkingDataSource = request.app.state.data_source
        try:
            bundle = source.get_bundle(payload.parking_lot_id)
        except ParkingLotNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ParkingDataUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        try:
            run = DeterministicSimulation(layout=bundle.layout, seed=payload.seed, wall_time_origin=payload.wall_time_origin).run(
                tuple(
                    SimulationCommand(
                        simulation_time_s=item.simulation_time_s,
                        priority=item.priority,
                        sequence_hint=item.sequence_hint,
                        event_type=item.event_type,
                        vehicle_id=item.vehicle_id,
                        payload=item.payload,
                    )
                    for item in payload.commands
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return SimulationRunResponse(seed=run.seed, events=run.events, summary=SimulationSummaryResponse(**asdict(run.summary)))

    @app.post(
        "/api/v2/simulations/replay",
        response_model=SimulationSummaryResponse,
        responses={404: ERROR_RESPONSES[404], 409: ERROR_RESPONSES[409], 422: ERROR_RESPONSES[422], 503: ERROR_RESPONSES[503]},
        tags=["simulations"],
    )
    def replay_simulation(payload: SimulationReplayRequest, request: Request) -> SimulationSummaryResponse:
        source: ParkingDataSource = request.app.state.data_source
        try:
            bundle = source.get_bundle(payload.parking_lot_id)
        except ParkingLotNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ParkingDataUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        try:
            summary = DeterministicSimulation(layout=bundle.layout, seed=payload.seed, wall_time_origin=payload.wall_time_origin).replay(payload.events)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return SimulationSummaryResponse(**asdict(summary))
