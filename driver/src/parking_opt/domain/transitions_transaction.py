"""Relocation-transaction creation reduction."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from itertools import pairwise
from typing import Any

from parking_opt.domain.conversion import (
    action_from_mapping,
    lock_from_mapping,
    reservation_from_mapping,
    transaction_from_mapping,
)
from parking_opt.domain.enums import (
    ActionStatus,
    ActionType,
    DepartureStatus,
    LocationKind,
    PositionKind,
    TransactionStatus,
)
from parking_opt.domain.records import Action, RelocationTransaction
from parking_opt.domain.state import AuthoritativeState
from parking_opt.domain.transitions import _WorkingState, _require
from parking_opt.domain.transitions_helpers import (
    _active_claim_owners,
    _assert_action_path,
    _metadata_by_position,
    _path_for_nodes,
    _shallower_occupants,
)


def _expected_transaction_actions(
    transaction: RelocationTransaction,
    actions: Sequence[Action],
) -> tuple[str, ...]:
    by_role: dict[tuple[ActionType, str], Action] = {}
    for action in actions:
        key = (action.action_type, action.anonymous_vehicle_id)
        _require(key not in by_role, f"duplicate transaction action role {key}")
        by_role[key] = action
    order: list[str] = []
    for blocker_id in transaction.blocker_vehicle_ids:
        order.append(by_role[(ActionType.RELOCATE_TO_BUFFER, blocker_id)].action_id)
    order.append(by_role[(ActionType.DIRECT_EXIT, transaction.target_vehicle_id)].action_id)
    for blocker_id in reversed(transaction.blocker_vehicle_ids):
        order.append(by_role[(ActionType.RESTORE_ORIGINAL, blocker_id)].action_id)
    _require(len(order) == len(actions), "transaction contains unexpected action roles")
    return tuple(order)


def _apply_transaction_created(
    state: AuthoritativeState,
    work: _WorkingState,
    event: Mapping[str, Any],
) -> None:
    transaction = transaction_from_mapping(event["transaction"])
    transaction_id = transaction.transaction_id
    _require(transaction.status is TransactionStatus.RESERVED, "transaction is not RESERVED")
    _require(transaction_id == event["transaction_id"], "transaction envelope mismatch")
    _require(transaction_id not in work.transactions, "transaction already exists")
    target = work.vehicles[transaction.target_vehicle_id]
    _require(target.departure_status is DepartureStatus.PENDING, "target has no departure")
    _require(target.location_state.kind is LocationKind.AT_POSITION, "transaction target is not parked")
    target_position = target.location_state.position_id
    assert target_position is not None
    blockers = _shallower_occupants(state, work, target_position)
    expected_blockers = tuple(vehicle_id for _, vehicle_id in blockers)
    _require(transaction.blocker_vehicle_ids == expected_blockers, "transaction blocker list is not the actual shallow-to-deep order")
    metadata = _metadata_by_position(state)
    for assignment, (origin_id, blocker_id) in zip(transaction.buffer_assignments, blockers, strict=True):
        _require(assignment.blocker_vehicle_id == blocker_id, "buffer mapping vehicle mismatch")
        _require(assignment.original_position_id == origin_id, "original position mismatch")
        _require(assignment.buffer_position_id in state.active_buffer_position_ids, "buffer is not active for this scenario")
        _require(metadata[assignment.buffer_position_id].position_kind is PositionKind.BUFFER, "buffer mapping points to a normal position")
        _require(not _active_claim_owners(work, assignment.buffer_position_id), "buffer already has a capacity owner")
        _require(
            _path_for_nodes(state, metadata[origin_id].access_node_id, metadata[assignment.buffer_position_id].access_node_id) is not None
            and _path_for_nodes(state, metadata[assignment.buffer_position_id].access_node_id, metadata[origin_id].access_node_id) is not None,
            "buffer round trip is unreachable",
        )
    for vehicle_id in (transaction.target_vehicle_id, *transaction.blocker_vehicle_ids):
        _require(work.vehicles[vehicle_id].active_transaction_id is None, f"vehicle {vehicle_id} already belongs to another transaction")

    actions = tuple(action_from_mapping(item) for item in event["payload"]["transaction_actions"])
    _require(
        all(item.status is ActionStatus.ACCEPTED and item.transaction_id == transaction_id for item in actions),
        "transaction actions must be ACCEPTED and owned by the transaction",
    )
    canonical_order = _expected_transaction_actions(transaction, actions)
    _require(transaction.action_ids == canonical_order, "transaction action_ids are not in canonical physical order")
    expected_edges = tuple(pairwise(canonical_order))
    actual_edges = tuple((item.before_action_id, item.after_action_id) for item in transaction.precedence_edges)
    _require(actual_edges == expected_edges, "transaction precedence is not the canonical chain")

    assignment_by_vehicle = {item.blocker_vehicle_id: item for item in transaction.buffer_assignments}
    for action in actions:
        _assert_action_path(state, work, action)
        if action.action_type is ActionType.RELOCATE_TO_BUFFER:
            assignment = assignment_by_vehicle[action.anonymous_vehicle_id]
            _require(
                action.origin_position_id == assignment.original_position_id and action.destination_position_id == assignment.buffer_position_id,
                "relocate action disagrees with buffer mapping",
            )
        elif action.action_type is ActionType.RESTORE_ORIGINAL:
            assignment = assignment_by_vehicle[action.anonymous_vehicle_id]
            _require(
                action.origin_position_id == assignment.buffer_position_id and action.destination_position_id == assignment.original_position_id,
                "restore action disagrees with original-position mapping",
            )

    reservations = tuple(reservation_from_mapping(item) for item in event["payload"]["created_reservations"])
    expected_reservations = {
        (item.blocker_vehicle_id, item.buffer_position_id, "buffer_destination") for item in transaction.buffer_assignments
    } | {
        (item.blocker_vehicle_id, item.original_position_id, "restore_original") for item in transaction.buffer_assignments
    }
    actual_reservations = {(item.owner_vehicle_id, item.position_id, item.purpose) for item in reservations}
    _require(
        actual_reservations == expected_reservations and all(item.transaction_id == transaction_id for item in reservations),
        "transaction reservations are not the exact buffer/original protection set",
    )

    locks = tuple(lock_from_mapping(item) for item in event["payload"]["created_locks"])
    target_group = metadata[target_position].stack_group_id
    assert target_group is not None
    expected_locks = {
        ("vehicle", transaction.target_vehicle_id),
        *(("vehicle", item) for item in transaction.blocker_vehicle_ids),
        ("stack_group", target_group),
    }
    actual_locks = {(item.resource_type, item.resource_id) for item in locks}
    _require(
        actual_locks == expected_locks and all(item.transaction_id == transaction_id for item in locks),
        "transaction locks are not the exact target/blockers/group set",
    )
    existing_lock_resources = {(item.resource_type, item.resource_id) for item in work.locks.values()}
    _require(not (actual_locks & existing_lock_resources), "transaction lock conflicts with an existing transaction")
    all_new_ids = {
        transaction_id,
        *(item.action_id for item in actions),
        *(item.reservation_id for item in reservations),
        *(item.lock_id for item in locks),
    }
    existing_ids = set(work.transactions) | set(work.actions) | set(work.reservations) | set(work.locks)
    _require(not (all_new_ids & existing_ids), "transaction runtime ID already exists")
    _require(len(all_new_ids) == 1 + len(actions) + len(reservations) + len(locks), "transaction runtime IDs collide")

    work.transactions[transaction_id] = transaction
    work.actions.update({item.action_id: item for item in actions})
    work.reservations.update({item.reservation_id: item for item in reservations})
    work.locks.update({item.lock_id: item for item in locks})
    for vehicle_id in (transaction.target_vehicle_id, *transaction.blocker_vehicle_ids):
        work.vehicles[vehicle_id] = replace(work.vehicles[vehicle_id], active_transaction_id=transaction_id)
