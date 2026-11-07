"""Versioned, deterministic area-discovery data independent of the frozen ParkingLot v2 model."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from parking_opt.api.models import (
    DataMode,
    DiscoveryArea,
    DiscoveryLotSummary,
    DiscoveryPosition,
    DiscoveryReferencePoint,
    HealthStatus,
    OffsiteEstimate,
    ParkingLot,
)

DISCOVERY_UPDATED_AT = datetime(2026, 8, 13, 9, 0, tzinfo=UTC)


class DiscoveryDataUnavailableError(RuntimeError):
    """The discovery source cannot provide a complete safe snapshot."""


class DiscoveryDataSource(Protocol):
    def get_area(self) -> DiscoveryArea: ...


class SyntheticDiscoveryDataSource:
    """Read-only deterministic discovery source validated against the parking source."""

    def __init__(self, area: DiscoveryArea, parking_lots: Iterable[ParkingLot]) -> None:
        lot_ids = {item.parking_lot_id for item in parking_lots}
        discovery_ids = {item.parking_lot_id for item in area.lots}
        if lot_ids != discovery_ids:
            raise ValueError("discovery and parking sources must expose the same parking lot IDs")
        if area.source_mode is not DataMode.SYNTHETIC or not area.synthetic:
            raise ValueError("synthetic discovery source requires explicit synthetic truth")
        self._area = area

    def get_area(self) -> DiscoveryArea:
        if self._area.source_health is HealthStatus.UNAVAILABLE:
            raise DiscoveryDataUnavailableError("discovery data source is unavailable")
        return self._area


class RealDiscoveryDataSource:
    """Future real adapter boundary with no implicit synthetic fallback."""

    def get_area(self) -> DiscoveryArea:
        raise DiscoveryDataUnavailableError("real discovery data source is not configured")


class UnpublishedPublicDiscoveryDataSource:
    """Fail closed until R1 binds discovery summaries to public complete scenarios."""

    def get_area(self) -> DiscoveryArea:
        raise DiscoveryDataUnavailableError("complete public discovery data is not published")


def _estimates(*values: tuple[str, int, int]) -> tuple[OffsiteEstimate, ...]:
    return tuple(
        OffsiteEstimate(reference_id=reference_id, distance_m=distance_m, eta_s=eta_s)
        for reference_id, distance_m, eta_s in values
    )


def built_in_discovery_area() -> DiscoveryArea:
    """Return the fixed synthetic discovery presentation used by M4 P1."""

    return DiscoveryArea(
        area_id="demo-city-core",
        display_version="discovery-2026-08-13-a",
        synthetic=True,
        source_mode=DataMode.SYNTHETIC,
        source_health=HealthStatus.HEALTHY,
        default_reference_id="reference-south",
        references=(
            DiscoveryReferencePoint(
                reference_id="reference-south",
                label="南侧参考点",
                position=DiscoveryPosition(x_pct=46, y_pct=84),
            ),
            DiscoveryReferencePoint(
                reference_id="reference-west",
                label="西侧参考点",
                position=DiscoveryPosition(x_pct=12, y_pct=48),
            ),
            DiscoveryReferencePoint(
                reference_id="reference-east",
                label="东侧参考点",
                position=DiscoveryPosition(x_pct=88, y_pct=48),
            ),
        ),
        lots=(
            DiscoveryLotSummary(
                parking_lot_id="lot-commercial",
                opening_hours_label="每日 08:00-23:30",
                position=DiscoveryPosition(x_pct=78, y_pct=20),
                offsite_estimates=_estimates(
                    ("reference-south", 450, 120),
                    ("reference-west", 1080, 250),
                    ("reference-east", 380, 95),
                ),
            ),
            DiscoveryLotSummary(
                parking_lot_id="lot-school",
                opening_hours_label="每日 06:30-23:00",
                position=DiscoveryPosition(x_pct=53, y_pct=39),
                offsite_estimates=_estimates(
                    ("reference-south", 680, 150),
                    ("reference-west", 730, 165),
                    ("reference-east", 620, 140),
                ),
            ),
            DiscoveryLotSummary(
                parking_lot_id="lot-hospital",
                opening_hours_label="24 小时开放",
                position=DiscoveryPosition(x_pct=20, y_pct=66),
                offsite_estimates=_estimates(
                    ("reference-south", 920, 210),
                    ("reference-west", 310, 80),
                    ("reference-east", 1360, 300),
                ),
            ),
            DiscoveryLotSummary(
                parking_lot_id="lot-transport-hub",
                opening_hours_label="24 小时开放",
                position=DiscoveryPosition(x_pct=71, y_pct=70),
                offsite_estimates=_estimates(
                    ("reference-south", 1250, 280),
                    ("reference-west", 1580, 350),
                    ("reference-east", 540, 130),
                ),
            ),
        ),
        updated_at=DISCOVERY_UPDATED_AT,
    )


def load_discovery_area(path: Path) -> DiscoveryArea:
    """Load and validate one exported discovery-area fixture."""

    return DiscoveryArea.model_validate_json(path.read_text(encoding="utf-8"))


def export_discovery_area(path: Path) -> None:
    """Export the discovery fixture with stable UTF-8 formatting."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        built_in_discovery_area().model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
