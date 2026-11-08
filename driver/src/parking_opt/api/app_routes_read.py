"""Read, discovery, facility, and recommend routes for web-v2."""
from __future__ import annotations
from fastapi import FastAPI, HTTPException, Query, Request, Response
from parking_opt.api.app_contracts import (
    ERROR_RESPONSES,
    RequiredSessionIdHeader,
    SessionIdHeader,
)
from parking_opt.api.app_helpers import driver_bundle, driver_bundles
from parking_opt.api.availability import project_parking_lots
from parking_opt.api.discovery import DiscoveryDataSource, DiscoveryDataUnavailableError
from parking_opt.api.facility import (
    FacilityDataUnavailableError,
    FacilityNotFoundError,
    FacilityVersionConflictError,
    ParkingFacilityDataSource,
)
from parking_opt.api.models import (
    AlgorithmDescriptor,
    DiscoveryArea,
    HealthResponse,
    Layout,
    ParkingFacilityLayout,
    ParkingFacilityStateSnapshot,
    ParkingLot,
    Recommendation,
    RecommendationRequest,
    RoutePreview,
    RoutePreviewRequest,
    SpaceStatus,
)
from parking_opt.api.registry import algorithm_registry, require_online_algorithm
from parking_opt.api.services.online_rule import OnlineRuleServiceV2
from parking_opt.api.sessions import InMemorySessionStore, SessionNamespace
from parking_opt.api.sources import (
    ParkingDataSource,
    ParkingDataUnavailableError,
    ParkingLotNotFoundError,
)
def register_read_routes(app: FastAPI) -> None:
    @app.get("/api/v2/health", response_model=HealthResponse, tags=["system"])
    def health(request: Request) -> HealthResponse:
        return HealthResponse(
            status="ok",
            data_mode=request.app.state.data_mode.value,
        )
    @app.get("/api/v2/parking-lots", response_model=list[ParkingLot], responses={503: ERROR_RESPONSES[503]}, tags=["parking-lots"])
    def list_parking_lots(request: Request, response: Response, session_id: SessionIdHeader = None,) -> list[ParkingLot]:
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
                scopes=tuple((item.scenario_id, item.parking_lot.parking_lot_id) for item in bundles),
            )
            return list(project_parking_lots(bundles, snapshot))
        except ParkingDataUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    @app.get("/api/v2/discovery-area", response_model=DiscoveryArea, responses={503: ERROR_RESPONSES[503]}, tags=["parking-lots"])
    def get_discovery_area(request: Request) -> DiscoveryArea:
        source: DiscoveryDataSource = request.app.state.discovery_source
        try:
            return source.get_area()
        except DiscoveryDataUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    @app.get("/api/v2/parking-lots/{parking_lot_id}", response_model=ParkingLot, responses={404: ERROR_RESPONSES[404], 503: ERROR_RESPONSES[503]}, tags=["parking-lots"])
    def get_parking_lot(parking_lot_id: str, request: Request, response: Response, session_id: SessionIdHeader = None,) -> ParkingLot:
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
    @app.get("/api/v2/parking-lots/{parking_lot_id}/layout", response_model=Layout, responses={404: ERROR_RESPONSES[404], 503: ERROR_RESPONSES[503]}, tags=["parking-lots"])
    def get_layout(parking_lot_id: str, request: Request) -> Layout:
        source: ParkingDataSource = request.app.state.data_source
        try:
            return source.get_bundle(parking_lot_id).layout
        except ParkingLotNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ParkingDataUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    @app.get("/api/v2/parking-lots/{parking_lot_id}/facility-layout", response_model=ParkingFacilityLayout, responses={404: ERROR_RESPONSES[404], 422: ERROR_RESPONSES[422], 503: ERROR_RESPONSES[503]}, tags=["parking-lots"])
    def get_facility_layout(parking_lot_id: str, request: Request, response: Response,) -> ParkingFacilityLayout:
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
    @app.get("/api/v2/parking-lots/{parking_lot_id}/facility-state", response_model=ParkingFacilityStateSnapshot, responses={404: ERROR_RESPONSES[404], 422: ERROR_RESPONSES[422], 503: ERROR_RESPONSES[503]}, tags=["parking-lots"])
    def get_facility_state(parking_lot_id: str, request: Request, response: Response, session_id: RequiredSessionIdHeader,) -> ParkingFacilityStateSnapshot:
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
    @app.post("/api/v2/parking-lots/{parking_lot_id}/route-previews", response_model=RoutePreview, responses={404: ERROR_RESPONSES[404], 409: ERROR_RESPONSES[409], 422: ERROR_RESPONSES[422], 503: ERROR_RESPONSES[503]}, tags=["parking-lots"])
    def preview_facility_route(parking_lot_id: str, payload: RoutePreviewRequest, request: Request, response: Response, session_id: RequiredSessionIdHeader,) -> RoutePreview:
        source: ParkingFacilityDataSource = request.app.state.facility_source
        response.headers["Cache-Control"] = "no-store"
        response.headers["Vary"] = "X-Session-ID"
        if request.query_params:
            raise HTTPException(status_code=422, detail="route preview accepts no selectors")
        try:
            preview = source.preview_route(parking_lot_id, session_id=session_id, request=payload)
            if preview.parking_lot_id != parking_lot_id:
                raise FacilityDataUnavailableError("route preview scope mismatch")
            if (preview.layout_version != payload.layout_version or preview.scenario_version != payload.scenario_version or preview.state_version != payload.state_version or preview.entrance_id != payload.entrance_id or preview.target_space_id != payload.target_space_id):
                raise FacilityVersionConflictError("route preview request identity mismatch")
            current_state = source.get_state(parking_lot_id, session_id=session_id)
            if (current_state.layout_version != payload.layout_version or current_state.scenario_version != payload.scenario_version or current_state.state_version != payload.state_version):
                raise FacilityVersionConflictError("route preview state is stale")
            target_state = next((item for item in current_state.spaces if item.space_id == payload.target_space_id), None)
            if target_state is None:
                raise FacilityDataUnavailableError("route preview target state is missing")
            if not target_state.assignable or target_state.effective_status is not SpaceStatus.AVAILABLE:
                raise FacilityVersionConflictError("route preview target is no longer assignable")
            try:
                preview.require_context(request=payload, layout=source.get_layout(parking_lot_id), state=current_state)
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
    @app.post("/api/v2/recommendations", response_model=Recommendation, responses={404: ERROR_RESPONSES[404], 409: ERROR_RESPONSES[409], 422: ERROR_RESPONSES[422], 500: ERROR_RESPONSES[500], 503: ERROR_RESPONSES[503]}, tags=["recommendations"])
    def recommend(payload: RecommendationRequest, request: Request) -> Recommendation:
        source: ParkingDataSource = request.app.state.data_source
        recommender: OnlineRuleServiceV2 = request.app.state.recommender
        try:
            require_online_algorithm(payload.algorithm_id)
            bundle = driver_bundle(source, payload.driver.parking_lot_id, payload.driver.session_id)
            return recommender.recommend(payload.driver, bundle.layout, bundle.cost_snapshot, bundle.parking_lot.data_source)
        except ParkingLotNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ParkingDataUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
