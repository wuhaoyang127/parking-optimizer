"""Cross-record invariants for the immutable authoritative parking state."""

from __future__ import annotations

from collections import Counter

from parking_opt.domain.enums import (
    ActionStatus,
    ArrivalStatus,
    DepartureStatus,
    LocationKind,
    PositionKind,
    TransactionStatus,
)
from parking_opt.domain.state import AuthoritativeState


class InvariantViolation(ValueError):
    """Raised when an authoritative state violates a frozen B1-B3 constraint."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise InvariantViolation(message)


def assert_state_invariants(state: AuthoritativeState) -> None:
    """Validate vehicle, position, ownership, transaction, and resource conservation."""

    metadata = {item.position_id: item for item in state.position_metadata}
    positions = {item.position_id: item for item in state.positions}
    vehicles = {item.anonymous_vehicle_id: item for item in state.vehicles}
    reservations = {item.reservation_id: item for item in state.reservations}
    locks = {item.lock_id: item for item in state.locks}
    actions = {item.action_id: item for item in state.actions}
    transactions = {item.transaction_id: item for item in state.transactions}

    for name, values in (
        ("position metadata", metadata),
        ("positions", positions),
        ("vehicles", vehicles),
        ("reservations", reservations),
        ("locks", locks),
        ("actions", actions),
        ("transactions", transactions),
    ):
        source = {
            "position metadata": state.position_metadata,
            "positions": state.positions,
            "vehicles": state.vehicles,
            "reservations": state.reservations,
            "locks": state.locks,
            "actions": state.actions,
            "transactions": state.transactions,
        }[name]
        _require(len(values) == len(source), f"duplicate ID in {name}")

    _require(set(metadata) == set(positions), "position metadata and state domains differ")
    active_buffers = set(state.active_buffer_position_ids)
    _require(
        active_buffers
        <= {
            item.position_id
            for item in state.position_metadata
            if item.position_kind is PositionKind.BUFFER
        },
        "active buffer set contains a non-buffer position",
    )
    runtime_ids = set(reservations) | set(locks) | set(actions) | set(transactions)
    _require(
        len(runtime_ids) == len(reservations) + len(locks) + len(actions) + len(transactions),
        "reservation, lock, action, and transaction IDs must not collide",
    )

    occupant_by_position: dict[str, str] = {}
    for vehicle_id, vehicle in vehicles.items():
        location = vehicle.location_state
        _require(
            (location.kind is LocationKind.REJECTED)
            == (vehicle.arrival_status is ArrivalStatus.REJECTED),
            f"rejected state mismatch for {vehicle_id}",
        )
        if vehicle.ever_admitted:
            _require(
                vehicle.arrival_status is not ArrivalStatus.REJECTED
                and location.kind is not LocationKind.REJECTED,
                f"ever-admitted vehicle {vehicle_id} was rejected",
            )
        if vehicle.arrival_status in {
            ArrivalStatus.ADMITTED,
            ArrivalStatus.ENTRY_COMPLETED,
        }:
            _require(vehicle.ever_admitted, f"admission history missing for {vehicle_id}")
        if vehicle.arrival_status is ArrivalStatus.CANCELLED:
            _require(
                location.kind is LocationKind.EXITED,
                f"cancelled arrival {vehicle_id} is not EXITED",
            )
        if vehicle.departure_status is DepartureStatus.COMPLETED:
            _require(
                location.kind is LocationKind.EXITED,
                f"completed departure {vehicle_id} is not EXITED",
            )
        if location.kind is LocationKind.AT_POSITION:
            position_id = location.position_id
            assert position_id is not None
            _require(position_id in positions, f"vehicle {vehicle_id} uses unknown position")
            _require(
                position_id not in occupant_by_position,
                f"position {position_id} has multiple physical occupants",
            )
            occupant_by_position[position_id] = vehicle_id
        elif location.kind is LocationKind.IN_TRANSIT:
            action_id = location.action_id
            assert action_id is not None
            _require(action_id in actions, f"in-transit action {action_id} does not exist")
            _require(
                actions[action_id].status is ActionStatus.STARTED,
                f"in-transit action {action_id} is not STARTED",
            )
            _require(
                vehicle.action_context_id == action_id,
                f"in-transit vehicle {vehicle_id} has wrong action context",
            )
        elif location.kind is LocationKind.POSITION_UNCERTAIN:
            _require(
                vehicle.action_context_id == location.action_id,
                f"uncertain vehicle {vehicle_id} has wrong action context",
            )

    for position_id, position in positions.items():
        _require(
            position.occupant_vehicle_id == occupant_by_position.get(position_id),
            f"position/vehicle occupancy disagrees at {position_id}",
        )
        if position.position_kind is PositionKind.BUFFER:
            _require(not position.assignable, f"buffer {position_id} is assignable")

    claims: dict[str, set[str]] = {
        position_id: ({owner} if (owner := position.occupant_vehicle_id) else set())
        for position_id, position in positions.items()
    }
    for reservation in reservations.values():
        _require(
            reservation.position_id in positions,
            f"reservation {reservation.reservation_id} uses unknown position",
        )
        _require(
            reservation.owner_vehicle_id in vehicles,
            f"reservation {reservation.reservation_id} owner does not exist",
        )
        claims[reservation.position_id].add(reservation.owner_vehicle_id)
        if reservation.transaction_id is not None:
            _require(
                reservation.transaction_id in transactions,
                f"reservation {reservation.reservation_id} transaction does not exist",
            )
    for position_id, owners in claims.items():
        _require(len(owners) <= 1, f"conflicting capacity owners at {position_id}")

    groups = {
        item.stack_group_id for item in state.position_metadata if item.stack_group_id is not None
    }
    zones = {item.channel_zone_id for item in state.channel_zone_resources}
    for lock in locks.values():
        _require(
            lock.transaction_id in transactions,
            f"lock {lock.lock_id} transaction does not exist",
        )
        valid_resource = {
            "vehicle": lock.resource_id in vehicles,
            "position": lock.resource_id in positions,
            "stack_group": lock.resource_id in groups,
            "channel_zone": lock.resource_id in zones,
        }[lock.resource_type]
        _require(valid_resource, f"lock {lock.lock_id} protects an unknown resource")

    for transaction in transactions.values():
        _require(
            transaction.target_vehicle_id in vehicles,
            f"transaction {transaction.transaction_id} target does not exist",
        )
        _require(
            tuple(item.blocker_vehicle_id for item in transaction.buffer_assignments)
            == transaction.blocker_vehicle_ids,
            f"transaction {transaction.transaction_id} blocker order differs from mappings",
        )
        _require(
            len({item.buffer_position_id for item in transaction.buffer_assignments})
            == len(transaction.buffer_assignments),
            f"transaction {transaction.transaction_id} buffer mapping is not injective",
        )
        for blocker_id in transaction.blocker_vehicle_ids:
            _require(blocker_id in vehicles, f"transaction blocker {blocker_id} does not exist")

    executor_active = state.executor_resource.active_action_ids
    expected_executor_used = sum(actions[action_id].executor_units for action_id in executor_active)
    _require(
        state.executor_resource.used == expected_executor_used,
        "executor used count disagrees with active actions",
    )
    _require(
        state.executor_resource.used <= state.executor_resource.capacity,
        "executor capacity exceeded",
    )
    zone_by_id = {item.channel_zone_id: item for item in state.channel_zone_resources}
    active_zone_memberships: Counter[str] = Counter()
    for zone_id, resource in zone_by_id.items():
        _require(resource.used == len(resource.active_action_ids), f"zone {zone_id} use mismatch")
        _require(resource.used <= resource.capacity, f"zone {zone_id} capacity exceeded")
        active_zone_memberships.update(resource.active_action_ids)

    started_ids = {
        item.action_id for item in actions.values() if item.status is ActionStatus.STARTED
    }
    for action_id, action in actions.items():
        if action.status is ActionStatus.STARTED:
            if action.executor_units:
                _require(action_id in executor_active, f"started action {action_id} lacks executor")
            for zone_id in action.channel_zone_ids:
                _require(zone_id in zone_by_id, f"action {action_id} uses unknown channel zone")
                _require(
                    action_id in zone_by_id[zone_id].active_action_ids,
                    f"started action {action_id} lacks zone {zone_id}",
                )
        else:
            _require(
                action_id not in executor_active and active_zone_memberships[action_id] == 0,
                f"non-started action {action_id} holds runtime resources",
            )
    _require(
        set(executor_active) <= started_ids,
        "executor resource references a non-started action",
    )

    for position_id, vehicle_id in occupant_by_position.items():
        if metadata[position_id].position_kind is not PositionKind.BUFFER:
            continue
        vehicle = vehicles[vehicle_id]
        transaction_id = vehicle.active_transaction_id
        _require(transaction_id in transactions, f"buffer vehicle {vehicle_id} lacks transaction")
        assert transaction_id is not None
        transaction = transactions[transaction_id]
        matching = {
            item.blocker_vehicle_id: item.buffer_position_id
            for item in transaction.buffer_assignments
        }
        _require(
            matching.get(vehicle_id) == position_id,
            f"buffer vehicle {vehicle_id} is not matched by its transaction",
        )

    for transaction in transactions.values():
        if transaction.status in {
            TransactionStatus.COMPLETED,
            TransactionStatus.CANCELLED,
            TransactionStatus.FAILED_RESOLVED,
        }:
            _require(
                not any(
                    item.transaction_id == transaction.transaction_id for item in state.reservations
                ),
                f"terminal transaction {transaction.transaction_id} retains reservations",
            )
            _require(
                not any(item.transaction_id == transaction.transaction_id for item in state.locks),
                f"terminal transaction {transaction.transaction_id} retains locks",
            )

    pending_keys = [(item.event_sequence_no, item.request_id) for item in state.pending_requests]
    _require(pending_keys == sorted(pending_keys), "pending requests are not canonically ordered")
