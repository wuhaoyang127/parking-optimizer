from __future__ import annotations

from datetime import UTC, datetime

from parking_opt.api.models import (
    ChannelZone,
    Coordinate,
    FacilityBounds,
    FacilityBuffer,
    FacilityEdge,
    FacilityEntrance,
    FacilityExit,
    FacilityFloor,
    FacilityNode,
    FacilityProvenance,
    FacilityRectangle,
    FacilitySourceKind,
    FacilitySpace,
    FacilityTandemGroup,
    FacilityZone,
    ParkingFacilityLayout,
)

OBSERVED_AT = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)


def _coordinate(x_m: float, y_m: float) -> Coordinate:
    return Coordinate(x_m=x_m, y_m=y_m)


def _facility_layout() -> ParkingFacilityLayout:
    bounds = FacilityBounds(min_x_m=0, min_y_m=0, max_x_m=40, max_y_m=30)
    return ParkingFacilityLayout(
        parking_lot_id="lot-school",
        layout_version="facility-school-v1",
        provenance=FacilityProvenance(
            source_kind=FacilitySourceKind.SYNTHETIC,
            source_name="m4-contract-test",
            source_revision="fixture-v1",
            published_at=OBSERVED_AT,
        ),
        coordinate_origin_note="South-west corner, x east, y north.",
        bounds=bounds,
        default_floor_id="floor-1",
        floors=(
            FacilityFloor(floor_id="floor-1", label="一层", elevation_m=0, bounds=bounds),
        ),
        zones=(
            FacilityZone(
                zone_id="zone-parking",
                floor_id="floor-1",
                label="停车区",
                kind="parking",
                polygon=(
                    _coordinate(0, 0),
                    _coordinate(40, 0),
                    _coordinate(40, 25),
                    _coordinate(0, 25),
                ),
            ),
            FacilityZone(
                zone_id="zone-buffer",
                floor_id="floor-1",
                label="缓冲区",
                kind="buffer",
                polygon=(
                    _coordinate(25, 20),
                    _coordinate(35, 20),
                    _coordinate(35, 30),
                    _coordinate(25, 30),
                ),
            ),
        ),
        nodes=(
            FacilityNode(node_id="entry", floor_id="floor-1", coordinate=_coordinate(0, 10), kind="entrance", label="入口"),
            FacilityNode(node_id="junction", floor_id="floor-1", coordinate=_coordinate(10, 10), kind="junction", label="主通道"),
            FacilityNode(node_id="access-1", floor_id="floor-1", coordinate=_coordinate(20, 10), kind="space_access", label="纵深近位接入"),
            FacilityNode(node_id="access-2", floor_id="floor-1", coordinate=_coordinate(25, 10), kind="space_access", label="纵深深位接入"),
            FacilityNode(node_id="buffer-access", floor_id="floor-1", coordinate=_coordinate(30, 10), kind="buffer_access", label="缓冲位接入"),
            FacilityNode(node_id="exit", floor_id="floor-1", coordinate=_coordinate(40, 10), kind="exit", label="出口"),
        ),
        edges=(
            FacilityEdge(edge_id="edge-entry", from_node_id="entry", to_node_id="junction", centerline=(_coordinate(0, 10), _coordinate(10, 10)), width_m=6, distance_m=10, base_travel_time_s=5, directed=True, channel_zone_ids=("channel-main",)),
            FacilityEdge(edge_id="edge-access-1", from_node_id="junction", to_node_id="access-1", centerline=(_coordinate(10, 10), _coordinate(20, 10)), width_m=6, distance_m=10, base_travel_time_s=5, directed=True, channel_zone_ids=("channel-main",)),
            FacilityEdge(edge_id="edge-access-2", from_node_id="access-1", to_node_id="access-2", centerline=(_coordinate(20, 10), _coordinate(25, 10)), width_m=6, distance_m=5, base_travel_time_s=3, directed=True, channel_zone_ids=("channel-main",)),
            FacilityEdge(edge_id="edge-buffer", from_node_id="access-2", to_node_id="buffer-access", centerline=(_coordinate(25, 10), _coordinate(30, 10)), width_m=6, distance_m=5, base_travel_time_s=3, directed=True, channel_zone_ids=("channel-main",)),
            FacilityEdge(edge_id="edge-exit", from_node_id="buffer-access", to_node_id="exit", centerline=(_coordinate(30, 10), _coordinate(40, 10)), width_m=6, distance_m=10, base_travel_time_s=5, directed=True, channel_zone_ids=("channel-main",)),
        ),
        channel_zones=(ChannelZone(channel_zone_id="channel-main", capacity=2),),
        entrances=(
            FacilityEntrance(entrance_id="entrance-south", node_id="entry", label="南入口", initial_heading_deg=0),
        ),
        exits=(FacilityExit(exit_id="exit-east", node_id="exit", label="东出口"),),
        default_entrance_id="entrance-south",
        spaces=(
            FacilitySpace(
                parking_lot_id="lot-school",
                space_id="T-01",
                floor_id="floor-1",
                zone_id="zone-parking",
                geometry=FacilityRectangle(center=_coordinate(20, 16), width_m=2.5, length_m=5, heading_deg=90),
                access_node_id="access-1",
                stack_group_id="stack-1",
                depth=1,
            ),
            FacilitySpace(
                parking_lot_id="lot-school",
                space_id="T-02",
                floor_id="floor-1",
                zone_id="zone-parking",
                geometry=FacilityRectangle(center=_coordinate(20, 22), width_m=2.5, length_m=5, heading_deg=90),
                access_node_id="access-2",
                stack_group_id="stack-1",
                depth=2,
            ),
        ),
        tandem_groups=(
            FacilityTandemGroup(
                stack_group_id="stack-1",
                space_ids_near_to_deep=("T-01", "T-02"),
                buffer_ids=("buffer-1",),
            ),
        ),
        buffers=(
            FacilityBuffer(
                parking_lot_id="lot-school",
                buffer_id="buffer-1",
                floor_id="floor-1",
                zone_id="zone-buffer",
                geometry=FacilityRectangle(center=_coordinate(30, 25), width_m=2.5, length_m=5, heading_deg=90),
                access_node_id="buffer-access",
                stack_group_ids=("stack-1",),
            ),
        ),
    )
