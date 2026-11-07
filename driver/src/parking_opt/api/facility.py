"""Additive complete-facility contract boundary with fail-closed defaults."""

from __future__ import annotations

from typing import Protocol

from parking_opt.api.models import (
    ParkingFacilityLayout,
    ParkingFacilityStateSnapshot,
    RoutePreview,
    RoutePreviewRequest,
)


class FacilityDataError(RuntimeError):
    """Base error for complete-facility resources."""


class FacilityNotFoundError(FacilityDataError):
    """The public facility catalog has no requested parking lot."""


class FacilityVersionConflictError(FacilityDataError):
    """The request references a stale or mismatched facility state."""


class FacilityDataUnavailableError(FacilityDataError):
    """The configured source cannot provide a complete safe resource."""


class ParkingFacilityDataSource(Protocol):
    """Public facility source; scenario selection is deliberately not exposed."""

    def get_layout(self, parking_lot_id: str) -> ParkingFacilityLayout: ...

    def get_state(
        self, parking_lot_id: str, *, session_id: str
    ) -> ParkingFacilityStateSnapshot: ...

    def preview_route(
        self,
        parking_lot_id: str,
        *,
        session_id: str,
        request: RoutePreviewRequest,
    ) -> RoutePreview: ...


class UnavailableParkingFacilityDataSource:
    """R0b default until R1 publishes the four complete synthetic facilities."""

    _MESSAGE = "complete parking facility data is not published"

    def get_layout(self, parking_lot_id: str) -> ParkingFacilityLayout:
        raise FacilityDataUnavailableError(f"{self._MESSAGE} for {parking_lot_id}")

    def get_state(
        self, parking_lot_id: str, *, session_id: str
    ) -> ParkingFacilityStateSnapshot:
        del session_id
        raise FacilityDataUnavailableError(f"{self._MESSAGE} for {parking_lot_id}")

    def preview_route(
        self,
        parking_lot_id: str,
        *,
        session_id: str,
        request: RoutePreviewRequest,
    ) -> RoutePreview:
        del session_id, request
        raise FacilityDataUnavailableError(f"{self._MESSAGE} for {parking_lot_id}")
