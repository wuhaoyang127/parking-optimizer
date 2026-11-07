"""Deterministic synthetic scenario bundle construction."""

from __future__ import annotations

from parking_opt.api.models import (
    BufferSpace,
    ChannelZone,
    Coordinate,
    CostSnapshot,
    DataMode,
    DataSourceStatus,
    HealthStatus,
    Layout,
    ParkingLot,
    RoadEdge,
    RoadNode,
    ScenarioBundle,
    SpaceStatus,
    TandemGroup,
    VenueType,
)
from parking_opt.api.scenarios import SYNTHETIC_UPDATED_AT, _space


def _build_spaces(lot_id: str, occupied_ids: frozenset[str], charging_ids: frozenset[str]):
    def status(space_id: str) -> SpaceStatus:
        return SpaceStatus.OCCUPIED if space_id in occupied_ids else SpaceStatus.AVAILABLE

    return (
        _space(lot_id, "A-01", 37, -11, "access-a", status=status("A-01"), charging="A-01" in charging_ids),
        _space(lot_id, "A-02", 41, -11, "access-a", status=status("A-02"), charging="A-02" in charging_ids),
        _space(lot_id, "A-03", 45, -11, "access-a", status=status("A-03"), charging="A-03" in charging_ids),
        _space(lot_id, "B-01", 37, 11, "access-b", status=status("B-01"), stack_group_id="stack-B1", depth=1),
        _space(lot_id, "B-02", 37, 15, "access-b", status=status("B-02"), stack_group_id="stack-B1", depth=2),
        _space(lot_id, "B-03", 45, 11, "access-b", status=status("B-03"), stack_group_id="stack-B2", depth=1),
        _space(lot_id, "B-04", 45, 15, "access-b", status=status("B-04"), stack_group_id="stack-B2", depth=2),
        _space(lot_id, "C-01", 25, -11, "junction-a", status=status("C-01"), charging="C-01" in charging_ids),
    )


def _bundle(
    *,
    scenario_id: str,
    lot_id: str,
    name: str,
    region: str,
    venue_type: VenueType,
    occupied_ids: frozenset[str],
    charging_ids: frozenset[str],
    edge_times: tuple[float, float, float, float],
    pricing,
) -> ScenarioBundle:
    nodes = (
        RoadNode(node_id="entry", coordinate=Coordinate(x_m=0, y_m=0), kind="entrance", label="入口"),
        RoadNode(node_id="junction-a", coordinate=Coordinate(x_m=20, y_m=0), kind="junction", label="A区路口"),
        RoadNode(node_id="access-a", coordinate=Coordinate(x_m=36, y_m=-8), kind="space_access", label="A区车位"),
        RoadNode(node_id="access-b", coordinate=Coordinate(x_m=36, y_m=8), kind="space_access", label="B区纵深位"),
        RoadNode(node_id="buffer-access", coordinate=Coordinate(x_m=20, y_m=14), kind="buffer_access", label="临时移车区"),
        RoadNode(node_id="exit", coordinate=Coordinate(x_m=0, y_m=18), kind="exit", label="出口"),
    )
    edge_specs = (
        ("edge-entry-junction", "entry", "junction-a", 20.0, edge_times[0], ("channel-main",)),
        ("edge-junction-a", "junction-a", "access-a", 18.0, edge_times[1], ("channel-a",)),
        ("edge-junction-b", "junction-a", "access-b", 18.0, edge_times[2], ("channel-b",)),
        ("edge-junction-buffer", "junction-a", "buffer-access", 14.0, edge_times[3], ("channel-buffer",)),
        ("edge-buffer-exit", "buffer-access", "exit", 24.0, 24.0, ("channel-main",)),
    )
    edges = tuple(
        RoadEdge(
            edge_id=edge_id,
            from_node_id=from_node,
            to_node_id=to_node,
            distance_m=distance,
            base_travel_time_s=travel_time,
            channel_zone_ids=zones,
        )
        for edge_id, from_node, to_node, distance, travel_time, zones in edge_specs
    )
    spaces = _build_spaces(lot_id, occupied_ids, charging_ids)
    layout = Layout(
        parking_lot_id=lot_id,
        layout_version="layout-2026-08-12",
        coordinate_origin_note="deterministic synthetic coordinates; entrance origin; meters",
        entrance_node_ids=("entry",),
        exit_node_ids=("exit",),
        nodes=nodes,
        edges=edges,
        channel_zones=tuple(
            ChannelZone(channel_zone_id=zone, capacity=1)
            for zone in ("channel-main", "channel-a", "channel-b", "channel-buffer")
        ),
        spaces=spaces,
        tandem_groups=(
            TandemGroup(stack_group_id="stack-B1", space_ids_near_to_deep=("B-01", "B-02")),
            TandemGroup(stack_group_id="stack-B2", space_ids_near_to_deep=("B-03", "B-04")),
        ),
        buffers=(
            BufferSpace(
                parking_lot_id=lot_id,
                buffer_id="BUF-01",
                coordinate=Coordinate(x_m=23, y_m=16),
                access_node_id="buffer-access",
                available=True,
                channel_zone_ids=("channel-buffer",),
            ),
        ),
    )
    available = sum(item.status is SpaceStatus.AVAILABLE for item in spaces)
    source = DataSourceStatus(
        parking_lot_id=lot_id,
        mode=DataMode.SYNTHETIC,
        health=HealthStatus.HEALTHY,
        source_name=f"web-v2 deterministic fixture: {scenario_id}",
        updated_at=SYNTHETIC_UPDATED_AT,
    )
    lot = ParkingLot(
        parking_lot_id=lot_id,
        name=name,
        region_label=region,
        venue_type=venue_type,
        synthetic=True,
        opening_status="open",
        total_spaces=len(spaces),
        available_spaces=available,
        charging_spaces=sum(item.charging for item in spaces),
        pricing=pricing,
        updated_at=SYNTHETIC_UPDATED_AT,
        data_source=source,
    )
    costs = CostSnapshot(
        parking_lot_id=lot_id,
        layout_version=layout.layout_version,
        cost_version="cost-2026-08-12T090000Z",
        observed_at=SYNTHETIC_UPDATED_AT,
        edge_travel_time_s={item.edge_id: item.base_travel_time_s for item in edges},
    )
    return ScenarioBundle(
        scenario_id=scenario_id,
        seed=20260812,
        parking_lot=lot,
        layout=layout,
        cost_snapshot=costs,
    )
