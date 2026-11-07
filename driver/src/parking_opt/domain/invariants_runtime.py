"""Runtime-resource and transaction invariants for the authoritative state."""

from __future__ import annotations

from collections import Counter

from parking_opt.domain.enums import ActionStatus, PositionKind, TransactionStatus
from parking_opt.domain.invariants import _require


def assert_runtime_invariants(state, ctx) -> None:
    metadata = ctx["metadata"]
    positions = ctx["positions"]
    vehicles = ctx["vehicles"]
    locks = ctx["locks"]
    actions = ctx["actions"]
    transactions = ctx["transactions"]
    occupant_by_position = ctx["occupant_by_position"]

    groups = {item.stack_group_id for item in state.position_metadata if item.stack_group_id is not None}
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
