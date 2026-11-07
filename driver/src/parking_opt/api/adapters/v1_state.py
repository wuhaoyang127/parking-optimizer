"""Build the immutable v1 authoritative state from v2 visible values."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from parking_opt.api.models import DriverRequest, SpaceStatus
from parking_opt.domain.enums import (
    ArrivalStatus,
    DepartureInformationSource,
    DepartureStatus,
    LocationKind,
    ManualStatus,
    PositionKind,
    ReservationStatus,
)
from parking_opt.domain.records import (
    DepartureInformation,
    LocationState,
    PendingRequest,
    PositionState,
    VehicleState,
)
from parking_opt.domain.state import (
    PathCostReference,
    PositionMetadata,
    empty_authoritative_state,
)


def build_v1_state(driver: DriverRequest, layout, v1_layout: dict[str, Any], sim_time_s: int):
    positions = tuple(
        PositionState(
            position_id=item.space_id,
            position_kind=PositionKind.NORMAL,
            physically_available=item.status is SpaceStatus.AVAILABLE,
            assignable=item.assignable,
            planned_closure=False,
            occupant_vehicle_id=(
                f"occupant-{item.space_id}" if item.status is SpaceStatus.OCCUPIED else None
            ),
        )
        for item in layout.spaces
    ) + tuple(
        PositionState(
            position_id=item.buffer_id,
            position_kind=PositionKind.BUFFER,
            physically_available=item.available,
            assignable=False,
            planned_closure=False,
            occupant_vehicle_id=None,
        )
        for item in layout.buffers
    )
    unknown_departure = DepartureInformation(
        expected_departure_time_s=None,
        source=DepartureInformationSource.UNKNOWN,
        known_at_time_s=sim_time_s,
    )
    occupants = tuple(
        VehicleState(
            anonymous_vehicle_id=f"occupant-{item.space_id}",
            location_state=LocationState(LocationKind.AT_POSITION, item.space_id),
            arrival_status=ArrivalStatus.ENTRY_COMPLETED,
            departure_status=DepartureStatus.NONE,
            manual_status=ManualStatus.NONE,
            ever_admitted=True,
            admitted_at_s=sim_time_s,
            waiting_since_s=None,
            action_context_id=None,
            active_transaction_id=None,
            reservation_status=ReservationStatus.NONE,
            departure_information=unknown_departure,
        )
        for item in layout.spaces
        if item.status is SpaceStatus.OCCUPIED
    )
    expected_departure = (
        DepartureInformation(
            expected_departure_time_s=int(driver.expected_departure_at.timestamp()),
            source=DepartureInformationSource.USER_ESTIMATE,
            known_at_time_s=sim_time_s,
            source_record_id=driver.request_id,
        )
        if driver.expected_departure_at is not None
        else unknown_departure
    )
    driver_vehicle = VehicleState(
        anonymous_vehicle_id=f"driver-{driver.session_id}",
        location_state=LocationState(LocationKind.ENTRY_QUEUE),
        arrival_status=ArrivalStatus.PENDING,
        departure_status=DepartureStatus.NONE,
        manual_status=ManualStatus.NONE,
        ever_admitted=False,
        admitted_at_s=None,
        waiting_since_s=sim_time_s,
        action_context_id=None,
        active_transaction_id=None,
        reservation_status=ReservationStatus.NONE,
        departure_information=expected_departure,
    )
    path_refs = tuple(
        PathCostReference(
            from_node_id=item["from_node_id"],
            to_node_id=item["to_node_id"],
            distance_m=float(item["distance_m"]),
            travel_time_s=int(item["travel_time_s"]),
            channel_zone_ids=tuple(item["channel_zone_ids"]),
        )
        for item in v1_layout["path_costs"]
    )
    metadata = tuple(
        PositionMetadata(
            position_id=item.space_id,
            position_kind=PositionKind.NORMAL,
            access_node_id=item.access_node_id,
            stack_group_id=item.stack_group_id,
            depth=item.depth,
            channel_zone_ids=(),
        )
        for item in layout.spaces
    ) + tuple(
        PositionMetadata(
            position_id=item.buffer_id,
            position_kind=PositionKind.BUFFER,
            access_node_id=item.access_node_id,
            stack_group_id=None,
            depth=None,
            channel_zone_ids=item.channel_zone_ids,
        )
        for item in layout.buffers
    )
    state = empty_authoritative_state(
        run_id=f"web-v2-{driver.session_id}",
        scenario_id=layout.parking_lot_id,
        layout_id=str(v1_layout["layout_id"]),
        position_metadata=metadata,
        exit_node_ids=layout.exit_node_ids,
        path_costs=path_refs,
        positions=positions,
        executor_capacity=1,
        channel_zone_capacities=tuple(
            (item.channel_zone_id, item.capacity) for item in layout.channel_zones
        ),
        active_buffer_position_ids=tuple(
            item.buffer_id for item in layout.buffers if item.available
        ),
        arrival_wait_capacity=8,
        max_arrival_wait_s=30,
    )
    return replace(
        state,
        sim_time_s=sim_time_s,
        vehicles=(*occupants, driver_vehicle),
        pending_requests=(
            PendingRequest(
                request_id=driver.request_id,
                anonymous_vehicle_id=driver_vehicle.anonymous_vehicle_id,
                request_type="ARRIVAL",
                requested_at_s=sim_time_s,
                event_sequence_no=1,
                entrance_node_id=driver.entrance_node_id,
            ),
        ),
    )
