"""Resource acquisition and release for event reduction."""

from __future__ import annotations

from dataclasses import replace

from parking_opt.domain.records import Action
from parking_opt.domain.state import AuthoritativeState
from parking_opt.domain.transitions import _WorkingState, _require
from parking_opt.domain.transitions_helpers import _metadata_by_position


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
            _require(lock.transaction_id == action.transaction_id, f"action {action.action_id} conflicts with lock {lock.lock_id}")


def _acquire_resources(work: _WorkingState, action: Action) -> None:
    _require(_resources_available(work, action), f"resources unavailable for {action.action_id}")
    if action.executor_units:
        work.executor_resource = replace(
            work.executor_resource,
            used=work.executor_resource.used + action.executor_units,
            active_action_ids=tuple(sorted((*work.executor_resource.active_action_ids, action.action_id))),
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
            active_action_ids=tuple(item for item in work.executor_resource.active_action_ids if item != action.action_id),
        )
    for zone_id, resource in tuple(work.channel_resources.items()):
        if action.action_id in resource.active_action_ids:
            work.channel_resources[zone_id] = replace(
                resource,
                used=resource.used - 1,
                active_action_ids=tuple(item for item in resource.active_action_ids if item != action.action_id),
            )


def _release_transaction_protection(work: _WorkingState, transaction_id: str) -> None:
    work.reservations = {key: item for key, item in work.reservations.items() if item.transaction_id != transaction_id}
    work.locks = {key: item for key, item in work.locks.items() if item.transaction_id != transaction_id}
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
