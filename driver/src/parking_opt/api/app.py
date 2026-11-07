"""FastAPI composition root for the versioned web-v2 read/recommend boundary."""

from __future__ import annotations

import logging
import tomllib
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from parking_opt.api.adapters.v1 import V1OnlineRuleAdapter
from parking_opt.api.availability import project_parking_lots
from parking_opt.api.discovery import (
    DiscoveryDataSource,
    DiscoveryDataUnavailableError,
    RealDiscoveryDataSource,
    SyntheticDiscoveryDataSource,
    load_discovery_area,
)
from parking_opt.api.dynamic_costs import DynamicCostService
from parking_opt.api.facility import (
    FacilityDataUnavailableError,
    FacilityNotFoundError,
    FacilityVersionConflictError,
    ParkingFacilityDataSource,
    UnavailableParkingFacilityDataSource,
)
from parking_opt.api.facility_scenarios import PublicFacilityDataSource
from parking_opt.api.models import (
    AlgorithmDescriptor,
    DataMode,
    DiscoveryArea,
    DriverDemoProfileAdvanceRequest,
    DriverDemoProfileAdvanceResponse,
    DriverDemoReplanRequest,
    DriverEntrance,
    DriverJourneySnapshot,
    DriverRecommendationContext,
    DriverTandemArrivalReplay,
    DriverTandemArrivalRequest,
    DriverTandemDepartureReplay,
    DriverTandemDepartureRequest,
    DriverTripEvent,
    DriverTripRecord,
    DriverTripSnapshot,
    ErrorResponse,
    ExternalOccupancyRequest,
    ExternalOccupancyResponse,
    HealthResponse,
    Journey,
    JourneyAlternativeRequest,
    JourneyCommandRequest,
    JourneyConfirmRequest,
    JourneyDeclineRequest,
    JourneyDeclineResponse,
    JourneyReassignmentRequest,
    JourneyReassignmentResponse,
    JourneyRecommendationRequest,
    JourneyRecommendationResponse,
    JourneyReplanRequest,
    JourneyReplanResponse,
    Layout,
    ParkingFacilityLayout,
    ParkingFacilityStateSnapshot,
    ParkingLot,
    Recommendation,
    RecommendationRequest,
    RoutePreview,
    RoutePreviewRequest,
    ScenarioBundle,
    SimulationReplayRequest,
    SimulationRunRequest,
    SimulationRunResponse,
    SimulationSummaryResponse,
    SpaceStatus,
)
from parking_opt.api.registry import algorithm_registry, require_online_algorithm
from parking_opt.api.routing import RouteCostService
from parking_opt.api.scenarios import load_scenarios
from parking_opt.api.services.journey import (
    JourneyRecommendationService,
    journey_to_contract,
)
from parking_opt.api.services.online_rule import OnlineRuleServiceV2
from parking_opt.api.research_api import connect_research
from parking_opt.api.services.replanning import JourneyReplanService
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
from parking_opt.api.sessions import (
    InMemorySessionStore,
    JourneyNotFoundError,
    JourneyRecord,
    SessionNamespace,
    SessionStateError,
    SessionTiming,
    VersionConflictError,
)
from parking_opt.api.simulation import DeterministicSimulation, SimulationCommand
from parking_opt.api.sources import (
    ParkingDataSource,
    ParkingDataUnavailableError,
    ParkingLotNotFoundError,
    RealParkingDataSource,
    ScenarioProfile,
    SyntheticParkingDataSource,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
LOGGER = logging.getLogger(__name__)
ERROR_RESPONSES = {
    500: {"model": ErrorResponse, "description": "Unexpected internal failure"},
    404: {"model": ErrorResponse, "description": "Resource not found"},
    409: {"model": ErrorResponse, "description": "Capability conflict"},
    422: {"model": ErrorResponse, "description": "Contract validation failed"},
    503: {"model": ErrorResponse, "description": "Data source unavailable"},
}
SessionIdHeader = Annotated[
    str | None,
    Header(
        alias="X-Session-ID",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
        description=(
            "Optional synthetic driver-session context. It is not an authentication credential."
        ),
    ),
]
RequiredSessionIdHeader = Annotated[
    str,
    Header(
        alias="X-Session-ID",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
        description=(
            "Required synthetic driver-session context. It is not an authentication credential."
        ),
    ),
]


def create_app(
    *,
    data_mode: DataMode = DataMode.SYNTHETIC,
    scenario_profile: ScenarioProfile | None,
    facility_source: ParkingFacilityDataSource | None = None,
    driver_demo_profiles_enabled: bool | None = None,
    driver_tandem_arrival_replay_enabled: bool | None = None,
    driver_tandem_departure_replay_enabled: bool | None = None,
) -> FastAPI:
    """Create an app with an explicit data mode; no environment-dependent silent fallback."""

    route_service = RouteCostService()
    m3_config = tomllib.loads(
        (REPO_ROOT / "configs" / "web-v2" / "m3.toml").read_text(encoding="utf-8")
    )
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
        if scenario_profile is ScenarioProfile.LEGACY:
            source = SyntheticParkingDataSource(
                load_scenarios(REPO_ROOT / "data" / "synthetic" / "web-v2"),
                profile=scenario_profile,
            )
            discovery_source: DiscoveryDataSource = SyntheticDiscoveryDataSource(
                load_discovery_area(
                    REPO_ROOT / "data" / "synthetic" / "web-v2" / "discovery-area.v1.json"
                ),
                (item.parking_lot for item in source.list_bundles()),
            )
        else:
            profiles_enabled = (
                m3_config["driver_demo"]["profiles_enabled"]
                if driver_demo_profiles_enabled is None
                else driver_demo_profiles_enabled
            )
            public_source = PublicFacilityDataSource(
                session_store=session_store,
                route_service=route_service,
                profiles_enabled=profiles_enabled,
            )
            source = public_source
            discovery_source = SyntheticDiscoveryDataSource(
                load_discovery_area(
                    REPO_ROOT / "data" / "synthetic" / "web-v2" / "discovery-area.v1.json"
                ),
                (item.parking_lot for item in source.list_bundles()),
            )
    else:
        if scenario_profile is not None:
            raise ValueError("real app construction cannot select a synthetic scenario profile")
        source = RealParkingDataSource()
        discovery_source = RealDiscoveryDataSource()
    active_facility_source = facility_source or (
        public_source
        if data_mode is DataMode.SYNTHETIC and scenario_profile is ScenarioProfile.PUBLIC
        else UnavailableParkingFacilityDataSource()
    )
    if active_facility_source is None:
        raise RuntimeError("public facility source was not initialized")
    recommender = OnlineRuleServiceV2(
        v1_adapter=V1OnlineRuleAdapter(
            schema_dir=REPO_ROOT / "schemas" / "v1",
            route_service=route_service,
        ),
        route_service=route_service,
    )
    app = FastAPI(
        title="ParkSim Web API", version="2.0.0",
        description="Parking discovery, journeys, routing and validated research releases.",
    )
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

    @app.middleware("http")
    async def attach_request_id(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.request_id = f"req-{uuid4().hex}"
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        code_by_status = {
            404: "RESOURCE_NOT_FOUND",
            409: "CAPABILITY_CONFLICT",
            503: "DATA_SOURCE_UNAVAILABLE",
        }
        payload = ErrorResponse(
            code=code_by_status.get(exc.status_code, "HTTP_ERROR"),
            message=str(exc.detail),
            request_id=request.state.request_id,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=payload.model_dump(mode="json"),
            headers={"X-Request-ID": payload.request_id},
        )

    @app.exception_handler(RequestValidationError)
    async def contract_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = tuple(
            {
                "location": [str(part) for part in item["loc"]],
                "type": item["type"],
                "message": item["msg"],
            }
            for item in exc.errors()
        )
        payload = ErrorResponse(
            code="CONTRACT_VALIDATION_FAILED",
            message="request does not satisfy the v2 contract",
            details=details,
            request_id=request.state.request_id,
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=payload.model_dump(mode="json"),
            headers={"X-Request-ID": payload.request_id},
        )

    @app.exception_handler(SessionStateError)
    async def session_state_error(request: Request, exc: SessionStateError) -> JSONResponse:
        is_missing = isinstance(exc, JourneyNotFoundError)
        payload = ErrorResponse(
            code="JOURNEY_NOT_FOUND" if is_missing else type(exc).__name__.upper(),
            message=str(exc),
            request_id=request.state.request_id,
        )
        return JSONResponse(
            status_code=404 if is_missing else 409,
            content=payload.model_dump(mode="json"),
            headers={"X-Request-ID": payload.request_id},
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", f"req-{uuid4().hex}")
        LOGGER.exception("unhandled web-v2 request failure; request_id=%s", request_id)
        payload = ErrorResponse(
            code="INTERNAL_SERVER_ERROR",
            message="an unexpected internal error occurred",
            request_id=request_id,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=payload.model_dump(mode="json"),
            headers={"X-Request-ID": payload.request_id},
        )

    @app.get("/api/v2/health", response_model=HealthResponse, tags=["system"])
    def health(request: Request) -> HealthResponse:
        return HealthResponse(data_mode=request.app.state.data_mode)

    @app.get(
        "/api/v2/parking-lots",
        response_model=list[ParkingLot],
        responses={503: ERROR_RESPONSES[503]},
        tags=["parking-lots"],
    )
    def list_parking_lots(
        request: Request,
        response: Response,
        session_id: SessionIdHeader = None,
    ) -> list[ParkingLot]:
        source: ParkingDataSource = request.app.state.data_source
        response.headers["Cache-Control"] = "no-store"
        response.headers["Vary"] = "X-Session-ID"
        try:
            bundles = driver_bundles(source, session_id)
            if session_id is None:
                return [item.parking_lot for item in bundles]
            store: InMemorySessionStore = request.app.state.session_store
            snapshot = store.availability_snapshot(
                session_id=session_id,
                namespace=SessionNamespace.DRIVER,
                scopes=tuple(
                    (item.scenario_id, item.parking_lot.parking_lot_id) for item in bundles
                ),
            )
            return list(project_parking_lots(bundles, snapshot))
        except ParkingDataUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get(
        "/api/v2/discovery-area",
        response_model=DiscoveryArea,
        responses={503: ERROR_RESPONSES[503]},
        tags=["parking-lots"],
    )
    def get_discovery_area(request: Request) -> DiscoveryArea:
        source: DiscoveryDataSource = request.app.state.discovery_source
        try:
            return source.get_area()
        except DiscoveryDataUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get(
        "/api/v2/parking-lots/{parking_lot_id}",
        response_model=ParkingLot,
        responses={404: ERROR_RESPONSES[404], 503: ERROR_RESPONSES[503]},
        tags=["parking-lots"],
    )
    def get_parking_lot(
        parking_lot_id: str,
        request: Request,
        response: Response,
        session_id: SessionIdHeader = None,
    ) -> ParkingLot:
        source: ParkingDataSource = request.app.state.data_source
        response.headers["Cache-Control"] = "no-store"
        response.headers["Vary"] = "X-Session-ID"
        try:
            bundle = driver_bundle(source, parking_lot_id, session_id)
            if session_id is None:
                return bundle.parking_lot
            store: InMemorySessionStore = request.app.state.session_store
            snapshot = store.availability_snapshot(
                session_id=session_id,
                namespace=SessionNamespace.DRIVER,
                scopes=((bundle.scenario_id, parking_lot_id),),
            )
            return project_parking_lots((bundle,), snapshot)[0]
        except ParkingLotNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ParkingDataUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get(
        "/api/v2/parking-lots/{parking_lot_id}/layout",
        response_model=Layout,
        responses={404: ERROR_RESPONSES[404], 503: ERROR_RESPONSES[503]},
        tags=["parking-lots"],
    )
    def get_layout(parking_lot_id: str, request: Request) -> Layout:
        source: ParkingDataSource = request.app.state.data_source
        try:
            return source.get_bundle(parking_lot_id).layout
        except ParkingLotNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ParkingDataUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get(
        "/api/v2/parking-lots/{parking_lot_id}/facility-layout",
        response_model=ParkingFacilityLayout,
        responses={
            404: ERROR_RESPONSES[404],
            422: ERROR_RESPONSES[422],
            503: ERROR_RESPONSES[503],
        },
        tags=["parking-lots"],
    )
    def get_facility_layout(
        parking_lot_id: str,
        request: Request,
        response: Response,
    ) -> ParkingFacilityLayout:
        source: ParkingFacilityDataSource = request.app.state.facility_source
        response.headers["Cache-Control"] = "private, max-age=300"
        if request.query_params:
            raise HTTPException(status_code=422, detail="facility layout accepts no selectors")
        try:
            layout = source.get_layout(parking_lot_id)
            if layout.parking_lot_id != parking_lot_id:
                raise FacilityDataUnavailableError("facility layout scope mismatch")
            return layout
        except FacilityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FacilityDataUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get(
        "/api/v2/parking-lots/{parking_lot_id}/facility-state",
        response_model=ParkingFacilityStateSnapshot,
        responses={
            404: ERROR_RESPONSES[404],
            422: ERROR_RESPONSES[422],
            503: ERROR_RESPONSES[503],
        },
        tags=["parking-lots"],
    )
    def get_facility_state(
        parking_lot_id: str,
        request: Request,
        response: Response,
        session_id: RequiredSessionIdHeader,
    ) -> ParkingFacilityStateSnapshot:
        source: ParkingFacilityDataSource = request.app.state.facility_source
        response.headers["Cache-Control"] = "no-store"
        response.headers["Vary"] = "X-Session-ID"
        if request.query_params:
            raise HTTPException(status_code=422, detail="facility state accepts no selectors")
        try:
            state_snapshot = source.get_state(parking_lot_id, session_id=session_id)
            if state_snapshot.parking_lot_id != parking_lot_id:
                raise FacilityDataUnavailableError("facility state scope mismatch")
            try:
                state_snapshot.require_layout(source.get_layout(parking_lot_id))
            except ValueError as exc:
                raise FacilityDataUnavailableError(str(exc)) from exc
            return state_snapshot
        except FacilityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FacilityDataUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post(
        "/api/v2/parking-lots/{parking_lot_id}/route-previews",
        response_model=RoutePreview,
        responses={
            404: ERROR_RESPONSES[404],
            409: ERROR_RESPONSES[409],
            422: ERROR_RESPONSES[422],
            503: ERROR_RESPONSES[503],
        },
        tags=["parking-lots"],
    )
    def preview_facility_route(
        parking_lot_id: str,
        payload: RoutePreviewRequest,
        request: Request,
        response: Response,
        session_id: RequiredSessionIdHeader,
    ) -> RoutePreview:
        source: ParkingFacilityDataSource = request.app.state.facility_source
        response.headers["Cache-Control"] = "no-store"
        response.headers["Vary"] = "X-Session-ID"
        if request.query_params:
            raise HTTPException(status_code=422, detail="route preview accepts no selectors")
        try:
            preview = source.preview_route(
                parking_lot_id,
                session_id=session_id,
                request=payload,
            )
            if preview.parking_lot_id != parking_lot_id:
                raise FacilityDataUnavailableError("route preview scope mismatch")
            if (
                preview.layout_version != payload.layout_version
                or preview.scenario_version != payload.scenario_version
                or preview.state_version != payload.state_version
                or preview.entrance_id != payload.entrance_id
                or preview.target_space_id != payload.target_space_id
            ):
                raise FacilityVersionConflictError("route preview request identity mismatch")
            current_state = source.get_state(parking_lot_id, session_id=session_id)
            if (
                current_state.layout_version != payload.layout_version
                or current_state.scenario_version != payload.scenario_version
                or current_state.state_version != payload.state_version
            ):
                raise FacilityVersionConflictError("route preview state is stale")
            target_state = next(
                (
                    item
                    for item in current_state.spaces
                    if item.space_id == payload.target_space_id
                ),
                None,
            )
            if target_state is None:
                raise FacilityDataUnavailableError("route preview target state is missing")
            if (
                not target_state.assignable
                or target_state.effective_status is not SpaceStatus.AVAILABLE
            ):
                raise FacilityVersionConflictError(
                    "route preview target is no longer assignable"
                )
            try:
                preview.require_context(
                    request=payload,
                    layout=source.get_layout(parking_lot_id),
                    state=current_state,
                )
            except ValueError as exc:
                raise FacilityDataUnavailableError(str(exc)) from exc
            return preview
        except FacilityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FacilityVersionConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except FacilityDataUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/v2/algorithms", response_model=list[AlgorithmDescriptor], tags=["algorithms"])
    def algorithms(selectable_only: bool = Query(default=False)) -> list[AlgorithmDescriptor]:
        items = algorithm_registry()
        return [item for item in items if not selectable_only or item.status.value == "online"]

    @app.post(
        "/api/v2/recommendations",
        response_model=Recommendation,
        responses={
            404: ERROR_RESPONSES[404],
            409: ERROR_RESPONSES[409],
            422: ERROR_RESPONSES[422],
            500: ERROR_RESPONSES[500],
            503: ERROR_RESPONSES[503],
        },
        tags=["recommendations"],
    )
    def recommend(payload: RecommendationRequest, request: Request) -> Recommendation:
        source: ParkingDataSource = request.app.state.data_source
        recommender: OnlineRuleServiceV2 = request.app.state.recommender
        try:
            require_online_algorithm(payload.algorithm_id)
            bundle = driver_bundle(
                source, payload.driver.parking_lot_id, payload.driver.session_id
            )
            return recommender.recommend(
                payload.driver,
                bundle.layout,
                bundle.cost_snapshot,
                bundle.parking_lot.data_source,
            )
        except ParkingLotNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ParkingDataUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/api/v2/journeys/recommendations",
        response_model=JourneyRecommendationResponse,
        responses={
            404: ERROR_RESPONSES[404],
            409: ERROR_RESPONSES[409],
            422: ERROR_RESPONSES[422],
            503: ERROR_RESPONSES[503],
        },
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
        if session_id is not None and (
            payload.namespace != "driver" or payload.driver.session_id != session_id
        ):
            raise HTTPException(
                status_code=409,
                detail="session header does not match driver request",
            )
        try:
            bundle = driver_bundle(
                source,
                payload.driver.parking_lot_id,
                payload.driver.session_id if payload.namespace == "driver" else None,
            )
        except ParkingLotNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ParkingDataUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if payload.scenario_id != bundle.scenario_id:
            raise HTTPException(status_code=409, detail="scenario_id does not match parking lot")
        store: InMemorySessionStore = request.app.state.session_store
        with store.atomic():
            bundle = driver_bundle(
                source,
                payload.driver.parking_lot_id,
                payload.driver.session_id if payload.namespace == "driver" else None,
            )
            if payload.scenario_id != bundle.scenario_id:
                raise HTTPException(
                    status_code=409, detail="scenario_id does not match parking lot"
                )
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
        if result.recommendation.route is not None:
            replan_service.register_route(result.journey.journey_id, result.recommendation.route)
        return JourneyRecommendationResponse(
            recommendation=result.recommendation,
            journey=journey_to_contract(
                result.journey,
                recommendation_id=result.recommendation.recommendation_id,
            ),
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
            entrances=tuple(
                DriverEntrance(node_id=node_id, label=nodes[node_id].label)
                for node_id in bundle.layout.entrance_node_ids
            ),
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
        responses={
            404: ERROR_RESPONSES[404],
            409: ERROR_RESPONSES[409],
            422: ERROR_RESPONSES[422],
            503: ERROR_RESPONSES[503],
        },
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
            raise HTTPException(
                status_code=409, detail="driver demo profiles require the synthetic public source"
            )
        store: InMemorySessionStore = request.app.state.session_store
        try:
            with store.atomic():
                state = source.get_state(parking_lot_id, session_id=session_id)
                expected_index = source.driver_demo_profile_index(
                    parking_lot_id, profile_id=payload.expected_profile_id
                )
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
                next_bundle = source.get_driver_bundle(
                    parking_lot_id, session_id=session_id
                )
                if next_state.demo_profile is None:
                    raise FacilityDataUnavailableError(
                        "synthetic driver facility state has no demo profile"
                    )
                return DriverDemoProfileAdvanceResponse(
                    demo_profile=next_state.demo_profile,
                    facility_state=next_state,
                    parking_lot=next_bundle.parking_lot,
                )
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
        session_id: Annotated[
            str,
            Header(
                alias="X-Session-ID",
                min_length=1,
                max_length=128,
                pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
            ),
        ],
    ) -> DriverJourneySnapshot:
        response.headers["Cache-Control"] = "no-store"
        recovery = request.app.state.journey_service.current_driver_recovery(session_id)
        if recovery is None:
            return DriverJourneySnapshot(
                observed_at=request.app.state.session_store.current_wall_time()
            )
        return DriverJourneySnapshot(
            observed_at=recovery.observed_at,
            journey=journey_to_contract(
                recovery.result.journey,
                recommendation_id=recovery.result.recommendation.recommendation_id,
            ),
            recommendation=recovery.result.recommendation,
            driver=recovery.driver,
            waiting_since=(
                recovery.result.journey.created_at
                if recovery.result.journey.state.value == "waiting"
                else None
            ),
        )
    @app.get(
        "/api/v2/driver-session/current-trip",
        response_model=DriverTripSnapshot,
        responses={422: ERROR_RESPONSES[422]},
        tags=["journeys"],
    )
    def current_driver_trip(
        request: Request,
        response: Response,
        session_id: Annotated[
            str,
            Header(
                alias="X-Session-ID",
                min_length=1,
                max_length=128,
                pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
            ),
        ],
    ) -> DriverTripSnapshot:
        response.headers["Cache-Control"] = "no-store"
        store: InMemorySessionStore = request.app.state.session_store
        with store.atomic():
            recovery = request.app.state.journey_service.current_driver_recovery(session_id)
            if recovery is None:
                return DriverTripSnapshot(observed_at=store.current_wall_time())
            record = recovery.result.journey
            stored_arrival_replay = store.tandem_arrival_replay(record.journey_id)
            if stored_arrival_replay is not None and not isinstance(
                stored_arrival_replay, DriverTandemArrivalReplay
            ):
                raise RuntimeError("stored tandem arrival replay has an invalid type")
            stored_replay = store.tandem_departure_replay(record.journey_id)
            if stored_replay is not None and not isinstance(
                stored_replay, DriverTandemDepartureReplay
            ):
                raise RuntimeError("stored tandem departure replay has an invalid type")
            navigation = request.app.state.replan_service.recover_navigation(
                record.journey_id
            )
            all_events = store.events()
            events = tuple(
                item for item in all_events if item.journey_id == record.journey_id
            )

            def lifecycle_times(journey_id: str):  # type: ignore[no-untyped-def]
                scoped = tuple(
                    item for item in all_events if item.journey_id == journey_id
                )
                started_at = next(
                    (item.wall_time for item in scoped if item.event_type == "NAVIGATING"),
                    None,
                )
                parked_at = next(
                    (item.wall_time for item in scoped if item.event_type == "OCCUPIED"),
                    None,
                )
                ended_at = next(
                    (
                        item.wall_time
                        for item in reversed(scoped)
                        if item.event_type
                        in {"DEPARTED", "FAILED", "CANCELLED", "EXPIRED"}
                    ),
                    None,
                )
                return started_at, parked_at, ended_at

            started, parked, ended = lifecycle_times(record.journey_id)
            route_visible = record.state.value in {"session_reserved", "navigating"}
            recent_trips = []
            record_states: dict[
                str, Literal["occupied", "departed", "cancelled", "expired", "failed"]
            ] = {
                "occupied": "occupied",
                "departed": "departed",
                "cancelled": "cancelled",
                "expired": "expired",
                "failed": "failed",
            }
            for item in store.session_journeys(
                session_id, SessionNamespace.DRIVER
            ):
                record_state = record_states.get(item.state.value)
                if record_state is None:
                    continue
                item_started, item_parked, item_ended = lifecycle_times(item.journey_id)
                recent_trips.append(
                    DriverTripRecord(
                        journey_id=item.journey_id,
                        parking_lot_id=item.parking_lot_id,
                        space_id=item.space_id,
                        state=record_state,
                        started_at=item_started,
                        parked_at=item_parked,
                        ended_at=item_ended,
                        terminal_reason=item.terminal_reason,
                    )
                )
            return DriverTripSnapshot(
                observed_at=recovery.observed_at,
                journey=journey_to_contract(
                    record,
                    recommendation_id=recovery.result.recommendation.recommendation_id,
                ),
                driver=recovery.driver,
                current_route=(
                    navigation.current_route
                    if route_visible and navigation is not None
                    else None
                ),
                current_node_id=(
                    navigation.current_node_id
                    if route_visible and navigation is not None
                    else None
                ),
                last_replan=(
                    navigation.last_replan
                    if route_visible and navigation is not None
                    else None
                ),
                started_at=started,
                parked_at=parked,
                ended_at=ended,
                recent_events=tuple(
                    DriverTripEvent(
                        sequence_no=item.sequence_no,
                        event_type=item.event_type,
                        reason_code=item.reason_code,
                        occurred_at=item.wall_time,
                    )
                    for item in events[-8:]
                ),
                recent_trips=tuple(recent_trips[:5]),
                tandem_arrival_replay_enabled=request.app.state.driver_tandem_arrival_replay_enabled,
                tandem_arrival_replay=(
                    stored_arrival_replay
                    if isinstance(stored_arrival_replay, DriverTandemArrivalReplay)
                    else None
                ),
                tandem_departure_replay_enabled=request.app.state.driver_tandem_departure_replay_enabled,
                tandem_departure_replay=(
                    stored_replay
                    if isinstance(stored_replay, DriverTandemDepartureReplay)
                    else None
                ),
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
                journey=journey_to_contract(
                    result.replacement.journey,
                    recommendation_id=result.replacement.recommendation.recommendation_id,
                ),
            ),
        )

    def get_journey_bundle(journey_id: str, request: Request):  # type: ignore[no-untyped-def]
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

    @app.post(
        "/api/v2/journeys/{journey_id}/select-alternative",
        response_model=JourneyRecommendationResponse,
        responses={
            404: ERROR_RESPONSES[404],
            409: ERROR_RESPONSES[409],
            503: ERROR_RESPONSES[503],
        },
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
        replan_service.register_route(result.journey.journey_id, result.recommendation.route)
        return JourneyRecommendationResponse(
            recommendation=result.recommendation,
            journey=journey_to_contract(
                result.journey,
                recommendation_id=result.recommendation.recommendation_id,
            ),
        )

    @app.post(
        "/api/v2/journeys/{journey_id}/retry-recommendation",
        response_model=JourneyRecommendationResponse,
        responses={
            404: ERROR_RESPONSES[404],
            409: ERROR_RESPONSES[409],
            503: ERROR_RESPONSES[503],
        },
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
            replan_service.register_route(result.journey.journey_id, result.recommendation.route)
        return JourneyRecommendationResponse(
            recommendation=result.recommendation,
            journey=journey_to_contract(
                result.journey,
                recommendation_id=result.recommendation.recommendation_id,
            ),
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
            store.confirm(
                journey_id=journey_id,
                accepted=payload.accepted,
                expected_version=payload.expected_version,
                idempotency_key=payload.idempotency_key,
            )
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

    @app.post(
        "/api/v2/journeys/{journey_id}/replan",
        response_model=JourneyReplanResponse,
        responses={
            404: ERROR_RESPONSES[404],
            409: ERROR_RESPONSES[409],
            503: ERROR_RESPONSES[503],
        },
        tags=["journeys"],
    )
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
        return JourneyReplanResponse(
            journey=journey_to_contract(result.journey),
            decision=result.decision,
        )

    @app.post(
        "/api/v2/journeys/{journey_id}/driver-demo-replan",
        response_model=JourneyReplanResponse,
        responses={
            404: ERROR_RESPONSES[404],
            409: ERROR_RESPONSES[409],
            503: ERROR_RESPONSES[503],
        },
        tags=["journeys"],
    )
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
        return JourneyReplanResponse(
            journey=journey_to_contract(result.journey),
            decision=result.decision,
        )

    @app.post(
        "/api/v2/journeys/{journey_id}/report-external-occupancy",
        response_model=ExternalOccupancyResponse,
        responses={
            404: ERROR_RESPONSES[404],
            409: ERROR_RESPONSES[409],
            503: ERROR_RESPONSES[503],
        },
        tags=["journeys"],
    )
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
            replan_service.register_route(
                result.replacement.journey.journey_id,
                result.replacement.recommendation.route,
            )
        return ExternalOccupancyResponse(
            failed_journey=journey_to_contract(result.failed_journey),
            replacement=JourneyRecommendationResponse(
                recommendation=result.replacement.recommendation,
                journey=journey_to_contract(
                    result.replacement.journey,
                    recommendation_id=(
                        result.replacement.recommendation.recommendation_id
                    ),
                ),
            ),
        )

    @app.post(
        "/api/v2/journeys/{journey_id}/occupy",
        response_model=Journey,
        responses={404: ERROR_RESPONSES[404], 409: ERROR_RESPONSES[409]},
        tags=["journeys"],
    )
    def occupy_journey(
        journey_id: str,
        payload: JourneyCommandRequest,
        request: Request,
        session_id: SessionIdHeader = None,
    ) -> Journey:
        return apply_command("occupy", journey_id, payload, request, session_id)

    @app.post(
        "/api/v2/journeys/{journey_id}/tandem-arrival-replay",
        response_model=DriverTandemArrivalReplay,
        responses={
            404: ERROR_RESPONSES[404],
            409: ERROR_RESPONSES[409],
            503: ERROR_RESPONSES[503],
        },
        tags=["journeys"],
    )
    def tandem_arrival_replay(
        journey_id: str,
        payload: DriverTandemArrivalRequest,
        request: Request,
        session_id: RequiredSessionIdHeader,
    ) -> DriverTandemArrivalReplay:
        store: InMemorySessionStore = request.app.state.session_store
        canonical_payload = {
            "journey_id": journey_id,
            **payload.model_dump(mode="json"),
        }
        with store.atomic():
            record = store.refresh_journey(journey_id)
            if record is None:
                raise JourneyNotFoundError(f"unknown journey: {journey_id}")
            require_driver_session(record, session_id)
            remembered = store.replay_tandem_arrival_command(
                session_id=session_id,
                idempotency_key=payload.idempotency_key,
                payload=canonical_payload,
            )
            if remembered is not None:
                if not isinstance(remembered, DriverTandemArrivalReplay):
                    raise RuntimeError("stored tandem arrival replay has an invalid type")
                return remembered
            if not request.app.state.driver_tandem_arrival_replay_enabled:
                raise HTTPException(
                    status_code=409, detail="tandem arrival replay is disabled"
                )
            source = request.app.state.public_source
            if not isinstance(source, PublicFacilityDataSource):
                raise HTTPException(
                    status_code=409,
                    detail="tandem arrival replay requires the synthetic public source",
                )
            if record.version != payload.expected_version:
                raise VersionConflictError(
                    "expected journey version "
                    f"{payload.expected_version}, current is {record.version}"
                )
            try:
                draft = build_tandem_arrival_draft(
                    journey=record,
                    expected_state_version=payload.expected_state_version,
                    profile=source.get_driver_demo_profile(
                        record.parking_lot_id, session_id=session_id
                    ),
                    layout=source.get_layout(record.parking_lot_id),
                    state=source.get_state(record.parking_lot_id, session_id=session_id),
                    bundle=source.get_driver_bundle(
                        record.parking_lot_id, session_id=session_id
                    ),
                    route_service=route_service,
                    created_at=store.current_wall_time(),
                )
            except TandemArrivalConflictError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except TandemArrivalUnavailableError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            occupied_record = store.occupy(
                journey_id=journey_id,
                expected_version=payload.expected_version,
                idempotency_key=payload.idempotency_key,
            )
            store.remember_tandem_coordination(draft.coordination)
            after_state = source.get_state(
                occupied_record.parking_lot_id, session_id=session_id
            )
            replay = draft.finalize(
                after_facility_state=after_state,
                final_journey=journey_to_contract(occupied_record),
            )
            store.remember_tandem_arrival_replay(
                journey_id=journey_id,
                session_id=session_id,
                idempotency_key=payload.idempotency_key,
                payload=canonical_payload,
                replay=replay,
            )
            return replay

    @app.post(
        "/api/v2/journeys/{journey_id}/cancel",
        response_model=Journey,
        responses={404: ERROR_RESPONSES[404], 409: ERROR_RESPONSES[409]},
        tags=["journeys"],
    )
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

    @app.post(
        "/api/v2/journeys/{journey_id}/depart",
        response_model=Journey,
        responses={404: ERROR_RESPONSES[404], 409: ERROR_RESPONSES[409]},
        tags=["journeys"],
    )
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
                store.advance_driver_demo_profile_after_terminal(
                    journey_id=journey_id,
                    profile_count=source.driver_demo_profile_count(result.parking_lot_id),
                )
            return result

    @app.post(
        "/api/v2/journeys/{journey_id}/tandem-departure-replay",
        response_model=DriverTandemDepartureReplay,
        responses={
            404: ERROR_RESPONSES[404],
            409: ERROR_RESPONSES[409],
            503: ERROR_RESPONSES[503],
        },
        tags=["journeys"],
    )
    def tandem_departure_replay(
        journey_id: str,
        payload: DriverTandemDepartureRequest,
        request: Request,
        session_id: RequiredSessionIdHeader,
    ) -> DriverTandemDepartureReplay:
        store: InMemorySessionStore = request.app.state.session_store
        canonical_payload = {
            "journey_id": journey_id,
            **payload.model_dump(mode="json"),
        }
        with store.atomic():
            record = store.get_journey(journey_id)
            if record is None:
                raise JourneyNotFoundError(f"unknown journey: {journey_id}")
            require_driver_session(record, session_id)
            remembered = store.replay_tandem_departure_command(
                session_id=session_id,
                idempotency_key=payload.idempotency_key,
                payload=canonical_payload,
            )
            if remembered is not None:
                if not isinstance(remembered, DriverTandemDepartureReplay):
                    raise RuntimeError("stored tandem departure replay has an invalid type")
                return remembered
            if not request.app.state.driver_tandem_departure_replay_enabled:
                raise HTTPException(
                    status_code=409, detail="tandem departure replay is disabled"
                )
            source = request.app.state.public_source
            if not isinstance(source, PublicFacilityDataSource):
                raise HTTPException(
                    status_code=409,
                    detail="tandem departure replay requires the synthetic public source",
                )
            if record.version != payload.expected_version:
                raise VersionConflictError(
                    "expected journey version "
                    f"{payload.expected_version}, current is {record.version}"
                )
            try:
                draft = build_tandem_departure_draft(
                    journey=record,
                    expected_state_version=payload.expected_state_version,
                    profile=source.get_driver_demo_profile(
                        record.parking_lot_id, session_id=session_id
                    ),
                    layout=source.get_layout(record.parking_lot_id),
                    state=source.get_state(record.parking_lot_id, session_id=session_id),
                    bundle=source.get_driver_bundle(
                        record.parking_lot_id, session_id=session_id
                    ),
                    route_service=route_service,
                    created_at=store.current_wall_time(),
                    coordination=store.tandem_coordination(journey_id),
                )
            except TandemDepartureConflictError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except TandemDepartureUnavailableError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            departed_record = store.depart(
                journey_id=journey_id,
                expected_version=payload.expected_version,
                idempotency_key=payload.idempotency_key,
            )
            replay = draft.finalize(journey_to_contract(departed_record))
            store.remember_tandem_departure_replay(
                journey_id=journey_id,
                session_id=session_id,
                idempotency_key=payload.idempotency_key,
                payload=canonical_payload,
                replay=replay,
            )
            store.advance_driver_demo_profile_after_terminal(
                journey_id=journey_id,
                profile_count=source.driver_demo_profile_count(
                    departed_record.parking_lot_id
                ),
            )
            return replay

    @app.post(
        "/api/v2/journeys/{journey_id}/reset-demo",
        response_model=Journey,
        responses={404: ERROR_RESPONSES[404], 409: ERROR_RESPONSES[409]},
        tags=["journeys"],
    )
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
            result = store.reset_demo(
                journey_id=journey_id,
                expected_version=payload.expected_version,
                idempotency_key=payload.idempotency_key,
            )
            source = request.app.state.public_source
            if isinstance(source, PublicFacilityDataSource):
                store.advance_driver_demo_profile_after_terminal(
                    journey_id=journey_id,
                    profile_count=source.driver_demo_profile_count(result.parking_lot_id),
                )
            return journey_to_contract(result)

    @app.post(
        "/api/v2/journeys/{journey_id}/reassign",
        response_model=JourneyReassignmentResponse,
        responses={
            404: ERROR_RESPONSES[404],
            409: ERROR_RESPONSES[409],
            503: ERROR_RESPONSES[503],
        },
        tags=["journeys"],
    )
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
            request.app.state.replan_service.register_route(
                result.replacement.journey.journey_id,
                result.replacement.recommendation.route,
            )
        return JourneyReassignmentResponse(
            ended_journey=journey_to_contract(result.ended_journey),
            replacement=JourneyRecommendationResponse(
                recommendation=result.replacement.recommendation,
                journey=journey_to_contract(
                    result.replacement.journey,
                    recommendation_id=result.replacement.recommendation.recommendation_id,
                ),
            ),
        )

    @app.post(
        "/api/v2/simulations/run",
        response_model=SimulationRunResponse,
        responses={
            404: ERROR_RESPONSES[404],
            409: ERROR_RESPONSES[409],
            422: ERROR_RESPONSES[422],
            503: ERROR_RESPONSES[503],
        },
        tags=["simulations"],
    )
    def run_simulation(
        payload: SimulationRunRequest, request: Request
    ) -> SimulationRunResponse:
        source: ParkingDataSource = request.app.state.data_source
        try:
            bundle = source.get_bundle(payload.parking_lot_id)
        except ParkingLotNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ParkingDataUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        try:
            run = DeterministicSimulation(
                layout=bundle.layout,
                seed=payload.seed,
                wall_time_origin=payload.wall_time_origin,
            ).run(
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
        return SimulationRunResponse(
            seed=run.seed,
            events=run.events,
            summary=SimulationSummaryResponse(**asdict(run.summary)),
        )

    @app.post(
        "/api/v2/simulations/replay",
        response_model=SimulationSummaryResponse,
        responses={
            404: ERROR_RESPONSES[404],
            409: ERROR_RESPONSES[409],
            422: ERROR_RESPONSES[422],
            503: ERROR_RESPONSES[503],
        },
        tags=["simulations"],
    )
    def replay_simulation(
        payload: SimulationReplayRequest, request: Request
    ) -> SimulationSummaryResponse:
        source: ParkingDataSource = request.app.state.data_source
        try:
            bundle = source.get_bundle(payload.parking_lot_id)
        except ParkingLotNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ParkingDataUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        try:
            summary = DeterministicSimulation(
                layout=bundle.layout,
                seed=payload.seed,
                wall_time_origin=payload.wall_time_origin,
            ).replay(payload.events)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return SimulationSummaryResponse(**asdict(summary))

    return app


app = create_app(scenario_profile=ScenarioProfile.PUBLIC)
