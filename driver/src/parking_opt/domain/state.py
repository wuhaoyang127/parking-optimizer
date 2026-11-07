"""Immutable authoritative state reduced only from confirmed parking events."""

from __future__ import annotations

from dataclasses import dataclass

from parking_opt.domain.enums import PositionKind
from parking_opt.domain.records import (
    Action,
    ChannelZoneResourceState,
    ExecutorResourceState,
    PendingRequest,
    PositionReservation,
    PositionState,
    RelocationTransaction,
    ResourceLock,
    VehicleState,
)


@dataclass(frozen=True, slots=True)
class PositionMetadata:
    """Immutable layout facts needed by the pure domain reducer."""

    position_id: str
    position_kind: PositionKind
    access_node_id: str
    stack_group_id: str | None
    depth: int | None
    channel_zone_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PathCostReference:
    """Third-party-free path facts copied from the materialized layout."""

    from_node_id: str
    to_node_id: str
    distance_m: float
    travel_time_s: int
    channel_zone_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AuthoritativeState:
    """The single replayable parking state at one confirmed event boundary."""

    schema_version: str
    run_id: str
    scenario_id: str
    layout_id: str
    sequence_no: int
    sim_time_s: int
    position_metadata: tuple[PositionMetadata, ...]
    exit_node_ids: tuple[str, ...]
    path_costs: tuple[PathCostReference, ...]
    active_buffer_position_ids: tuple[str, ...]
    arrival_wait_capacity: int
    max_arrival_wait_s: int
    vehicles: tuple[VehicleState, ...]
    positions: tuple[PositionState, ...]
    reservations: tuple[PositionReservation, ...]
    locks: tuple[ResourceLock, ...]
    actions: tuple[Action, ...]
    transactions: tuple[RelocationTransaction, ...]
    executor_resource: ExecutorResourceState
    channel_zone_resources: tuple[ChannelZoneResourceState, ...]
    pending_requests: tuple[PendingRequest, ...]

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise ValueError("AuthoritativeState requires schema_version 1.0.0")
        if self.sequence_no < 0 or self.sim_time_s < 0:
            raise ValueError("state sequence and simulation time must be non-negative")
        if self.arrival_wait_capacity < 0 or self.max_arrival_wait_s < 0:
            raise ValueError("arrival wait capacity and duration must be non-negative")
        if len(set(self.active_buffer_position_ids)) != len(self.active_buffer_position_ids):
            raise ValueError("active buffer IDs must be unique")


def empty_authoritative_state(
    *,
    run_id: str,
    scenario_id: str,
    layout_id: str,
    position_metadata: tuple[PositionMetadata, ...],
    exit_node_ids: tuple[str, ...],
    path_costs: tuple[PathCostReference, ...],
    positions: tuple[PositionState, ...],
    executor_capacity: int,
    channel_zone_capacities: tuple[tuple[str, int], ...],
    active_buffer_position_ids: tuple[str, ...],
    arrival_wait_capacity: int,
    max_arrival_wait_s: int,
) -> AuthoritativeState:
    """Create the immutable version-zero state for a validated layout/scenario pair."""

    return AuthoritativeState(
        schema_version="1.0.0",
        run_id=run_id,
        scenario_id=scenario_id,
        layout_id=layout_id,
        sequence_no=0,
        sim_time_s=0,
        position_metadata=tuple(sorted(position_metadata, key=lambda item: item.position_id)),
        exit_node_ids=tuple(sorted(exit_node_ids)),
        path_costs=tuple(sorted(path_costs, key=lambda item: (item.from_node_id, item.to_node_id))),
        active_buffer_position_ids=tuple(active_buffer_position_ids),
        arrival_wait_capacity=arrival_wait_capacity,
        max_arrival_wait_s=max_arrival_wait_s,
        vehicles=(),
        positions=tuple(sorted(positions, key=lambda item: item.position_id)),
        reservations=(),
        locks=(),
        actions=(),
        transactions=(),
        executor_resource=ExecutorResourceState(
            capacity=executor_capacity,
            used=0,
            active_action_ids=(),
        ),
        channel_zone_resources=tuple(
            ChannelZoneResourceState(
                channel_zone_id=zone_id,
                capacity=capacity,
                used=0,
                active_action_ids=(),
            )
            for zone_id, capacity in sorted(channel_zone_capacities)
        ),
        pending_requests=(),
    )
