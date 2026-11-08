"""Shared request-handling helpers for the web-v2 API routes."""

from __future__ import annotations

from fastapi import HTTPException, Request

from parking_opt.api.facility_scenarios import PublicFacilityDataSource
from parking_opt.api.models import DataMode
from parking_opt.api.sessions import (
    InMemorySessionStore,
    JourneyNotFoundError,
    JourneyRecord,
    SessionNamespace,
)
from parking_opt.api.sources import (
    ParkingDataSource,
    ParkingDataUnavailableError,
    ParkingLotNotFoundError,
    ScenarioBundle,
)
from parking_opt.api.services.journey import journey_to_contract
from parking_opt.api.models import Journey, JourneyCommandRequest


def driver_bundles(
    data_source: ParkingDataSource, session_id: str | None
) -> tuple[ScenarioBundle, ...]:
    if session_id is not None and isinstance(data_source, PublicFacilityDataSource):
        return data_source.list_driver_bundles(session_id=session_id)
    return data_source.list_bundles()


def driver_bundle(
    data_source: ParkingDataSource, parking_lot_id: str, session_id: str | None
) -> ScenarioBundle:
    if session_id is not None and isinstance(data_source, PublicFacilityDataSource):
        return data_source.get_driver_bundle(parking_lot_id, session_id=session_id)
    return data_source.get_bundle(parking_lot_id)


def get_journey_bundle(journey_id: str, request: Request):
    store: InMemorySessionStore = request.app.state.session_store
    source: ParkingDataSource = request.app.state.data_source
    record = store.get_journey(journey_id)
    if record is None:
        raise JourneyNotFoundError(f"unknown journey: {journey_id}")
    try:
        bundle = driver_bundle(
            source,
            record.parking_lot_id,
            record.session_id if record.namespace is SessionNamespace.DRIVER else None,
        )
    except ParkingLotNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ParkingDataUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if bundle.scenario_id != record.scenario_id:
        raise HTTPException(status_code=409, detail="journey scenario is unavailable")
    return record, bundle


def require_driver_session(record: JourneyRecord, session_id: str | None) -> None:
    if session_id is not None and (
        record.namespace is not SessionNamespace.DRIVER or record.session_id != session_id
    ):
        raise HTTPException(status_code=409, detail="session header does not match journey")


def require_synthetic_driver_demo(
    record: JourneyRecord, bundle: object, request: Request
) -> None:
    parking_lot = bundle.parking_lot  # type: ignore[attr-defined]
    if (
        request.app.state.data_mode is not DataMode.SYNTHETIC
        or record.namespace is not SessionNamespace.DRIVER
        or parking_lot.synthetic is not True
        or parking_lot.data_source.mode is not DataMode.SYNTHETIC
    ):
        raise HTTPException(
            status_code=409,
            detail="driver demo action requires a synthetic driver journey",
        )


def apply_command(
    command: str,
    journey_id: str,
    payload: JourneyCommandRequest,
    request: Request,
    session_id: str | None = None,
) -> Journey:
    store: InMemorySessionStore = request.app.state.session_store
    record = store.refresh_journey(journey_id)
    if record is None:
        raise JourneyNotFoundError(f"unknown journey: {journey_id}")
    require_driver_session(record, session_id)
    method = {
        "start-navigation": store.start_navigation,
        "occupy": store.occupy,
        "cancel": store.cancel,
        "depart": store.depart,
    }[command]
    return journey_to_contract(
        method(
            journey_id=journey_id,
            expected_version=payload.expected_version,
            idempotency_key=payload.idempotency_key,
        )
    )
