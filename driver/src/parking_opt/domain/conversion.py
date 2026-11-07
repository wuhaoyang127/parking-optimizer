"""Lossless conversion between v1 JSON records and immutable domain values."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from parking_opt.domain.enums import (
    ActionStatus,
    ActionType,
    ArrivalStatus,
    DepartureInformationSource,
    DepartureStatus,
    ExecutorType,
    LocationKind,
    ManualStatus,
    PositionConfirmation,
    ReservationStatus,
    TransactionStatus,
)
from parking_opt.domain.records import (
    Action,
    BufferAssignment,
    CandidateGenerationRecord,
    ChannelZoneResourceState,
    DecisionResult,
    DecisionTiming,
    DepartureInformation,
    ExecutorResourceState,
    FallbackRecord,
    LocationState,
    PendingRequest,
    PositionReservation,
    PositionState,
    PrecedenceEdge,
    RelocationTransaction,
    ResourceLock,
    VehicleState,
)


def departure_information_from_mapping(value: Mapping[str, Any]) -> DepartureInformation:
    """Build immutable visible departure information from a v1 mapping."""

    return DepartureInformation(
        expected_departure_time_s=value["expected_departure_time_s"],
        source=DepartureInformationSource(value["source"]),
        known_at_time_s=value["known_at_time_s"],
        source_record_id=value["source_record_id"],
        model_id=value["model_id"],
        generated_at_time_s=value["generated_at_time_s"],
        training_data_cutoff_s=value["training_data_cutoff_s"],
        feature_window_end_s=value["feature_window_end_s"],
    )


def departure_information_to_mapping(value: DepartureInformation) -> dict[str, Any]:
    """Serialize departure information without adding hidden fields."""

    return {
        "expected_departure_time_s": value.expected_departure_time_s,
        "source": value.source.value,
        "known_at_time_s": value.known_at_time_s,
        "source_record_id": value.source_record_id,
        "model_id": value.model_id,
        "generated_at_time_s": value.generated_at_time_s,
        "training_data_cutoff_s": value.training_data_cutoff_s,
        "feature_window_end_s": value.feature_window_end_s,
    }


def location_from_mapping(value: Mapping[str, Any]) -> LocationState:
    """Build a mutually exclusive location value."""

    return LocationState(
        kind=LocationKind(value["kind"]),
        position_id=value.get("position_id"),
        action_id=value.get("action_id"),
    )


def location_to_mapping(value: LocationState) -> dict[str, Any]:
    """Serialize only the fields permitted for the selected location kind."""

    result: dict[str, Any] = {"kind": value.kind.value}
    if value.position_id is not None:
        result["position_id"] = value.position_id
    if value.action_id is not None:
        result["action_id"] = value.action_id
    return result


def vehicle_to_mapping(value: VehicleState) -> dict[str, Any]:
    """Serialize a visible vehicle state."""

    return {
        "anonymous_vehicle_id": value.anonymous_vehicle_id,
        "location_state": location_to_mapping(value.location_state),
        "arrival_status": value.arrival_status.value,
        "departure_status": value.departure_status.value,
        "manual_status": value.manual_status.value,
        "ever_admitted": value.ever_admitted,
        "admitted_at_s": value.admitted_at_s,
        "waiting_since_s": value.waiting_since_s,
        "action_context_id": value.action_context_id,
        "active_transaction_id": value.active_transaction_id,
        "reservation_status": value.reservation_status.value,
        "departure_information": departure_information_to_mapping(value.departure_information),
    }


def position_to_mapping(value: PositionState) -> dict[str, Any]:
    """Serialize one normal or buffer position state."""

    return {
        "position_id": value.position_id,
        "position_kind": value.position_kind.value,
        "physically_available": value.physically_available,
        "assignable": value.assignable,
        "planned_closure": value.planned_closure,
        "occupant_vehicle_id": value.occupant_vehicle_id,
    }


def reservation_from_mapping(value: Mapping[str, Any]) -> PositionReservation:
    """Build a vehicle-owned position reservation."""

    return PositionReservation(
        reservation_id=value["reservation_id"],
        position_id=value["position_id"],
        owner_vehicle_id=value["owner_vehicle_id"],
        transaction_id=value["transaction_id"],
        purpose=value["purpose"],
        created_at_s=value["created_at_s"],
    )


def reservation_to_mapping(value: PositionReservation) -> dict[str, Any]:
    """Serialize a position-capacity claim."""

    return {
        "reservation_id": value.reservation_id,
        "position_id": value.position_id,
        "owner_vehicle_id": value.owner_vehicle_id,
        "transaction_id": value.transaction_id,
        "purpose": value.purpose,
        "created_at_s": value.created_at_s,
    }


def lock_from_mapping(value: Mapping[str, Any]) -> ResourceLock:
    """Build a transaction-owned access lock."""

    return ResourceLock(
        lock_id=value["lock_id"],
        resource_type=value["resource_type"],
        resource_id=value["resource_id"],
        transaction_id=value["transaction_id"],
        created_at_s=value["created_at_s"],
    )


def lock_to_mapping(value: ResourceLock) -> dict[str, Any]:
    """Serialize an access lock without treating it as capacity."""

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
    """Build a replay-stably ordered pending request."""

    return PendingRequest(
        request_id=value["request_id"],
        anonymous_vehicle_id=value["anonymous_vehicle_id"],
        request_type=value["request_type"],
        requested_at_s=value["requested_at_s"],
        event_sequence_no=value["event_sequence_no"],
        entrance_node_id=value["entrance_node_id"],
    )


def pending_request_to_mapping(value: PendingRequest) -> dict[str, Any]:
    """Serialize a visible pending request."""

    return {
        "request_id": value.request_id,
        "anonymous_vehicle_id": value.anonymous_vehicle_id,
        "request_type": value.request_type,
        "requested_at_s": value.requested_at_s,
        "event_sequence_no": value.event_sequence_no,
        "entrance_node_id": value.entrance_node_id,
    }


def executor_resource_to_mapping(value: ExecutorResourceState) -> dict[str, Any]:
    """Serialize aggregate executor capacity and ownership."""

    return {
        "capacity": value.capacity,
        "used": value.used,
        "active_action_ids": list(value.active_action_ids),
    }


def channel_resource_to_mapping(value: ChannelZoneResourceState) -> dict[str, Any]:
    """Serialize one coarse channel-zone resource."""

    return {
        "channel_zone_id": value.channel_zone_id,
        "capacity": value.capacity,
        "used": value.used,
        "active_action_ids": list(value.active_action_ids),
    }


def default_unknown_departure_information() -> DepartureInformation:
    """Return the visible no-estimate value for a newly arrived vehicle."""

    return DepartureInformation(
        expected_departure_time_s=None,
        source=DepartureInformationSource.UNKNOWN,
        known_at_time_s=0,
    )


def initial_vehicle_state(vehicle_id: str) -> VehicleState:
    """Create the B2 ARRIVAL_REQUESTED state."""

    return VehicleState(
        anonymous_vehicle_id=vehicle_id,
        location_state=LocationState(LocationKind.ENTRY_QUEUE),
        arrival_status=ArrivalStatus.PENDING,
        departure_status=DepartureStatus.NONE,
        manual_status=ManualStatus.NONE,
        ever_admitted=False,
        admitted_at_s=None,
        waiting_since_s=None,
        action_context_id=None,
        active_transaction_id=None,
        reservation_status=ReservationStatus.NONE,
        departure_information=default_unknown_departure_information(),
    )


def fallback_record_to_mapping(value: FallbackRecord) -> dict[str, Any]:
    """Serialize fallback provenance separately from solver status."""

    return {
        "original_method": value.original_method,
        "original_solver_status": value.original_solver_status.value,
        "reason": value.reason,
        "used_strategy": value.used_strategy,
        "elapsed_s": value.elapsed_s,
        "result_validation_status": value.result_validation_status.value,
    }


def candidate_generation_to_mapping(value: CandidateGenerationRecord) -> dict[str, Any]:
    """Serialize bounded candidate-generation counts and truncation reasons."""

    return {
        "requests_seen": value.requests_seen,
        "requests_kept": value.requests_kept,
        "positions_seen": value.positions_seen,
        "positions_kept": value.positions_kept,
        "buffer_matchings_seen": value.buffer_matchings_seen,
        "buffer_matchings_kept": value.buffer_matchings_kept,
        "action_plans_kept": value.action_plans_kept,
        "truncation_reasons": list(value.truncation_reasons),
    }


def decision_timing_to_mapping(value: DecisionTiming) -> dict[str, float]:
    """Serialize the approved timing partition."""

    return {
        "end_to_end_s": value.end_to_end_s,
        "validation_and_modeling_s": value.validation_and_modeling_s,
        "solver_s": value.solver_s,
        "postsolve_validation_s": value.postsolve_validation_s,
        "minimum_logging_s": value.minimum_logging_s,
        "solver_time_limit_s": value.solver_time_limit_s,
    }


def decision_result_to_mapping(value: DecisionResult) -> dict[str, Any]:
    """Serialize a policy result exactly as decision.schema.json expects."""

    return {
        "record_type": "decision_result",
        "schema_version": "1.0.0",
        "decision_id": value.decision_id,
        "request_id": value.request_id,
        "algorithm_id": value.algorithm_id,
        "algorithm_version": value.algorithm_version,
        "config_sha256": value.config_sha256,
        "layout_sha256": value.layout_sha256,
        "visible_snapshot_sha256": value.visible_snapshot_sha256,
        "input_model_sha256": value.input_model_sha256,
        "target_request_id": value.target_request_id,
        "target_anonymous_vehicle_id": value.target_anonymous_vehicle_id,
        "primary_decision": value.primary_decision.value,
        "recommended_actions": [action_to_mapping(item) for item in value.recommended_actions],
        "candidate_transaction": (
            transaction_to_mapping(value.candidate_transaction)
            if value.candidate_transaction is not None
            else None
        ),
        "solver_status": value.solver_status.value,
        "fallback_record": (
            fallback_record_to_mapping(value.fallback_record)
            if value.fallback_record is not None
            else None
        ),
        "validation_status": value.validation_status.value,
        "explanation_codes": list(value.explanation_codes),
        "candidate_generation": (
            candidate_generation_to_mapping(value.candidate_generation)
            if value.candidate_generation is not None
            else None
        ),
        "timing": decision_timing_to_mapping(value.timing),
    }
