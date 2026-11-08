"""FastAPI composition root for the versioned web-v2 read/recommend boundary."""
from __future__ import annotations
import logging
import tomllib
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from parking_opt.api.adapters.v1 import V1OnlineRuleAdapter
from parking_opt.api.app_contracts import ERROR_RESPONSES
from parking_opt.api.app_routes_advanced import register_advanced_routes
from parking_opt.api.app_routes_auth import register_auth_routes
from parking_opt.api.app_routes_journey import register_journey_routes
from parking_opt.api.app_routes_read import register_read_routes
from parking_opt.api.app_routes_recommend import register_recommend_routes
from parking_opt.api.app_routes_replan import register_replan_routes
from parking_opt.api.app_routes_simulation import register_simulation_routes
from parking_opt.api.app_routes_tandem import register_tandem_routes
from parking_opt.api.app_routes_trip import register_trip_routes
from parking_opt.api.discovery import (
    DiscoveryDataSource,
    RealDiscoveryDataSource,
    SyntheticDiscoveryDataSource,
    load_discovery_area,
)
from parking_opt.api.dynamic_costs import DynamicCostService
from parking_opt.api.facility import (
    ParkingFacilityDataSource,
    UnavailableParkingFacilityDataSource,
)
from parking_opt.api.facility_scenarios import PublicFacilityDataSource
from parking_opt.api.models import DataMode, ErrorResponse
from parking_opt.api.routing import RouteCostService
from parking_opt.api.scenarios import load_scenarios
from parking_opt.api.services.journey import JourneyRecommendationService
from parking_opt.api.services.online_rule import OnlineRuleServiceV2
from parking_opt.api.research_api import connect_research
from parking_opt.api.services.replanning import JourneyReplanService
from parking_opt.api.sessions import (
    InMemorySessionStore,
    JourneyNotFoundError,
    SessionStateError,
    SessionTiming,
)
from parking_opt.api.sources import (
    ParkingDataSource,
    RealParkingDataSource,
    SyntheticParkingDataSource,
)
from parking_opt.api.sources import ScenarioProfile as _ScenarioProfile
REPO_ROOT = Path(__file__).resolve().parents[3]
LOGGER = logging.getLogger(__name__)
def create_app(
    *,
    data_mode: DataMode = DataMode.SYNTHETIC,
    scenario_profile: _ScenarioProfile | None,
    facility_source: ParkingFacilityDataSource | None = None,
    driver_demo_profiles_enabled: bool | None = None,
    driver_tandem_arrival_replay_enabled: bool | None = None,
    driver_tandem_departure_replay_enabled: bool | None = None,
) -> FastAPI:
    """Create an app with an explicit data mode; no environment-dependent silent fallback."""
    route_service = RouteCostService()
    m3_config = tomllib.loads((REPO_ROOT / "configs" / "web-v2" / "m3.toml").read_text(encoding="utf-8"))
    session_config = m3_config["session"]
    tandem_replay_enabled = (
        m3_config["driver_demo"]["tandem_departure_replay_enabled"]
        if driver_tandem_departure_replay_enabled is None
        else driver_tandem_departure_replay_enabled
    )
    tandem_arrival_replay_enabled = (
        m3_config["driver_demo"]["tandem_arrival_replay_enabled"]
        if driver_tandem_arrival_replay_enabled is None
        else driver_tandem_arrival_replay_enabled
    )
    session_store = InMemorySessionStore(
        timing=SessionTiming(
            driver_idle_ttl_s=session_config["driver_idle_ttl_s"],
            defense_idle_ttl_s=session_config["defense_idle_ttl_s"],
            soft_hold_ttl_s=session_config["soft_hold_ttl_s"],
            driver_reservation_ttl_s=session_config["driver_reservation_ttl_s"],
            defense_reservation_ttl_s=session_config["defense_reservation_ttl_s"],
        )
    )
    source: ParkingDataSource
    public_source: PublicFacilityDataSource | None = None
    if data_mode is DataMode.SYNTHETIC:
        if scenario_profile is None:
            raise ValueError("synthetic app construction requires an explicit scenario profile")
        if scenario_profile is _ScenarioProfile.LEGACY:
            source = SyntheticParkingDataSource(load_scenarios(REPO_ROOT / "data" / "synthetic" / "web-v2"), profile=scenario_profile)
            discovery_source: DiscoveryDataSource = SyntheticDiscoveryDataSource(
                load_discovery_area(REPO_ROOT / "data" / "synthetic" / "web-v2" / "discovery-area.v1.json"),
                (item.parking_lot for item in source.list_bundles()),
            )
        else:
            profiles_enabled = (
                m3_config["driver_demo"]["profiles_enabled"]
                if driver_demo_profiles_enabled is None
                else driver_demo_profiles_enabled
            )
            public_source = PublicFacilityDataSource(session_store=session_store, route_service=route_service, profiles_enabled=profiles_enabled)
            source = public_source
            discovery_source = SyntheticDiscoveryDataSource(
                load_discovery_area(REPO_ROOT / "data" / "synthetic" / "web-v2" / "discovery-area.v1.json"),
                (item.parking_lot for item in source.list_bundles()),
            )
    else:
        if scenario_profile is not None:
            raise ValueError("real app construction cannot select a synthetic scenario profile")
        source = RealParkingDataSource()
        discovery_source = RealDiscoveryDataSource()
    active_facility_source = facility_source or (
        public_source if data_mode is DataMode.SYNTHETIC and scenario_profile is _ScenarioProfile.PUBLIC else UnavailableParkingFacilityDataSource()
    )
    if active_facility_source is None:
        raise RuntimeError("public facility source was not initialized")
    recommender = OnlineRuleServiceV2(
        v1_adapter=V1OnlineRuleAdapter(schema_dir=REPO_ROOT / "schemas" / "v1", route_service=route_service),
        route_service=route_service,
    )
    app = FastAPI(title="ParkSim Web API", version="2.0.0", description="Parking discovery, journeys, routing and validated research releases.")
    recommender = connect_research(app, recommender, route_service, REPO_ROOT)
    journey_service = JourneyRecommendationService(
        online_rule=recommender,
        route_service=route_service,
        session_store=session_store,
        eta_safety_margin_s=session_config["eta_safety_margin_s"],
        driver_reservation_ttl_s=session_config["driver_reservation_ttl_s"],
    )
    replan_service = JourneyReplanService(
        route_service=route_service,
        cost_service=DynamicCostService(),
        session_store=session_store,
        eta_safety_margin_s=session_config["eta_safety_margin_s"],
    )
    app.state.data_mode = data_mode
    app.state.data_source = source
    app.state.public_source = public_source
    app.state.discovery_source = discovery_source
    app.state.facility_source = active_facility_source
    app.state.recommender = recommender
    app.state.session_store = session_store
    app.state.journey_service = journey_service
    app.state.replan_service = replan_service
    app.state.route_service = route_service
    app.state.driver_tandem_arrival_replay_enabled = tandem_arrival_replay_enabled
    app.state.driver_tandem_departure_replay_enabled = tandem_replay_enabled
    @app.middleware("http")
    async def attach_request_id(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.request_id = f"req-{uuid4().hex}"
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response
    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        code_by_status = {404: "RESOURCE_NOT_FOUND", 409: "CAPABILITY_CONFLICT", 503: "DATA_SOURCE_UNAVAILABLE"}
        payload = ErrorResponse(code=code_by_status.get(exc.status_code, "HTTP_ERROR"), message=str(exc.detail), request_id=request.state.request_id)
        return JSONResponse(status_code=exc.status_code, content=payload.model_dump(mode="json"), headers={"X-Request-ID": payload.request_id})
    @app.exception_handler(RequestValidationError)
    async def contract_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = tuple(
            {"location": [str(part) for part in item["loc"]], "type": item["type"], "message": item["msg"]}
            for item in exc.errors()
        )
        payload = ErrorResponse(code="CONTRACT_VALIDATION_FAILED", message="request does not satisfy the v2 contract", details=details, request_id=request.state.request_id)
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content=payload.model_dump(mode="json"), headers={"X-Request-ID": payload.request_id})
    @app.exception_handler(SessionStateError)
    async def session_state_error(request: Request, exc: SessionStateError) -> JSONResponse:
        is_missing = isinstance(exc, JourneyNotFoundError)
        payload = ErrorResponse(code="JOURNEY_NOT_FOUND" if is_missing else type(exc).__name__.upper(), message=str(exc), request_id=request.state.request_id)
        return JSONResponse(status_code=404 if is_missing else 409, content=payload.model_dump(mode="json"), headers={"X-Request-ID": payload.request_id})
    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", f"req-{uuid4().hex}")
        LOGGER.exception("unhandled web-v2 request failure; request_id=%s", request_id)
        payload = ErrorResponse(code="INTERNAL_SERVER_ERROR", message="an unexpected internal error occurred", request_id=request_id)
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=payload.model_dump(mode="json"), headers={"X-Request-ID": payload.request_id})
    register_read_routes(app)
    register_recommend_routes(app)
    register_auth_routes(app)
    register_advanced_routes(app)
    register_trip_routes(app)
    register_journey_routes(app)
    register_replan_routes(app)
    register_tandem_routes(app)
    register_simulation_routes(app)
    return app
app = create_app(scenario_profile=_ScenarioProfile.PUBLIC)
