from __future__ import annotations

from parking_opt.api.models import (
    ParkingFacilityLayout,
    ParkingFacilityStateSnapshot,
    RoutePreview,
    RoutePreviewRequest,
)
from facility_layout_fixture import _facility_layout
from facility_state_fixture import _facility_state, _route_preview


class StubFacilitySource:
    def __init__(self) -> None:
        self.sessions: list[str] = []
        self.preview_requests: list[RoutePreviewRequest] = []

    def get_layout(self, parking_lot_id: str) -> ParkingFacilityLayout:
        assert parking_lot_id == "lot-school"
        return _facility_layout()

    def get_state(self, parking_lot_id: str, *, session_id: str) -> ParkingFacilityStateSnapshot:
        assert parking_lot_id == "lot-school"
        self.sessions.append(session_id)
        return _facility_state()

    def preview_route(
        self,
        parking_lot_id: str,
        *,
        session_id: str,
        request: RoutePreviewRequest,
    ) -> RoutePreview:
        assert parking_lot_id == "lot-school"
        self.sessions.append(session_id)
        self.preview_requests.append(request)
        return _route_preview()


class CorruptRouteSource(StubFacilitySource):
    def preview_route(
        self,
        parking_lot_id: str,
        *,
        session_id: str,
        request: RoutePreviewRequest,
    ) -> RoutePreview:
        preview = super().preview_route(parking_lot_id, session_id=session_id, request=request)
        route = preview.route.model_copy(update={"edge_ids": ("missing-edge",)})
        return preview.model_copy(update={"route": route})


class StaleStateSource(StubFacilitySource):
    def get_state(self, parking_lot_id: str, *, session_id: str) -> ParkingFacilityStateSnapshot:
        state = super().get_state(parking_lot_id, session_id=session_id)
        return state.model_copy(update={"state_version": "state-2"})


class UnavailableTargetSource(StubFacilitySource):
    def get_state(self, parking_lot_id: str, *, session_id: str) -> ParkingFacilityStateSnapshot:
        state = super().get_state(parking_lot_id, session_id=session_id)
        unavailable_target = state.spaces[0].model_copy(
            update={"assignable": False, "reason_codes": ("ROUTE_BLOCKED",)}
        )
        return state.model_copy(update={"spaces": (unavailable_target, *state.spaces[1:])})
