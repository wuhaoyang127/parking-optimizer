"""Conversion of reservation, lock, action, transaction, and pending records."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from parking_opt.domain.enums import (
    ActionStatus,
    ActionType,
    ExecutorType,
    PositionConfirmation,
    TransactionStatus,
)
from parking_opt.domain.records import (
    Action,
    BufferAssignment,
    PendingRequest,
    PositionReservation,
    PrecedenceEdge,
    RelocationTransaction,
    ResourceLock,
)

def reservation_from_mapping(value: Mapping[str, Any]) -> PositionReservation:

    return PositionReservation(
        reservation_id=value["reservation_id"],
        position_id=value["position_id"],
        owner_vehicle_id=value["owner_vehicle_id"],
        transaction_id=value["transaction_id"],
        purpose=value["purpose"],
        created_at_s=value["created_at_s"],
    )

def reservation_to_mapping(value: PositionReservation) -> dict[str, Any]:

    return {
        "reservation_id": value.reservation_id,
        "position_id": value.position_id,
        "owner_vehicle_id": value.owner_vehicle_id,
        "transaction_id": value.transaction_id,
        "purpose": value.purpose,
        "created_at_s": value.created_at_s,
    }

def lock_from_mapping(value: Mapping[str, Any]) -> ResourceLock:

    return ResourceLock(
        lock_id=value["lock_id"],
        resource_type=value["resource_type"],
        resource_id=value["resource_id"],
        transaction_id=value["transaction_id"],
        created_at_s=value["created_at_s"],
    )

def lock_to_mapping(value: ResourceLock) -> dict[str, Any]:

    return {
        "lock_id": value.lock_id,
        "resource_type": value.resource_type,
        "resource_id": value.resource_id,
        "transaction_id": value.transaction_id,
        "created_at_s": value.created_at_s,
    }

def action_from_mapping(value: Mapping[str, Any]) -> Action:
    """Build a complete immutable action record."""

    return Action(
        action_id=value["action_id"],
        transaction_id=value["transaction_id"],
        anonymous_vehicle_id=value["anonymous_vehicle_id"],
        action_type=ActionType(value["action_type"]),
        status=ActionStatus(value["status"]),
        origin_position_id=value["origin_position_id"],
        destination_position_id=value["destination_position_id"],
        destination_exit_id=value["destination_exit_id"],
        distance_m=float(value["distance_m"]),
        modeled_duration_s=value["modeled_duration_s"],
        executor_type=ExecutorType(value["executor_type"]),
        executor_units=value["executor_units"],
        channel_zone_ids=tuple(value["channel_zone_ids"]),
        reason=value["reason"],
        distance_value_source=value["distance_value_source"],
        duration_value_source=value["duration_value_source"],
        recommended_at_s=value["recommended_at_s"],
        accepted_at_s=value["accepted_at_s"],
        started_at_s=value["started_at_s"],
        ended_at_s=value["ended_at_s"],
        failure_reason=value["failure_reason"],
        position_confirmation=PositionConfirmation(value["position_confirmation"]),
    )

def action_to_mapping(value: Action) -> dict[str, Any]:
    """Serialize an action exactly as required by the v1 common schema."""

    return {
        "action_id": value.action_id,
        "transaction_id": value.transaction_id,
        "anonymous_vehicle_id": value.anonymous_vehicle_id,
        "action_type": value.action_type.value,
        "status": value.status.value,
        "reason": value.reason,
        "origin_position_id": value.origin_position_id,
        "destination_position_id": value.destination_position_id,
        "destination_exit_id": value.destination_exit_id,
        "distance_m": value.distance_m,
        "distance_value_source": value.distance_value_source,
        "modeled_duration_s": value.modeled_duration_s,
        "duration_value_source": value.duration_value_source,
        "recommended_at_s": value.recommended_at_s,
        "accepted_at_s": value.accepted_at_s,
        "started_at_s": value.started_at_s,
        "ended_at_s": value.ended_at_s,
        "executor_type": value.executor_type.value,
        "executor_units": value.executor_units,
        "channel_zone_ids": list(value.channel_zone_ids),
        "failure_reason": value.failure_reason,
        "position_confirmation": value.position_confirmation.value,
    }

def transaction_from_mapping(value: Mapping[str, Any]) -> RelocationTransaction:
    """Build a complete passive-relocation transaction."""

    return RelocationTransaction(
        transaction_id=value["transaction_id"],
        target_vehicle_id=value["target_vehicle_id"],
        status=TransactionStatus(value["status"]),
        blocker_vehicle_ids=tuple(value["blocker_vehicle_ids"]),
        buffer_assignments=tuple(
            BufferAssignment(
                blocker_vehicle_id=item["blocker_vehicle_id"],
                original_position_id=item["original_position_id"],
                buffer_position_id=item["buffer_position_id"],
            )
            for item in value["buffer_assignments"]
        ),
        action_ids=tuple(value["action_ids"]),
        precedence_edges=tuple(
            PrecedenceEdge(
                before_action_id=item["before_action_id"],
                after_action_id=item["after_action_id"],
            )
            for item in value["precedence_edges"]
        ),
        created_at_s=value["created_at_s"],
        ended_at_s=value["ended_at_s"],
    )

def transaction_to_mapping(value: RelocationTransaction) -> dict[str, Any]:
    """Serialize a relocation transaction and its canonical action chain."""

    return {
        "transaction_id": value.transaction_id,
        "target_vehicle_id": value.target_vehicle_id,
        "status": value.status.value,
        "blocker_vehicle_ids": list(value.blocker_vehicle_ids),
        "buffer_assignments": [
            {
                "blocker_vehicle_id": item.blocker_vehicle_id,
                "original_position_id": item.original_position_id,
                "buffer_position_id": item.buffer_position_id,
            }
            for item in value.buffer_assignments
        ],
        "action_ids": list(value.action_ids),
        "precedence_edges": [
            {
                "before_action_id": item.before_action_id,
                "after_action_id": item.after_action_id,
            }
            for item in value.precedence_edges
        ],
        "created_at_s": value.created_at_s,
        "ended_at_s": value.ended_at_s,
    }

def pending_request_from_mapping(value: Mapping[str, Any]) -> PendingRequest:

    return PendingRequest(
        request_id=value["request_id"],
        anonymous_vehicle_id=value["anonymous_vehicle_id"],
        request_type=value["request_type"],
        requested_at_s=value["requested_at_s"],
        event_sequence_no=value["event_sequence_no"],
        entrance_node_id=value["entrance_node_id"],
    )

def pending_request_to_mapping(value: PendingRequest) -> dict[str, Any]:

    return {
        "request_id": value.request_id,
        "anonymous_vehicle_id": value.anonymous_vehicle_id,
        "request_type": value.request_type,
        "requested_at_s": value.requested_at_s,
        "event_sequence_no": value.event_sequence_no,
        "entrance_node_id": value.entrance_node_id,
    }
