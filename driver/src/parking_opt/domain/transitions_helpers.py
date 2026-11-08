"""Shared path, claim, and entry helpers for event reduction."""

from __future__ import annotations

from parking_opt.domain.enums import ActionStatus, ActionType, PositionKind
from parking_opt.domain.records import Action
from parking_opt.domain.state import AuthoritativeState, PositionMetadata
from parking_opt.domain.transitions import _WorkingState, _require


def _metadata_by_position(state: AuthoritativeState) -> dict[str, PositionMetadata]:
    return {item.position_id: item for item in state.position_metadata}


def _active_claim_owners(work: _WorkingState, position_id: str) -> set[str]:
    position = work.positions[position_id]
    owners = {position.occupant_vehicle_id} if position.occupant_vehicle_id else set()
    owners.update(item.owner_vehicle_id for item in work.reservations.values() if item.position_id == position_id)
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
            (item for item in work.pending_requests.values() if item.anonymous_vehicle_id == action.anonymous_vehicle_id and item.request_type == "ARRIVAL"),
            None,
        )
        if request is None or request.entrance_node_id is None:
            return None
        return _path_for_nodes(state, request.entrance_node_id, metadata[destination].access_node_id)
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
    _require(abs(action.distance_m - distance_m) <= 1e-9, f"action {action.action_id} distance differs from materialized path")
    _require(action.channel_zone_ids == zone_ids, f"action {action.action_id} channel zones differ from materialized path")


def _shallower_occupants(
    state: AuthoritativeState,
    work: _WorkingState,
    target_position_id: str,
) -> tuple[tuple[str, str], ...]:
    metadata = _metadata_by_position(state)
    target = metadata[target_position_id]
    _require(
        target.position_kind is PositionKind.NORMAL and target.stack_group_id is not None and target.depth is not None,
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
    return tuple((position_id, vehicle_id) for _, position_id, vehicle_id in sorted(result, key=lambda item: item[0]))


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
            _require(not _active_claim_owners(work, item.position_id), f"entry to {destination_id} is blocked by {item.position_id}")
            _require(
                not any(lock.resource_type == "position" and lock.resource_id == item.position_id for lock in work.locks.values()),
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
    _require(current.status in allowed_previous, f"action {incoming.action_id} cannot move from {current.status} to {incoming.status}")
    _require(_same_action_definition(current, incoming), f"action {incoming.action_id} immutable fields changed")
    work.actions[incoming.action_id] = incoming
