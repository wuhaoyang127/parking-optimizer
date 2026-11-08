from __future__ import annotations

from parking_opt.api.models import (
    FacilityBufferState,
    FacilityInterFloorConnection,
    FacilityObservationSource,
    FacilitySourceKind,
    FacilitySourceStatus,
    FacilitySpaceState,
    HealthStatus,
    ParkingFacilityLayout,
    ParkingFacilityStateSnapshot,
    Route,
    RouteInstruction,
    RoutePreview,
    SpaceStatus,
)
from facility_layout_fixture import OBSERVED_AT, _facility_layout


def _facility_state() -> ParkingFacilityStateSnapshot:
    return ParkingFacilityStateSnapshot(
        parking_lot_id="lot-school",
        layout_version="facility-school-v1",
        scenario_id="school-full-demo",
        scenario_version="scenario-school-v1",
        state_version="state-1",
        observed_at=OBSERVED_AT,
        source=FacilitySourceStatus(
            source_kind=FacilitySourceKind.SYNTHETIC,
            health=HealthStatus.HEALTHY,
            source_name="m4-contract-test",
            updated_at=OBSERVED_AT,
        ),
        spaces=(
            FacilitySpaceState(
                space_id="T-01",
                observed_status=SpaceStatus.AVAILABLE,
                observation_source=FacilityObservationSource.SYNTHETIC_TRUTH,
                effective_status=SpaceStatus.AVAILABLE,
                assignable=True,
            ),
            FacilitySpaceState(
                space_id="T-02",
                observed_status=SpaceStatus.OCCUPIED,
                observation_source=FacilityObservationSource.SYNTHETIC_TRUTH,
                effective_status=SpaceStatus.OCCUPIED,
                assignable=False,
                reason_codes=("OCCUPIED",),
            ),
        ),
        buffers=(
            FacilityBufferState(
                buffer_id="buffer-1",
                status=SpaceStatus.AVAILABLE,
                observation_source=FacilityObservationSource.SYNTHETIC_TRUTH,
            ),
        ),
    )


def _two_floor_layout() -> ParkingFacilityLayout:
    payload = _facility_layout().model_dump(mode="json")
    payload["floors"].append(
        {"floor_id": "floor-2", "label": "二层", "elevation_m": 3, "bounds": payload["bounds"]}
    )
    payload["nodes"].extend(
        [
            {"node_id": "ramp-floor-1", "floor_id": "floor-1", "coordinate": {"x_m": 35, "y_m": 5}, "kind": "inter_floor", "label": "坡道一层"},
            {"node_id": "ramp-floor-2", "floor_id": "floor-2", "coordinate": {"x_m": 5, "y_m": 5}, "kind": "inter_floor", "label": "坡道二层"},
        ]
    )
    payload["edges"].append(
        {
            "edge_id": "edge-ramp",
            "from_node_id": "ramp-floor-1",
            "to_node_id": "ramp-floor-2",
            "centerline": [{"x_m": 35, "y_m": 5}, {"x_m": 5, "y_m": 5}],
            "width_m": 4,
            "distance_m": 30,
            "base_travel_time_s": 20,
            "directed": True,
            "traversal_kind": "ramp",
            "channel_zone_ids": [],
        }
    )
    payload["inter_floor_connections"] = [
        FacilityInterFloorConnection(
            connection_id="connection-ramp",
            from_floor_id="floor-1",
            to_floor_id="floor-2",
            kind="ramp",
            edge_ids=("edge-ramp",),
        ).model_dump(mode="json")
    ]
    return ParkingFacilityLayout.model_validate(payload)


def _route_preview() -> RoutePreview:
    return RoutePreview(
        parking_lot_id="lot-school",
        layout_version="facility-school-v1",
        scenario_version="scenario-school-v1",
        state_version="state-1",
        observed_at=OBSERVED_AT,
        entrance_id="entrance-south",
        target_space_id="T-01",
        route=Route(
            parking_lot_id="lot-school",
            layout_version="facility-school-v1",
            cost_version="cost-1",
            from_node_id="entry",
            to_node_id="access-1",
            node_ids=("entry", "junction", "access-1"),
            edge_ids=("edge-entry", "edge-access-1"),
            distance_m=20,
            dynamic_eta_s=10,
            instructions=(
                RouteInstruction(sequence=1, edge_id="edge-entry", text="沿入口通道直行", distance_m=10, travel_time_s=5),
                RouteInstruction(sequence=2, edge_id="edge-access-1", text="继续前往目标车位", distance_m=10, travel_time_s=5),
            ),
        ),
    )
