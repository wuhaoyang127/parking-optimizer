"""Parking-data source boundary with explicit synthetic opt-in and real fail-closed behavior."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Protocol

from parking_opt.api.models import ScenarioBundle


class ParkingDataUnavailableError(RuntimeError):
    """The requested source cannot provide a complete, safe snapshot."""


class ParkingLotNotFoundError(ParkingDataUnavailableError):
    """The configured source has no parking lot with the requested ID."""


class ParkingDataSourceNotConfiguredError(ParkingDataUnavailableError):
    """The selected data mode has no configured source adapter."""


class ParkingDataSource(Protocol):
    def list_bundles(self) -> tuple[ScenarioBundle, ...]: ...

    def get_bundle(self, parking_lot_id: str) -> ScenarioBundle: ...


class ScenarioProfile(StrEnum):
    PUBLIC = "public"
    LEGACY = "legacy"


class SyntheticParkingDataSource:
    """Read-only source backed by explicit deterministic fixtures."""

    def __init__(
        self,
        scenarios: Mapping[str, ScenarioBundle],
        *,
        profile: ScenarioProfile,
    ) -> None:
        self._by_lot = {item.parking_lot.parking_lot_id: item for item in scenarios.values()}
        if len(self._by_lot) != len(scenarios):
            raise ValueError("synthetic fixtures contain duplicate parking_lot_id values")
        self._profile = profile

    @property
    def profile(self) -> ScenarioProfile:
        """Expose internal source identity without creating an HTTP selector."""

        return self._profile

    def list_bundles(self) -> tuple[ScenarioBundle, ...]:
        return tuple(
            sorted(self._by_lot.values(), key=lambda item: item.parking_lot.parking_lot_id)
        )

    def get_bundle(self, parking_lot_id: str) -> ScenarioBundle:
        try:
            return self._by_lot[parking_lot_id]
        except KeyError as exc:
            raise ParkingLotNotFoundError(f"unknown parking lot: {parking_lot_id}") from exc


class UnpublishedPublicParkingDataSource:
    """Fail closed until R1 publishes complete public scenario bundles."""

    _MESSAGE = "complete public parking scenarios are not published"

    def list_bundles(self) -> tuple[ScenarioBundle, ...]:
        raise ParkingDataSourceNotConfiguredError(self._MESSAGE)

    def get_bundle(self, parking_lot_id: str) -> ScenarioBundle:
        raise ParkingDataSourceNotConfiguredError(f"{self._MESSAGE} for {parking_lot_id}")


class RealParkingDataSource:
    """Future adapter boundary; M2 intentionally has no implicit synthetic fallback."""

    def list_bundles(self) -> tuple[ScenarioBundle, ...]:
        raise ParkingDataSourceNotConfiguredError(
            "real parking data source is not configured"
        )

    def get_bundle(self, parking_lot_id: str) -> ScenarioBundle:
        raise ParkingDataSourceNotConfiguredError(
            f"real parking data source is not configured for {parking_lot_id}"
        )
