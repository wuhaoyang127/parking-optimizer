"""Project session-scoped synthetic claims onto read-only parking-lot summaries."""

from __future__ import annotations

from parking_opt.api.models import ParkingLot, ScenarioBundle, SpaceStatus
from parking_opt.api.sessions import SessionAvailabilitySnapshot


def project_parking_lots(
    bundles: tuple[ScenarioBundle, ...],
    snapshot: SessionAvailabilitySnapshot,
) -> tuple[ParkingLot, ...]:
    """Return immutable summaries using set-based, non-duplicating exclusions."""

    exclusions_by_scope = {
        (item.scenario_id, item.parking_lot_id): (
            item.claimed_space_ids | item.unavailable_space_ids
        )
        for item in snapshot.scopes
    }
    if len(exclusions_by_scope) != len(snapshot.scopes):
        raise ValueError("availability snapshot contains duplicate scopes")

    projected: list[ParkingLot] = []
    for bundle in bundles:
        scope = (bundle.scenario_id, bundle.parking_lot.parking_lot_id)
        if scope not in exclusions_by_scope:
            raise ValueError(f"availability snapshot is missing scope: {scope}")
        base_available = {
            item.space_id
            for item in bundle.layout.spaces
            if item.status is SpaceStatus.AVAILABLE
        }
        effective_available = base_available - exclusions_by_scope[scope]
        projected.append(
            bundle.parking_lot.model_copy(
                update={
                    "available_spaces": len(effective_available),
                    "updated_at": snapshot.observed_at,
                }
            )
        )
    return tuple(projected)
