"""Compatibility ScenarioBundle projection for public facilities."""

from __future__ import annotations

from parking_opt.api.facility_scenarios_geom import _project_node
from parking_opt.api.facility_scenarios_types import (
    PUBLISHED_AT,
    FacilityScenarioSpec,
    ParkingFacilityLayout,
    ParkingFacilityStateSnapshot,
)
from parking_opt.api.models import (
    BufferSpace,
    CostSnapshot,
    DataMode,
    DataSourceStatus,
    HealthStatus,
    Layout,
    ParkingLot,
    ParkingSpace,
    RoadEdge,
    ScenarioBundle,
    SpaceStatus,
    TandemGroup,
)

from parking_opt.api.facility_scenarios_types import PUBLIC_SPECS, PublishedFacilityScenario


def _project_bundle(
    spec: FacilityScenarioSpec, layout: ParkingFacilityLayout, state: ParkingFacilityStateSnapshot
) -> ScenarioBundle:
    states = {item.space_id: item for item in state.spaces}
    road_layout = Layout(
        parking_lot_id=layout.parking_lot_id,
        layout_version=layout.layout_version,
        coordinate_origin_note=layout.coordinate_origin_note,
        entrance_node_ids=tuple(item.node_id for item in layout.entrances),
        exit_node_ids=tuple(item.node_id for item in layout.exits),
        nodes=tuple(_project_node(item) for item in layout.nodes),
        edges=tuple(
            RoadEdge(
                edge_id=item.edge_id,
                from_node_id=item.from_node_id,
                to_node_id=item.to_node_id,
                distance_m=item.distance_m,
                base_travel_time_s=item.base_travel_time_s,
                directed=item.directed,
                channel_zone_ids=item.channel_zone_ids,
            )
            for item in layout.edges
        ),
        channel_zones=layout.channel_zones,
        spaces=tuple(
            ParkingSpace(
                parking_lot_id=item.parking_lot_id,
                space_id=item.space_id,
                coordinate=item.geometry.center,
                access_node_id=item.access_node_id,
                status=states[item.space_id].effective_status,
                charging=item.charging,
                stack_group_id=item.stack_group_id or f"single-{item.space_id}",
                depth=item.depth,
                assignable=states[item.space_id].assignable,
                assignability_reasons=states[item.space_id].reason_codes,
            )
            for item in layout.spaces
        ),
        tandem_groups=tuple(
            TandemGroup(stack_group_id=item.stack_group_id, space_ids_near_to_deep=item.space_ids_near_to_deep)
            for item in layout.tandem_groups
        ),
        buffers=tuple(
            BufferSpace(
                parking_lot_id=item.parking_lot_id,
                buffer_id=item.buffer_id,
                coordinate=item.geometry.center,
                access_node_id=item.access_node_id,
                available=True,
                channel_zone_ids=("channel-buffer",),
            )
            for item in layout.buffers
        ),
    )
    source = DataSourceStatus(
        parking_lot_id=spec.lot_id,
        mode=DataMode.SYNTHETIC,
        health=HealthStatus.HEALTHY,
        source_name=f"web-v2 public facility: {spec.scenario_id}",
        updated_at=PUBLISHED_AT,
    )
    lot = ParkingLot(
        parking_lot_id=spec.lot_id,
        name=spec.name,
        region_label=spec.region,
        venue_type=spec.venue_type,
        synthetic=True,
        opening_status="open",
        total_spaces=spec.spaces,
        available_spaces=sum(item.effective_status is SpaceStatus.AVAILABLE for item in state.spaces),
        charging_spaces=spec.charging,
        pricing=spec.pricing,
        updated_at=PUBLISHED_AT,
        data_source=source,
    )
    costs = CostSnapshot(
        parking_lot_id=spec.lot_id,
        layout_version=layout.layout_version,
        cost_version="cost-base-1",
        observed_at=PUBLISHED_AT,
        edge_travel_time_s={item.edge_id: item.base_travel_time_s for item in road_layout.edges},
    )
    return ScenarioBundle(
        scenario_id=spec.scenario_id,
        seed=spec.seed,
        parking_lot=lot,
        layout=road_layout,
        cost_snapshot=costs,
    )


def build_public_facility_scenarios() -> dict[str, PublishedFacilityScenario]:
    from parking_opt.api.facility_scenarios_build import _build_scenario

    return {item.lot_id: _build_scenario(item) for item in PUBLIC_SPECS}
