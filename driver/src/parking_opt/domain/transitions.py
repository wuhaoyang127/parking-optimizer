"""Pure, atomic event reduction for the approved stage B state machines."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import pairwise
from typing import Any

from parking_opt.domain.conversion import (
    action_from_mapping,
    departure_information_from_mapping,
    initial_vehicle_state,
    location_from_mapping,
    lock_from_mapping,
    pending_request_from_mapping,
    reservation_from_mapping,
    transaction_from_mapping,
)
from parking_opt.domain.enums import (
    ActionStatus,
    ActionType,
    ArrivalStatus,
    DepartureStatus,
    LocationKind,
    ManualStatus,
    PositionConfirmation,
    PositionKind,
    ReservationStatus,
    TransactionStatus,
)
from parking_opt.domain.invariants import assert_state_invariants
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
from parking_opt.domain.state import AuthoritativeState, PositionMetadata


class StateTransitionError(ValueError):
    """Raised when a confirmed event is not legal from the current state."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise StateTransitionError(message)


@dataclass(slots=True)
class _WorkingState:
    """Private mutable copy committed only after all checks and invariants pass."""

    source: AuthoritativeState
    vehicles: dict[str, VehicleState]
    positions: dict[str, PositionState]
    reservations: dict[str, PositionReservation]
    locks: dict[str, ResourceLock]
    actions: dict[str, Action]
    transactions: dict[str, RelocationTransaction]
    executor_resource: ExecutorResourceState
    channel_resources: dict[str, ChannelZoneResourceState]
    pending_requests: dict[str, PendingRequest]

    @classmethod
    def from_state(cls, state: AuthoritativeState) -> _WorkingState:
        return cls(
            source=state,
            vehicles={item.anonymous_vehicle_id: item for item in state.vehicles},
            positions={item.position_id: item for item in state.positions},
            reservations={item.reservation_id: item for item in state.reservations},
            locks={item.lock_id: item for item in state.locks},
            actions={item.action_id: item for item in state.actions},
            transactions={item.transaction_id: item for item in state.transactions},
            executor_resource=state.executor_resource,
            channel_resources={item.channel_zone_id: item for item in state.channel_zone_resources},
            pending_requests={item.request_id: item for item in state.pending_requests},
        )

    def freeze(self, *, sequence_no: int, sim_time_s: int) -> AuthoritativeState:
        state = replace(
            self.source,
            sequence_no=sequence_no,
            sim_time_s=sim_time_s,
            vehicles=tuple(
                sorted(
                    self.vehicles.values(),
                    key=lambda item: item.anonymous_vehicle_id,
                )
            ),
            positions=tuple(sorted(self.positions.values(), key=lambda item: item.position_id)),
            reservations=tuple(
                sorted(self.reservations.values(), key=lambda item: item.reservation_id)
            ),
            locks=tuple(sorted(self.locks.values(), key=lambda item: item.lock_id)),
            actions=tuple(sorted(self.actions.values(), key=lambda item: item.action_id)),
            transactions=tuple(
                sorted(self.transactions.values(), key=lambda item: item.transaction_id)
            ),
            executor_resource=self.executor_resource,
            channel_zone_resources=tuple(
                sorted(
                    self.channel_resources.values(),
                    key=lambda item: item.channel_zone_id,
                )
            ),
            pending_requests=tuple(
                sorted(
                    self.pending_requests.values(),
                    key=lambda item: (item.event_sequence_no, item.request_id),
                )
            ),
        )
        assert_state_invariants(state)
        return state


def _metadata_by_position(state: AuthoritativeState) -> dict[str, PositionMetadata]:
    return {item.position_id: item for item in state.position_metadata}


def _active_claim_owners(work: _WorkingState, position_id: str) -> set[str]:
    position = work.positions[position_id]
    owners = {position.occupant_vehicle_id} if position.occupant_vehicle_id else set()
    owners.update(
        item.owner_vehicle_id
        for item in work.reservations.values()
        if item.position_id == position_id
    )
    return owners


def _path_for_nodes(
    state: AuthoritativeState,
    from_node_id: str,
    to_node_id: str,
) -> tuple[float, tuple[str, ...]] | None:
    for path in state.path_costs:
        if path.from_node_id == from_node_id and path.to_node_id == to_node_id:
            return path.distance_m, path.channel_zone_ids
    return None


def _path_for_action(
    state: AuthoritativeState,
    work: _WorkingState,
    action: Action,
) -> tuple[float, tuple[str, ...]] | None:
    metadata = _metadata_by_position(state)
    if action.action_type is ActionType.ASSIGN:
        destination = action.destination_position_id
        if destination is None:
            return None
        request = next(
            (
                item
                for item in work.pending_requests.values()
                if item.anonymous_vehicle_id == action.anonymous_vehicle_id
                and item.request_type == "ARRIVAL"
            ),
            None,
        )
        if request is None or request.entrance_node_id is None:
            return None
        return _path_for_nodes(
            state,
            request.entrance_node_id,
            metadata[destination].access_node_id,
        )
    origin = action.origin_position_id
    if origin is None:
        return None
    from_node = metadata[origin].access_node_id
    if action.action_type is ActionType.DIRECT_EXIT:
        if action.destination_exit_id is None:
            return None
        return _path_for_nodes(state, from_node, action.destination_exit_id)
    destination = action.destination_position_id
    if destination is None:
        return None
    return _path_for_nodes(state, from_node, metadata[destination].access_node_id)


def _assert_action_path(state: AuthoritativeState, work: _WorkingState, action: Action) -> None:
    path = _path_for_action(state, work, action)
    _require(path is not None, f"action {action.action_id} path is unreachable")
    assert path is not None
    distance_m, zone_ids = path
    _require(
        abs(action.distance_m - distance_m) <= 1e-9,
        f"action {action.action_id} distance differs from materialized path",
    )
    _require(
        action.channel_zone_ids == zone_ids,
        f"action {action.action_id} channel zones differ from materialized path",
    )


def _shallower_occupants(
    state: AuthoritativeState,
    work: _WorkingState,
    target_position_id: str,
) -> tuple[tuple[str, str], ...]:
    metadata = _metadata_by_position(state)
    target = metadata[target_position_id]
    _require(
        target.position_kind is PositionKind.NORMAL
        and target.stack_group_id is not None
        and target.depth is not None,
        "target must be a normal tandem position",
    )
    assert target.depth is not None
    result: list[tuple[int, str, str]] = []
    for position_id, position in work.positions.items():
        item = metadata[position_id]
        if (
            item.position_kind is PositionKind.NORMAL
            and item.stack_group_id == target.stack_group_id
            and item.depth is not None
            and item.depth < target.depth
            and position.occupant_vehicle_id is not None
        ):
            result.append((item.depth, position_id, position.occupant_vehicle_id))
    return tuple(
        (position_id, vehicle_id)
        for _, position_id, vehicle_id in sorted(result, key=lambda item: item[0])
    )


def _assert_entry_clear(
    state: AuthoritativeState,
    work: _WorkingState,
    destination_id: str,
) -> None:
    metadata = _metadata_by_position(state)
    target = metadata[destination_id]
    _require(target.position_kind is PositionKind.NORMAL, "arrival destination is not normal")
    for item in state.position_metadata:
        if (
            item.position_kind is PositionKind.NORMAL
            and item.stack_group_id == target.stack_group_id
            and item.depth is not None
            and target.depth is not None
            and item.depth < target.depth
        ):
            _require(
                not _active_claim_owners(work, item.position_id),
                f"entry to {destination_id} is blocked by {item.position_id}",
            )
            _require(
                not any(
                    lock.resource_type == "position" and lock.resource_id == item.position_id
                    for lock in work.locks.values()
                ),
                f"entry to {destination_id} crosses a position lock",
            )


def _same_action_definition(left: Action, right: Action) -> bool:
    fields = (
        "action_id",
        "transaction_id",
        "anonymous_vehicle_id",
        "action_type",
        "origin_position_id",
        "destination_position_id",
        "destination_exit_id",
        "distance_m",
        "modeled_duration_s",
        "executor_type",
        "executor_units",
        "channel_zone_ids",
        "reason",
        "distance_value_source",
        "duration_value_source",
        "recommended_at_s",
    )
    return all(getattr(left, field) == getattr(right, field) for field in fields)


def _replace_action(
    work: _WorkingState,
    incoming: Action,
    allowed_previous: set[ActionStatus],
) -> None:
    current = work.actions.get(incoming.action_id)
    _require(current is not None, f"action {incoming.action_id} does not exist")
    assert current is not None
    _require(
        current.status in allowed_previous,
        f"action {incoming.action_id} cannot move from {current.status} to {incoming.status}",
    )
    _require(
        _same_action_definition(current, incoming),
        f"action {incoming.action_id} immutable fields changed",
    )
    work.actions[incoming.action_id] = incoming


def _resources_available(work: _WorkingState, action: Action) -> bool:
    if work.executor_resource.used + action.executor_units > work.executor_resource.capacity:
        return False
    return all(
        zone_id in work.channel_resources
        and work.channel_resources[zone_id].used + 1 <= work.channel_resources[zone_id].capacity
        for zone_id in action.channel_zone_ids
    )


def _assert_lock_access(
    state: AuthoritativeState,
    work: _WorkingState,
    action: Action,
) -> None:
    metadata = _metadata_by_position(state)
    resources = {("vehicle", action.anonymous_vehicle_id)}
    for position_id in (action.origin_position_id, action.destination_position_id):
        if position_id is None:
            continue
        resources.add(("position", position_id))
        group_id = metadata[position_id].stack_group_id
        if group_id is not None:
            resources.add(("stack_group", group_id))
    resources.update(("channel_zone", zone_id) for zone_id in action.channel_zone_ids)
    for lock in work.locks.values():
        if (lock.resource_type, lock.resource_id) in resources:
            _require(
                lock.transaction_id == action.transaction_id,
                f"action {action.action_id} conflicts with lock {lock.lock_id}",
            )


def _acquire_resources(work: _WorkingState, action: Action) -> None:
    _require(_resources_available(work, action), f"resources unavailable for {action.action_id}")
    if action.executor_units:
        work.executor_resource = replace(
            work.executor_resource,
            used=work.executor_resource.used + action.executor_units,
            active_action_ids=tuple(
                sorted((*work.executor_resource.active_action_ids, action.action_id))
            ),
        )
    for zone_id in action.channel_zone_ids:
        resource = work.channel_resources[zone_id]
        work.channel_resources[zone_id] = replace(
            resource,
            used=resource.used + 1,
            active_action_ids=tuple(sorted((*resource.active_action_ids, action.action_id))),
        )


def _release_resources(work: _WorkingState, action: Action) -> None:
    if action.action_id in work.executor_resource.active_action_ids:
        work.executor_resource = replace(
            work.executor_resource,
            used=work.executor_resource.used - action.executor_units,
            active_action_ids=tuple(
                item
                for item in work.executor_resource.active_action_ids
                if item != action.action_id
            ),
        )
    for zone_id, resource in tuple(work.channel_resources.items()):
        if action.action_id in resource.active_action_ids:
            work.channel_resources[zone_id] = replace(
                resource,
                used=resource.used - 1,
                active_action_ids=tuple(
                    item for item in resource.active_action_ids if item != action.action_id
                ),
            )


def _release_transaction_protection(work: _WorkingState, transaction_id: str) -> None:
    work.reservations = {
        key: item
        for key, item in work.reservations.items()
        if item.transaction_id != transaction_id
    }
    work.locks = {
        key: item for key, item in work.locks.items() if item.transaction_id != transaction_id
    }
    for vehicle_id, vehicle in tuple(work.vehicles.items()):
        if vehicle.active_transaction_id == transaction_id:
            work.vehicles[vehicle_id] = replace(vehicle, active_transaction_id=None)


def _remove_pending_for_vehicle(
    work: _WorkingState,
    vehicle_id: str,
    request_type: str,
) -> None:
    work.pending_requests = {
        key: item
        for key, item in work.pending_requests.items()
        if not (item.anonymous_vehicle_id == vehicle_id and item.request_type == request_type)
    }


def _apply_arrival(work: _WorkingState, event: Mapping[str, Any]) -> None:
    vehicle_id = event["anonymous_vehicle_id"]
    _require(vehicle_id not in work.vehicles, f"vehicle {vehicle_id} already exists")
    request = pending_request_from_mapping(event["payload"]["pending_request"])
    _require(request.anonymous_vehicle_id == vehicle_id, "arrival request vehicle mismatch")
    _require(request.requested_at_s == event["sim_time_s"], "arrival request time mismatch")
    _require(
        request.event_sequence_no == event["sequence_no"],
        "arrival request sequence mismatch",
    )
    work.vehicles[vehicle_id] = initial_vehicle_state(vehicle_id)
    work.pending_requests[request.request_id] = request


def _apply_wait(work: _WorkingState, event: Mapping[str, Any]) -> None:
    vehicle_id = event["anonymous_vehicle_id"]
    vehicle = work.vehicles[vehicle_id]
    _require(
        vehicle.location_state.kind is LocationKind.ENTRY_QUEUE
        and vehicle.arrival_status in {ArrivalStatus.PENDING, ArrivalStatus.RECOMMENDED},
        "WAIT is legal only for an unadmitted arrival",
    )
    request_id = event["payload"]["request_id"]
    _require(request_id in work.pending_requests, "WAIT request does not exist")
    request = work.pending_requests[request_id]
    elapsed = event["sim_time_s"] - request.requested_at_s
    _require(elapsed < work.source.max_arrival_wait_s, "arrival wait deadline reached")
    waiting_count = sum(
        item.location_state.kind is LocationKind.ENTRY_QUEUE
        and item.arrival_status in {ArrivalStatus.PENDING, ArrivalStatus.RECOMMENDED}
        and item.waiting_since_s is not None
        for item in work.vehicles.values()
    )
    if vehicle.waiting_since_s is None:
        _require(
            waiting_count < work.source.arrival_wait_capacity,
            "arrival wait capacity exhausted",
        )
    work.vehicles[vehicle_id] = replace(
        vehicle,
        arrival_status=ArrivalStatus.PENDING,
        waiting_since_s=vehicle.waiting_since_s
        if vehicle.waiting_since_s is not None
        else event["sim_time_s"],
    )


def _apply_assign_recommended(
    state: AuthoritativeState,
    work: _WorkingState,
    event: Mapping[str, Any],
) -> None:
    action = action_from_mapping(event["action"])
    _require(action.status is ActionStatus.RECOMMENDED, "assignment must be RECOMMENDED")
    _require(action.action_type is ActionType.ASSIGN, "event is not an assignment")
    _require(action.action_id not in work.actions, "assignment action already exists")
    vehicle = work.vehicles[action.anonymous_vehicle_id]
    _require(
        vehicle.location_state.kind is LocationKind.ENTRY_QUEUE
        and vehicle.arrival_status in {ArrivalStatus.PENDING, ArrivalStatus.RECOMMENDED},
        "assignment recommendation requires an unadmitted arrival",
    )
    destination = action.destination_position_id
    assert destination is not None
    position = work.positions[destination]
    _require(position.assignable and not position.planned_closure, "slot is not assignable")
    _require(position.physically_available, "slot is physically unavailable")
    _require(not _active_claim_owners(work, destination), "slot already has a capacity owner")
    _assert_entry_clear(state, work, destination)
    _assert_action_path(state, work, action)
    work.actions[action.action_id] = action
    work.vehicles[action.anonymous_vehicle_id] = replace(
        vehicle,
        arrival_status=ArrivalStatus.RECOMMENDED,
        action_context_id=action.action_id,
    )


def _apply_assignment_accepted(
    state: AuthoritativeState,
    work: _WorkingState,
    event: Mapping[str, Any],
) -> None:
    action = action_from_mapping(event["action"])
    _require(action.status is ActionStatus.ACCEPTED, "assignment must be ACCEPTED")
    _replace_action(work, action, {ActionStatus.RECOMMENDED})
    vehicle = work.vehicles[action.anonymous_vehicle_id]
    _require(vehicle.arrival_status is ArrivalStatus.RECOMMENDED, "vehicle not recommended")
    records = event["payload"]["created_reservations"]
    _require(len(records) == 1, "assignment acceptance needs exactly one reservation")
    reservation = reservation_from_mapping(records[0])
    _require(
        reservation.owner_vehicle_id == action.anonymous_vehicle_id
        and reservation.position_id == action.destination_position_id
        and reservation.transaction_id is None
        and reservation.purpose == "admitted_assignment",
        "assignment reservation does not match the accepted action",
    )
    _require(reservation.reservation_id not in work.reservations, "duplicate reservation ID")
    destination = reservation.position_id
    position = work.positions[destination]
    _require(
        position.physically_available and position.assignable and not position.planned_closure,
        "accepted assignment destination is no longer assignable",
    )
    _require(
        not _active_claim_owners(work, destination),
        "assignment destination acquired another owner",
    )
    _assert_entry_clear(state, work, destination)
    _assert_action_path(state, work, action)
    work.reservations[reservation.reservation_id] = reservation
    work.vehicles[action.anonymous_vehicle_id] = replace(
        vehicle,
        arrival_status=ArrivalStatus.ADMITTED,
        ever_admitted=True,
        admitted_at_s=vehicle.admitted_at_s
        if vehicle.admitted_at_s is not None
        else event["sim_time_s"],
        waiting_since_s=None,
        action_context_id=action.action_id,
    )
    _remove_pending_for_vehicle(work, action.anonymous_vehicle_id, "ARRIVAL")


def _apply_departure_requested(work: _WorkingState, event: Mapping[str, Any]) -> None:
    vehicle_id = event["anonymous_vehicle_id"]
    vehicle = work.vehicles[vehicle_id]
    location = vehicle.location_state
    _require(location.kind is LocationKind.AT_POSITION, "departure requires a parked vehicle")
    assert location.position_id is not None
    _require(
        work.positions[location.position_id].position_kind is PositionKind.NORMAL,
        "normal departure cannot be requested from a buffer",
    )
    _require(
        vehicle.departure_status in {DepartureStatus.NONE, DepartureStatus.PENDING},
        "departure already in service or completed",
    )
    request = pending_request_from_mapping(event["payload"]["pending_request"])
    _require(request.anonymous_vehicle_id == vehicle_id, "departure request vehicle mismatch")
    _require(request.request_type == "DEPARTURE", "wrong departure request type")
    work.vehicles[vehicle_id] = replace(
        vehicle,
        departure_status=DepartureStatus.PENDING,
    )
    work.pending_requests[request.request_id] = request


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
    _require(
        target.location_state.kind is LocationKind.AT_POSITION,
        "transaction target is not parked",
    )
    target_position = target.location_state.position_id
    assert target_position is not None
    blockers = _shallower_occupants(state, work, target_position)
    expected_blockers = tuple(vehicle_id for _, vehicle_id in blockers)
    _require(
        transaction.blocker_vehicle_ids == expected_blockers,
        "transaction blocker list is not the actual shallow-to-deep order",
    )
    metadata = _metadata_by_position(state)
    for assignment, (origin_id, blocker_id) in zip(
        transaction.buffer_assignments,
        blockers,
        strict=True,
    ):
        _require(assignment.blocker_vehicle_id == blocker_id, "buffer mapping vehicle mismatch")
        _require(assignment.original_position_id == origin_id, "original position mismatch")
        _require(
            assignment.buffer_position_id in state.active_buffer_position_ids,
            "buffer is not active for this scenario",
        )
        _require(
            metadata[assignment.buffer_position_id].position_kind is PositionKind.BUFFER,
            "buffer mapping points to a normal position",
        )
        _require(
            not _active_claim_owners(work, assignment.buffer_position_id),
            "buffer already has a capacity owner",
        )
        _require(
            _path_for_nodes(
                state,
                metadata[origin_id].access_node_id,
                metadata[assignment.buffer_position_id].access_node_id,
            )
            is not None
            and _path_for_nodes(
                state,
                metadata[assignment.buffer_position_id].access_node_id,
                metadata[origin_id].access_node_id,
            )
            is not None,
            "buffer round trip is unreachable",
        )
    for vehicle_id in (
        transaction.target_vehicle_id,
        *transaction.blocker_vehicle_ids,
    ):
        _require(
            work.vehicles[vehicle_id].active_transaction_id is None,
            f"vehicle {vehicle_id} already belongs to another transaction",
        )

    actions = tuple(action_from_mapping(item) for item in event["payload"]["transaction_actions"])
    _require(
        all(
            item.status is ActionStatus.ACCEPTED and item.transaction_id == transaction_id
            for item in actions
        ),
        "transaction actions must be ACCEPTED and owned by the transaction",
    )
    canonical_order = _expected_transaction_actions(transaction, actions)
    _require(
        transaction.action_ids == canonical_order,
        "transaction action_ids are not in canonical physical order",
    )
    expected_edges = tuple(pairwise(canonical_order))
    actual_edges = tuple(
        (item.before_action_id, item.after_action_id) for item in transaction.precedence_edges
    )
    _require(actual_edges == expected_edges, "transaction precedence is not the canonical chain")

    assignment_by_vehicle = {
        item.blocker_vehicle_id: item for item in transaction.buffer_assignments
    }
    for action in actions:
        _assert_action_path(state, work, action)
        if action.action_type is ActionType.RELOCATE_TO_BUFFER:
            assignment = assignment_by_vehicle[action.anonymous_vehicle_id]
            _require(
                action.origin_position_id == assignment.original_position_id
                and action.destination_position_id == assignment.buffer_position_id,
                "relocate action disagrees with buffer mapping",
            )
        elif action.action_type is ActionType.RESTORE_ORIGINAL:
            assignment = assignment_by_vehicle[action.anonymous_vehicle_id]
            _require(
                action.origin_position_id == assignment.buffer_position_id
                and action.destination_position_id == assignment.original_position_id,
                "restore action disagrees with original-position mapping",
            )

    reservations = tuple(
        reservation_from_mapping(item) for item in event["payload"]["created_reservations"]
    )
    expected_reservations = {
        (item.blocker_vehicle_id, item.buffer_position_id, "buffer_destination")
        for item in transaction.buffer_assignments
    } | {
        (item.blocker_vehicle_id, item.original_position_id, "restore_original")
        for item in transaction.buffer_assignments
    }
    actual_reservations = {
        (item.owner_vehicle_id, item.position_id, item.purpose) for item in reservations
    }
    _require(
        actual_reservations == expected_reservations
        and all(item.transaction_id == transaction_id for item in reservations),
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
        actual_locks == expected_locks
        and all(item.transaction_id == transaction_id for item in locks),
        "transaction locks are not the exact target/blockers/group set",
    )
    existing_lock_resources = {
        (item.resource_type, item.resource_id) for item in work.locks.values()
    }
    _require(
        not (actual_locks & existing_lock_resources),
        "transaction lock conflicts with an existing transaction",
    )
    all_new_ids = {
        transaction_id,
        *(item.action_id for item in actions),
        *(item.reservation_id for item in reservations),
        *(item.lock_id for item in locks),
    }
    existing_ids = (
        set(work.transactions) | set(work.actions) | set(work.reservations) | set(work.locks)
    )
    _require(not (all_new_ids & existing_ids), "transaction runtime ID already exists")
    _require(
        len(all_new_ids) == 1 + len(actions) + len(reservations) + len(locks),
        "transaction runtime IDs collide",
    )

    work.transactions[transaction_id] = transaction
    work.actions.update({item.action_id: item for item in actions})
    work.reservations.update({item.reservation_id: item for item in reservations})
    work.locks.update({item.lock_id: item for item in locks})
    for vehicle_id in (
        transaction.target_vehicle_id,
        *transaction.blocker_vehicle_ids,
    ):
        work.vehicles[vehicle_id] = replace(
            work.vehicles[vehicle_id],
            active_transaction_id=transaction_id,
        )


def _apply_action_recommended(
    state: AuthoritativeState,
    work: _WorkingState,
    event: Mapping[str, Any],
) -> None:
    action = action_from_mapping(event["action"])
    _require(action.status is ActionStatus.RECOMMENDED, "action must be RECOMMENDED")
    _require(action.action_type is not ActionType.ASSIGN, "ASSIGN uses its dedicated event")
    _require(action.action_id not in work.actions, "action already exists")
    vehicle = work.vehicles[action.anonymous_vehicle_id]
    _require(
        vehicle.departure_status is DepartureStatus.PENDING,
        "departure action requires a pending departure",
    )
    if action.action_type is ActionType.DIRECT_EXIT:
        _require(
            vehicle.location_state.kind is LocationKind.AT_POSITION
            and vehicle.location_state.position_id == action.origin_position_id,
            "direct-exit origin does not match vehicle",
        )
        _require(
            not _shallower_occupants(state, work, action.origin_position_id or ""),
            "direct exit is blocked",
        )
    else:
        _require(action.transaction_id in work.transactions, "relocation lacks transaction")
    _assert_action_path(state, work, action)
    work.actions[action.action_id] = action
    work.vehicles[action.anonymous_vehicle_id] = replace(
        vehicle,
        action_context_id=action.action_id,
    )


def _apply_action_accepted(work: _WorkingState, event: Mapping[str, Any]) -> None:
    action = action_from_mapping(event["action"])
    _require(action.status is ActionStatus.ACCEPTED, "action must be ACCEPTED")
    _replace_action(work, action, {ActionStatus.RECOMMENDED})
    vehicle = work.vehicles[action.anonymous_vehicle_id]
    work.vehicles[action.anonymous_vehicle_id] = replace(
        vehicle,
        action_context_id=action.action_id,
    )


def _apply_action_waiting(work: _WorkingState, event: Mapping[str, Any]) -> None:
    action = action_from_mapping(event["action"])
    _require(
        action.status is ActionStatus.WAITING_FOR_RESOURCES,
        "action must be WAITING_FOR_RESOURCES",
    )
    _replace_action(work, action, {ActionStatus.ACCEPTED})


def _assert_predecessors_complete(work: _WorkingState, action: Action) -> None:
    if action.transaction_id is None:
        return
    transaction = work.transactions[action.transaction_id]
    predecessors = {
        item.before_action_id
        for item in transaction.precedence_edges
        if item.after_action_id == action.action_id
    }
    _require(
        all(work.actions[item].status is ActionStatus.COMPLETED for item in predecessors),
        f"action {action.action_id} predecessor is incomplete",
    )


def _apply_action_started(
    state: AuthoritativeState,
    work: _WorkingState,
    event: Mapping[str, Any],
) -> None:
    action = action_from_mapping(event["action"])
    _require(action.status is ActionStatus.STARTED, "action must be STARTED")
    _replace_action(
        work,
        action,
        {ActionStatus.ACCEPTED, ActionStatus.WAITING_FOR_RESOURCES},
    )
    _assert_predecessors_complete(work, action)
    _assert_lock_access(state, work, action)
    vehicle = work.vehicles[action.anonymous_vehicle_id]
    if action.action_type is ActionType.ASSIGN:
        _require(
            vehicle.location_state.kind is LocationKind.ENTRY_QUEUE
            and vehicle.arrival_status is ArrivalStatus.ADMITTED,
            "assignment start requires an admitted entry-queue vehicle",
        )
        destination = action.destination_position_id
        assert destination is not None
        _assert_entry_clear(state, work, destination)
    else:
        _require(
            vehicle.location_state.kind is LocationKind.AT_POSITION
            and vehicle.location_state.position_id == action.origin_position_id,
            "action origin does not match the parked vehicle",
        )
        origin = action.origin_position_id
        assert origin is not None
        work.positions[origin] = replace(
            work.positions[origin],
            occupant_vehicle_id=None,
        )
        if action.action_type is ActionType.DIRECT_EXIT:
            _require(
                vehicle.departure_status is DepartureStatus.PENDING,
                "direct exit start requires pending departure",
            )
            _require(not _shallower_occupants(state, work, origin), "direct exit is blocked")
    if action.destination_position_id is not None:
        _require(
            any(
                item.position_id == action.destination_position_id
                and item.owner_vehicle_id == action.anonymous_vehicle_id
                for item in work.reservations.values()
            ),
            "action destination lacks a vehicle-owned reservation",
        )
    _acquire_resources(work, action)
    work.vehicles[action.anonymous_vehicle_id] = replace(
        vehicle,
        location_state=replace(
            vehicle.location_state,
            kind=LocationKind.IN_TRANSIT,
            position_id=None,
            action_id=action.action_id,
        ),
        departure_status=DepartureStatus.IN_SERVICE
        if action.action_type is ActionType.DIRECT_EXIT
        else vehicle.departure_status,
        action_context_id=action.action_id,
    )


def _apply_action_completed(work: _WorkingState, event: Mapping[str, Any]) -> None:
    action = action_from_mapping(event["action"])
    _require(action.status is ActionStatus.COMPLETED, "action must be COMPLETED")
    _replace_action(work, action, {ActionStatus.STARTED})
    vehicle = work.vehicles[action.anonymous_vehicle_id]
    _require(
        vehicle.location_state.kind is LocationKind.IN_TRANSIT
        and vehicle.location_state.action_id == action.action_id,
        "completed action vehicle is not in its transit state",
    )
    _release_resources(work, action)
    if action.action_type is ActionType.DIRECT_EXIT:
        work.vehicles[action.anonymous_vehicle_id] = replace(
            vehicle,
            location_state=replace(
                vehicle.location_state,
                kind=LocationKind.EXITED,
                position_id=None,
                action_id=None,
            ),
            departure_status=DepartureStatus.COMPLETED,
            action_context_id=None,
        )
        _remove_pending_for_vehicle(work, action.anonymous_vehicle_id, "DEPARTURE")
        return
    destination = action.destination_position_id
    assert destination is not None
    _require(
        work.positions[destination].occupant_vehicle_id is None,
        "completed destination is occupied",
    )
    work.positions[destination] = replace(
        work.positions[destination],
        occupant_vehicle_id=action.anonymous_vehicle_id,
    )
    work.vehicles[action.anonymous_vehicle_id] = replace(
        vehicle,
        location_state=replace(
            vehicle.location_state,
            kind=LocationKind.AT_POSITION,
            position_id=destination,
            action_id=None,
        ),
        arrival_status=ArrivalStatus.ENTRY_COMPLETED
        if action.action_type is ActionType.ASSIGN
        else vehicle.arrival_status,
        action_context_id=None,
    )
    if action.action_type is ActionType.ASSIGN:
        work.reservations = {
            key: item
            for key, item in work.reservations.items()
            if not (
                item.owner_vehicle_id == action.anonymous_vehicle_id
                and item.position_id == destination
                and item.purpose == "admitted_assignment"
            )
        }


def _fail_transaction_if_needed(work: _WorkingState, action: Action) -> None:
    if action.transaction_id is None:
        return
    transaction = work.transactions[action.transaction_id]
    work.transactions[action.transaction_id] = replace(
        transaction,
        status=TransactionStatus.FAILED_MANUAL_PENDING,
    )


def _apply_action_failed_known(work: _WorkingState, event: Mapping[str, Any]) -> None:
    action = action_from_mapping(event["action"])
    _require(
        action.status is ActionStatus.FAILED
        and action.position_confirmation is not PositionConfirmation.UNKNOWN,
        "known-position failure must be FAILED with a known confirmation",
    )
    _replace_action(work, action, {ActionStatus.STARTED})
    vehicle = work.vehicles[action.anonymous_vehicle_id]
    location = location_from_mapping(event["payload"]["confirmed_location_state"])
    _require(location.kind is LocationKind.AT_POSITION, "known failure needs AT_POSITION")
    position_id = location.position_id
    assert position_id is not None
    if action.position_confirmation is PositionConfirmation.AT_ORIGIN:
        _require(position_id == action.origin_position_id, "AT_ORIGIN confirmation mismatch")
    elif action.position_confirmation is PositionConfirmation.AT_DESTINATION:
        _require(
            position_id == action.destination_position_id,
            "AT_DESTINATION confirmation mismatch",
        )
    elif action.position_confirmation is PositionConfirmation.AT_OTHER_POSITION:
        _require(
            position_id not in {action.origin_position_id, action.destination_position_id},
            "AT_OTHER_POSITION must identify a third modeled position",
        )
    _require(
        work.positions[position_id].occupant_vehicle_id
        in {
            None,
            action.anonymous_vehicle_id,
        },
        "confirmed failure position has another occupant",
    )
    _release_resources(work, action)
    work.positions[position_id] = replace(
        work.positions[position_id],
        occupant_vehicle_id=action.anonymous_vehicle_id,
    )
    work.vehicles[action.anonymous_vehicle_id] = replace(
        vehicle,
        location_state=location,
        action_context_id=action.action_id,
    )
    _fail_transaction_if_needed(work, action)


def _apply_action_failed_unknown(work: _WorkingState, event: Mapping[str, Any]) -> None:
    action = action_from_mapping(event["action"])
    _require(
        action.status is ActionStatus.FAILED
        and action.position_confirmation is PositionConfirmation.UNKNOWN,
        "unknown-position failure must be FAILED/UNKNOWN",
    )
    _replace_action(work, action, {ActionStatus.STARTED})
    vehicle = work.vehicles[action.anonymous_vehicle_id]
    _release_resources(work, action)
    work.vehicles[action.anonymous_vehicle_id] = replace(
        vehicle,
        location_state=replace(
            vehicle.location_state,
            kind=LocationKind.POSITION_UNCERTAIN,
            position_id=None,
            action_id=action.action_id,
        ),
        action_context_id=action.action_id,
    )
    _fail_transaction_if_needed(work, action)


def _apply_aborted(work: _WorkingState, event: Mapping[str, Any]) -> None:
    action = action_from_mapping(event["action"])
    _require(action.status is ActionStatus.ABORTED, "action must be ABORTED")
    _replace_action(
        work,
        action,
        {
            ActionStatus.RECOMMENDED,
            ActionStatus.ACCEPTED,
            ActionStatus.WAITING_FOR_RESOURCES,
        },
    )
    _require(action.started_at_s is None, "before-start abort cannot have started_at_s")


def _apply_position_reconciled(work: _WorkingState, event: Mapping[str, Any]) -> None:
    vehicle_id = event["anonymous_vehicle_id"]
    vehicle = work.vehicles[vehicle_id]
    _require(
        vehicle.location_state.kind is LocationKind.POSITION_UNCERTAIN,
        "vehicle position is not uncertain",
    )
    location = location_from_mapping(event["payload"]["confirmed_location_state"])
    _require(
        location.kind in {LocationKind.AT_POSITION, LocationKind.EXITED},
        "reconciliation must confirm a position or real exit",
    )
    if location.kind is LocationKind.AT_POSITION:
        position_id = location.position_id
        assert position_id is not None
        _require(
            work.positions[position_id].occupant_vehicle_id in {None, vehicle_id},
            "reconciled position has another occupant",
        )
        work.positions[position_id] = replace(
            work.positions[position_id],
            occupant_vehicle_id=vehicle_id,
        )
    work.vehicles[vehicle_id] = replace(
        vehicle,
        location_state=location,
        action_context_id=None,
        departure_status=DepartureStatus.COMPLETED
        if location.kind is LocationKind.EXITED
        else vehicle.departure_status,
    )


def _apply_transaction_stage(work: _WorkingState, event: Mapping[str, Any]) -> None:
    incoming = transaction_from_mapping(event["transaction"])
    current = work.transactions[incoming.transaction_id]
    _require(
        incoming.transaction_id == event["transaction_id"],
        "transaction stage envelope mismatch",
    )
    actions = [work.actions[action_id] for action_id in current.action_ids]
    legal_next: TransactionStatus
    if current.status is TransactionStatus.RESERVED:
        legal_next = TransactionStatus.MOVING_BLOCKERS_OUT
    elif current.status is TransactionStatus.MOVING_BLOCKERS_OUT:
        relocation_actions = [
            item for item in actions if item.action_type is ActionType.RELOCATE_TO_BUFFER
        ]
        _require(
            all(item.status is ActionStatus.COMPLETED for item in relocation_actions),
            "not all blockers have reached buffers",
        )
        legal_next = TransactionStatus.TARGET_EXITING
    elif current.status is TransactionStatus.TARGET_EXITING:
        target_exit = next(item for item in actions if item.action_type is ActionType.DIRECT_EXIT)
        _require(
            target_exit.status is ActionStatus.COMPLETED,
            "target exit has not completed",
        )
        legal_next = TransactionStatus.RESTORING_ORIGINALS
    elif current.status is TransactionStatus.RESTORING_ORIGINALS:
        restore_actions = [
            item for item in actions if item.action_type is ActionType.RESTORE_ORIGINAL
        ]
        _require(
            all(item.status is ActionStatus.COMPLETED for item in restore_actions),
            "not all blockers have returned to original positions",
        )
        legal_next = TransactionStatus.COMPLETED
    else:
        raise StateTransitionError(f"transaction {current.transaction_id} cannot advance")
    _require(incoming.status is legal_next, "transaction advanced to the wrong stage")
    _require(
        replace(incoming, status=current.status, ended_at_s=current.ended_at_s) == current,
        "transaction immutable fields changed during stage advance",
    )
    work.transactions[incoming.transaction_id] = incoming
    if legal_next is TransactionStatus.COMPLETED:
        _require(
            not any(item.status is ActionStatus.STARTED for item in actions),
            "cannot release a transaction with a started action",
        )
        _release_transaction_protection(work, incoming.transaction_id)


def _apply_transaction_cancelled(work: _WorkingState, event: Mapping[str, Any]) -> None:
    incoming = transaction_from_mapping(event["transaction"])
    current = work.transactions[incoming.transaction_id]
    _require(current.status is TransactionStatus.RESERVED, "transaction is not cancellable")
    _require(incoming.status is TransactionStatus.CANCELLED, "transaction is not CANCELLED")
    _require(
        replace(incoming, status=current.status, ended_at_s=current.ended_at_s) == current,
        "transaction immutable fields changed during cancellation",
    )
    _require(
        not any(
            work.actions[action_id].status
            in {ActionStatus.STARTED, ActionStatus.COMPLETED, ActionStatus.FAILED}
            for action_id in current.action_ids
        ),
        "transaction execution has already started",
    )
    work.transactions[incoming.transaction_id] = incoming
    _release_transaction_protection(work, incoming.transaction_id)


def _apply_transaction_reconciled(work: _WorkingState, event: Mapping[str, Any]) -> None:
    incoming = transaction_from_mapping(event["transaction"])
    current = work.transactions[incoming.transaction_id]
    _require(
        current.status is TransactionStatus.FAILED_MANUAL_PENDING,
        "transaction is not awaiting failure reconciliation",
    )
    _require(
        incoming.status is TransactionStatus.FAILED_RESOLVED,
        "transaction did not enter FAILED_RESOLVED",
    )
    _require(
        replace(incoming, status=current.status, ended_at_s=current.ended_at_s) == current,
        "transaction immutable fields changed during reconciliation",
    )
    affected = (current.target_vehicle_id, *current.blocker_vehicle_ids)
    _require(
        all(
            work.vehicles[item].location_state.kind is not LocationKind.POSITION_UNCERTAIN
            for item in affected
        ),
        "transaction still contains an uncertain vehicle",
    )
    _require(
        not any(
            work.actions[action_id].status is ActionStatus.STARTED
            for action_id in current.action_ids
        ),
        "transaction still has a started action",
    )
    work.transactions[incoming.transaction_id] = incoming
    _release_transaction_protection(work, incoming.transaction_id)


def _apply_reject(work: _WorkingState, event: Mapping[str, Any]) -> None:
    vehicle_id = event["anonymous_vehicle_id"]
    vehicle = work.vehicles[vehicle_id]
    _require(
        not vehicle.ever_admitted and vehicle.location_state.kind is LocationKind.ENTRY_QUEUE,
        "an admitted or non-queued vehicle cannot be rejected",
    )
    work.vehicles[vehicle_id] = replace(
        vehicle,
        location_state=replace(
            vehicle.location_state,
            kind=LocationKind.REJECTED,
            position_id=None,
            action_id=None,
        ),
        arrival_status=ArrivalStatus.REJECTED,
        waiting_since_s=None,
        action_context_id=None,
    )
    _remove_pending_for_vehicle(work, vehicle_id, "ARRIVAL")


def _apply_user_cancelled(work: _WorkingState, event: Mapping[str, Any]) -> None:
    vehicle_id = event["anonymous_vehicle_id"]
    vehicle = work.vehicles[vehicle_id]
    _require(
        vehicle.arrival_status
        in {
            ArrivalStatus.PENDING,
            ArrivalStatus.RECOMMENDED,
            ArrivalStatus.ADMITTED,
        },
        "USER_CANCELLED requires a pending, incomplete arrival",
    )
    _require(
        vehicle.location_state.kind is LocationKind.ENTRY_QUEUE,
        "started movement must be reconciled before cancellation",
    )
    for action_id, action in tuple(work.actions.items()):
        if (
            action.anonymous_vehicle_id == vehicle_id
            and action.action_type is ActionType.ASSIGN
            and action.status
            in {
                ActionStatus.RECOMMENDED,
                ActionStatus.ACCEPTED,
                ActionStatus.WAITING_FOR_RESOURCES,
            }
        ):
            work.actions[action_id] = replace(
                action,
                status=ActionStatus.ABORTED,
                ended_at_s=event["sim_time_s"],
            )
    work.reservations = {
        key: item
        for key, item in work.reservations.items()
        if not (item.owner_vehicle_id == vehicle_id and item.purpose == "admitted_assignment")
    }
    work.vehicles[vehicle_id] = replace(
        vehicle,
        location_state=replace(
            vehicle.location_state,
            kind=LocationKind.EXITED,
            position_id=None,
            action_id=None,
        ),
        arrival_status=ArrivalStatus.CANCELLED,
        waiting_since_s=None,
        action_context_id=None,
    )
    _remove_pending_for_vehicle(work, vehicle_id, "ARRIVAL")


def _apply_manual(work: _WorkingState, event: Mapping[str, Any]) -> None:
    vehicle_id = event["anonymous_vehicle_id"]
    vehicle = work.vehicles[vehicle_id]
    _require(
        vehicle.location_state.kind not in {LocationKind.EXITED, LocationKind.REJECTED},
        "manual intervention cannot target a terminal vehicle",
    )
    if event["event_type"] == "MANUAL_INTERVENTION_REQUESTED":
        status = ManualStatus.REQUESTED
        _require(
            vehicle.manual_status in {ManualStatus.NONE, ManualStatus.FAILED},
            "manual intervention is already active",
        )
    else:
        status = ManualStatus(event["payload"]["manual_status"])
        allowed = {
            ManualStatus.REQUESTED: {ManualStatus.ACKNOWLEDGED, ManualStatus.FAILED},
            ManualStatus.ACKNOWLEDGED: {
                ManualStatus.IN_PROGRESS,
                ManualStatus.FAILED,
            },
            ManualStatus.IN_PROGRESS: {
                ManualStatus.COMPLETED,
                ManualStatus.FAILED,
            },
        }
        _require(status in allowed.get(vehicle.manual_status, set()), "illegal manual status")
    work.vehicles[vehicle_id] = replace(vehicle, manual_status=status)


def _apply_information_updated(work: _WorkingState, event: Mapping[str, Any]) -> None:
    vehicle_id = event["anonymous_vehicle_id"]
    vehicle = work.vehicles[vehicle_id]
    information = departure_information_from_mapping(event["payload"]["departure_information"])
    _require(
        information.known_at_time_s <= event["sim_time_s"],
        "information update is not yet known",
    )
    work.vehicles[vehicle_id] = replace(
        vehicle,
        reservation_status=ReservationStatus(event["payload"]["reservation_status"]),
        departure_information=information,
    )


def apply_event(
    state: AuthoritativeState,
    event: Mapping[str, Any],
) -> AuthoritativeState:
    """Atomically reduce one validated v1 event into a new immutable state."""

    _require(event["schema_version"] == "1.0.0", "unsupported event schema version")
    _require(event["run_id"] == state.run_id, "event run_id differs from state")
    _require(event["scenario_id"] == state.scenario_id, "event scenario_id differs from state")
    _require(
        event["sequence_no"] == state.sequence_no + 1,
        "event sequence_no must be exactly the next integer",
    )
    _require(event["sim_time_s"] >= state.sim_time_s, "event time moved backwards")
    work = _WorkingState.from_state(state)
    event_type = event["event_type"]

    if event_type == "ARRIVAL_REQUESTED":
        _apply_arrival(work, event)
    elif event_type == "WAIT_DECIDED":
        _apply_wait(work, event)
    elif event_type == "ASSIGN_RECOMMENDED":
        _apply_assign_recommended(state, work, event)
    elif event_type == "ASSIGNMENT_ACCEPTED":
        _apply_assignment_accepted(state, work, event)
    elif event_type == "DEPARTURE_REQUESTED":
        _apply_departure_requested(work, event)
    elif event_type == "RELOCATION_TRANSACTION_CREATED":
        _apply_transaction_created(state, work, event)
    elif event_type == "ACTION_RECOMMENDED":
        _apply_action_recommended(state, work, event)
    elif event_type == "ACTION_ACCEPTED":
        _apply_action_accepted(work, event)
    elif event_type == "ACTION_WAITING_FOR_RESOURCES":
        _apply_action_waiting(work, event)
    elif event_type == "ACTION_STARTED":
        _apply_action_started(state, work, event)
    elif event_type == "ACTION_COMPLETED":
        _apply_action_completed(work, event)
    elif event_type == "ACTION_FAILED_KNOWN_POSITION":
        _apply_action_failed_known(work, event)
    elif event_type == "ACTION_FAILED_POSITION_UNKNOWN":
        _apply_action_failed_unknown(work, event)
    elif event_type == "ABORTED_BEFORE_START":
        _apply_aborted(work, event)
    elif event_type == "POSITION_RECONCILED":
        _apply_position_reconciled(work, event)
    elif event_type == "TRANSACTION_STAGE_ADVANCED":
        _apply_transaction_stage(work, event)
    elif event_type == "TRANSACTION_CANCELLED_BEFORE_EXECUTION":
        _apply_transaction_cancelled(work, event)
    elif event_type == "TRANSACTION_RECONCILED":
        _apply_transaction_reconciled(work, event)
    elif event_type == "REJECT_DECIDED":
        _apply_reject(work, event)
    elif event_type == "USER_CANCELLED":
        _apply_user_cancelled(work, event)
    elif event_type in {"MANUAL_INTERVENTION_REQUESTED", "MANUAL_STATUS_CHANGED"}:
        _apply_manual(work, event)
    elif event_type == "INFORMATION_UPDATED":
        _apply_information_updated(work, event)
    elif event_type in {"FALLBACK_USED", "DECISION_TIMER_TRIGGERED"}:
        pass
    else:
        raise StateTransitionError(f"unsupported event type: {event_type}")

    return work.freeze(
        sequence_no=event["sequence_no"],
        sim_time_s=event["sim_time_s"],
    )


def replay_events(
    initial_state: AuthoritativeState,
    events: Sequence[Mapping[str, Any]],
) -> AuthoritativeState:
    """Replay an ordered event sequence with no hidden state or side effects."""

    state = initial_state
    for event in events:
        state = apply_event(state, event)
    return state
