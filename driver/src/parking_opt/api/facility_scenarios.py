"""Deterministic M4 public facilities and their Layout 2.0 projections."""

from __future__ import annotations

from parking_opt.api.facility import (
    FacilityDataUnavailableError,
    FacilityNotFoundError,
    FacilityVersionConflictError,
)
from parking_opt.api.facility_scenarios_bundle import build_public_facility_scenarios
from parking_opt.api.facility_scenarios_profiles import _build_driver_demo_scenarios
from parking_opt.api.facility_scenarios_state import FacilityStateProjectionMixin
from parking_opt.api.facility_scenarios_types import (
    DRIVER_DEMO_PROFILE_SPECS,
    PUBLISHED_AT,
    PUBLIC_SPECS,
    DriverDemoProfileSpec,
    FacilityScenarioSpec,
    PublishedDriverDemoScenario,
    PublishedFacilityScenario,
)
from parking_opt.api.models import (
    DriverDemoProfile,
    ParkingFacilityLayout,
    ParkingFacilityStateSnapshot,
    RoutePreview,
    RoutePreviewRequest,
    ScenarioBundle,
)
from parking_opt.api.routing import RouteCostService, RouteNotFoundError
from parking_opt.api.sessions import InMemorySessionStore
from parking_opt.api.sources import ParkingLotNotFoundError, ScenarioProfile


class PublicFacilityDataSource(FacilityStateProjectionMixin):
    """Public data source shared by compatibility and facility endpoints."""

    def __init__(
        self,
        *,
        session_store: InMemorySessionStore,
        route_service: RouteCostService,
        profiles_enabled: bool = True,
    ) -> None:
        self._by_lot = build_public_facility_scenarios()
        self._driver_profiles = {
            lot_id: _build_driver_demo_scenarios(scenario)
            for lot_id, scenario in self._by_lot.items()
        }
        self._session_store = session_store
        self._route_service = route_service
        for scenario in self._by_lot.values():
            route_service.register_entrance_headings(
                scenario.layout.parking_lot_id,
                scenario.layout.layout_version,
                {item.node_id: item.initial_heading_deg for item in scenario.layout.entrances},
            )
        self._profiles_enabled = profiles_enabled
        self._profile = ScenarioProfile.PUBLIC

    @property
    def profile(self) -> ScenarioProfile:
        return self._profile

    @property
    def driver_demo_profiles_enabled(self) -> bool:
        return self._profiles_enabled

    def list_bundles(self) -> tuple[ScenarioBundle, ...]:
        return tuple(self._by_lot[key].bundle for key in sorted(self._by_lot))

    def get_bundle(self, parking_lot_id: str) -> ScenarioBundle:
        try:
            return self._by_lot[parking_lot_id].bundle
        except KeyError as exc:
            raise ParkingLotNotFoundError(f"unknown parking lot: {parking_lot_id}") from exc

    def list_driver_bundles(self, *, session_id: str) -> tuple[ScenarioBundle, ...]:
        return tuple(
            self.get_driver_bundle(parking_lot_id, session_id=session_id)
            for parking_lot_id in sorted(self._by_lot)
        )

    def get_driver_bundle(self, parking_lot_id: str, *, session_id: str) -> ScenarioBundle:
        return self._driver_scenario(parking_lot_id, session_id=session_id).bundle

    def get_driver_demo_profile(self, parking_lot_id: str, *, session_id: str) -> DriverDemoProfile:
        return self._driver_scenario(parking_lot_id, session_id=session_id).demo_profile

    def driver_demo_profile_count(self, parking_lot_id: str) -> int:
        try:
            return len(self._driver_profiles[parking_lot_id]) if self._profiles_enabled else 1
        except KeyError as exc:
            raise ParkingLotNotFoundError(f"unknown parking lot: {parking_lot_id}") from exc

    def driver_demo_profile_index(self, parking_lot_id: str, *, profile_id: str) -> int:
        try:
            profiles = self._driver_profiles[parking_lot_id]
        except KeyError as exc:
            raise ParkingLotNotFoundError(f"unknown parking lot: {parking_lot_id}") from exc
        for index, profile in enumerate(profiles):
            if profile.demo_profile.profile_id == profile_id:
                return index
        raise FacilityVersionConflictError(f"unknown driver demo profile: {profile_id}")

    def get_layout(self, parking_lot_id: str) -> ParkingFacilityLayout:
        return self._scenario(parking_lot_id).layout

    def preview_route(
        self, parking_lot_id: str, *, session_id: str, request: RoutePreviewRequest
    ) -> RoutePreview:
        scenario = self._driver_scenario(parking_lot_id, session_id=session_id)
        state = self.get_state(parking_lot_id, session_id=session_id)
        if (
            request.layout_version != scenario.layout.layout_version
            or request.scenario_version != state.scenario_version
            or request.state_version != state.state_version
        ):
            raise FacilityVersionConflictError("route preview state is stale")
        entrance = next(
            (item for item in scenario.layout.entrances if item.entrance_id == request.entrance_id),
            None,
        )
        target = next(
            (item for item in scenario.layout.spaces if item.space_id == request.target_space_id),
            None,
        )
        if entrance is None or target is None:
            raise FacilityDataUnavailableError("route preview endpoint is unknown")
        try:
            route = self._route_service.route(
                scenario.bundle.layout,
                scenario.bundle.cost_snapshot,
                from_node_id=entrance.node_id,
                to_node_id=target.access_node_id,
            )
        except RouteNotFoundError as exc:
            raise FacilityDataUnavailableError(str(exc)) from exc
        return RoutePreview(
            parking_lot_id=parking_lot_id,
            layout_version=scenario.layout.layout_version,
            scenario_version=state.scenario_version,
            state_version=state.state_version,
            observed_at=state.observed_at,
            entrance_id=request.entrance_id,
            target_space_id=request.target_space_id,
            route=route,
        )

    def _scenario(self, parking_lot_id: str) -> PublishedFacilityScenario:
        try:
            return self._by_lot[parking_lot_id]
        except KeyError as exc:
            raise FacilityNotFoundError(f"unknown parking lot: {parking_lot_id}") from exc

    def _driver_scenario(self, parking_lot_id: str, *, session_id: str) -> PublishedDriverDemoScenario:
        try:
            profiles = self._driver_profiles[parking_lot_id]
        except KeyError as exc:
            raise FacilityNotFoundError(f"unknown parking lot: {parking_lot_id}") from exc
        if not self._profiles_enabled:
            return profiles[0]
        index = self._session_store.driver_demo_profile_index(
            session_id=session_id,
            parking_lot_id=parking_lot_id,
            profile_count=len(profiles),
        )
        return profiles[index]
