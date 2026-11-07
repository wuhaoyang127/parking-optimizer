from __future__ import annotations

from datetime import UTC, datetime

from parking_opt.api.availability import project_parking_lots
from parking_opt.api.models import SpaceStatus
from parking_opt.api.scenarios import built_in_scenarios
from parking_opt.api.sessions import (
    AvailabilityScopeSnapshot,
    SessionAvailabilitySnapshot,
    SessionNamespace,
)


def test_projection_uses_space_id_sets_without_double_subtraction() -> None:
    bundle = built_in_scenarios()["school-demo"]
    base_available = {
        item.space_id for item in bundle.layout.spaces if item.status is SpaceStatus.AVAILABLE
    }
    base_occupied = next(
        item.space_id for item in bundle.layout.spaces if item.status is SpaceStatus.OCCUPIED
    )
    excluded = next(iter(base_available))
    snapshot = SessionAvailabilitySnapshot(
        session_id="session-projector",
        namespace=SessionNamespace.DRIVER,
        observed_at=datetime(2026, 8, 13, 1, 0, tzinfo=UTC),
        scopes=(
            AvailabilityScopeSnapshot(
                scenario_id=bundle.scenario_id,
                parking_lot_id=bundle.parking_lot.parking_lot_id,
                claimed_space_ids=frozenset({excluded, base_occupied}),
                unavailable_space_reasons=((excluded, "EXTERNAL_SPACE_OCCUPIED"),),
            ),
        ),
    )

    projected = project_parking_lots((bundle,), snapshot)[0]

    assert projected.available_spaces == len(base_available) - 1
    assert projected.updated_at == snapshot.observed_at
    assert projected.data_source.updated_at == bundle.parking_lot.data_source.updated_at
