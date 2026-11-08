"""Shared context and reachability helpers for bounded selection."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from parking_opt.domain.enums import ActionStatus, ActionType
from parking_opt.domain.records import DecisionRequest, PendingRequest
from parking_opt.strategies._selection import _locked_resources, _path, _position_claims


def _busy_stack_groups(request: DecisionRequest) -> set[str]:
    group_by_position = {item["position_id"]: item["stack_group_id"] for item in request.layout["slots"]}
    groups: set[str] = set()
    for action in request.observed_snapshot.actions:
        if action.status not in {
            ActionStatus.RECOMMENDED,
            ActionStatus.ACCEPTED,
            ActionStatus.WAITING_FOR_RESOURCES,
            ActionStatus.STARTED,
        }:
            continue
        if action.action_type is ActionType.ASSIGN:
            position_id = action.destination_position_id
        elif action.action_type is ActionType.DIRECT_EXIT:
            position_id = action.origin_position_id
        else:
            continue
        if position_id in group_by_position:
            groups.add(group_by_position[position_id])
    return groups


def _legal_soft_departure_times(request: DecisionRequest) -> dict[str, int]:
    if not bool(request.approved_config["use_soft_departure_information"]):
        return {}
    records: list[tuple[int, str, str, int]] = []
    for vehicle in request.observed_snapshot.vehicles:
        information = vehicle.departure_information
        if (
            information.expected_departure_time_s is not None
            and information.known_at_time_s <= request.decision_time_s
            and information.source.value in {"reservation", "user_estimate", "model_prediction"}
        ):
            records.append(
                (
                    information.known_at_time_s,
                    information.source_record_id or f"{vehicle.anonymous_vehicle_id}-{information.source.value}",
                    vehicle.anonymous_vehicle_id,
                    information.expected_departure_time_s,
                )
            )
    records.sort()
    limit = int(request.approved_config["max_soft_future_records"])
    return {vehicle_id: expected for _, _, vehicle_id, expected in records[:limit]}


def _departure_order_mismatches(
    request: DecisionRequest,
    target: PendingRequest,
    candidate_slot: Mapping[str, Any],
    *,
    slots: tuple[Mapping[str, Any], ...],
    soft_departure_times: Mapping[str, int],
) -> int:
    target_expected = soft_departure_times.get(target.anonymous_vehicle_id)
    if target_expected is None:
        return 0
    depth_by_position = {item["position_id"]: int(item["depth"]) for item in slots}
    occupant_by_position = {
        item.position_id: item.occupant_vehicle_id
        for item in request.observed_snapshot.positions
        if item.occupant_vehicle_id is not None
    }
    candidate_depth = int(candidate_slot["depth"])
    mismatch_count = 0
    for position_id, other_vehicle_id in occupant_by_position.items():
        other_slot = next(
            (item for item in slots if item["position_id"] == position_id and item["stack_group_id"] == candidate_slot["stack_group_id"]),
            None,
        )
        if other_slot is None:
            continue
        other_expected = soft_departure_times.get(other_vehicle_id)
        if other_expected is None:
            continue
        if (candidate_depth - depth_by_position[position_id]) * (target_expected - other_expected) < 0:
            mismatch_count += 1
    return mismatch_count


def _entry_clear(
    slot: Mapping[str, Any],
    *,
    slots: tuple[Mapping[str, Any], ...],
    claims: Mapping[str, set[str]],
    locked: set[tuple[str, str]],
) -> bool:
    if ("stack_group", slot["stack_group_id"]) in locked:
        return False
    for other in slots:
        if (
            other["stack_group_id"] == slot["stack_group_id"]
            and int(other["depth"]) < int(slot["depth"])
            and (claims[other["position_id"]] or ("position", other["position_id"]) in locked)
        ):
            return False
    return ("position", slot["position_id"]) not in locked


def _free_active_buffers(
    request: DecisionRequest,
    buffer_by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    positions = {item.position_id: item for item in request.observed_snapshot.positions}
    claims = _position_claims(request)
    locked = _locked_resources(request)
    return tuple(
        buffer_by_id[buffer_id]
        for buffer_id in request.approved_config["active_buffer_position_ids"]
        if buffer_id in buffer_by_id
        and positions[buffer_id].physically_available
        and not claims[buffer_id]
        and ("position", buffer_id) not in locked
    )
