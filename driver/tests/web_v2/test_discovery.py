from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from parking_opt.api.discovery import (
    DiscoveryDataUnavailableError,
    RealDiscoveryDataSource,
    SyntheticDiscoveryDataSource,
    built_in_discovery_area,
    load_discovery_area,
)
from parking_opt.api.models import DiscoveryArea, HealthStatus
from parking_opt.api.scenarios import built_in_scenarios

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_exported_discovery_area_matches_authoritative_builder() -> None:
    exported = load_discovery_area(
        REPO_ROOT / "data" / "synthetic" / "web-v2" / "discovery-area.v1.json"
    )
    assert exported == built_in_discovery_area()
    assert {item.parking_lot_id for item in exported.lots} == {
        "lot-commercial",
        "lot-hospital",
        "lot-school",
        "lot-transport-hub",
    }


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("lots", 0, "position", "x_pct"), -1),
        (("lots", 0, "offsite_estimates", 0, "distance_m"), -1),
        (("lots", 0, "offsite_estimates", 0, "eta_s"), -1),
        (("lots", 0, "opening_hours_label"), ""),
    ],
)
def test_discovery_contract_rejects_invalid_boundaries(
    path: tuple[object, ...], value: object
) -> None:
    payload = built_in_discovery_area().model_dump(mode="json")
    target: object = payload
    for key in path[:-1]:
        target = target[key]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]
    with pytest.raises(ValidationError):
        DiscoveryArea.model_validate(payload)


def test_discovery_contract_requires_every_reference_for_every_lot() -> None:
    payload = built_in_discovery_area().model_dump(mode="json")
    payload["lots"][0]["offsite_estimates"].pop()
    with pytest.raises(ValidationError, match="every discovery lot"):
        DiscoveryArea.model_validate(payload)


def test_synthetic_discovery_source_requires_matching_parking_lot_scope() -> None:
    with pytest.raises(ValueError, match="same parking lot IDs"):
        SyntheticDiscoveryDataSource(built_in_discovery_area(), ())


def test_unavailable_and_unconfigured_discovery_sources_fail_closed() -> None:
    lots = (item.parking_lot for item in built_in_scenarios().values())
    unavailable = built_in_discovery_area().model_copy(
        update={"source_health": HealthStatus.UNAVAILABLE}
    )
    source = SyntheticDiscoveryDataSource(unavailable, lots)
    with pytest.raises(DiscoveryDataUnavailableError, match="unavailable"):
        source.get_area()
    with pytest.raises(DiscoveryDataUnavailableError, match="not configured"):
        RealDiscoveryDataSource().get_area()
