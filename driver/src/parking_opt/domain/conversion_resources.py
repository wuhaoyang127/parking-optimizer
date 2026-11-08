"""Conversion of resources, defaults, fallback, candidate, timing, and decision."""

from __future__ import annotations

from typing import Any

from parking_opt.domain.conversion_records import action_to_mapping, transaction_to_mapping
from parking_opt.domain.enums import (
    ArrivalStatus,
    DepartureInformationSource,
    DepartureStatus,
    LocationKind,
    ManualStatus,
    ReservationStatus,
)
from parking_opt.domain.records import (
    CandidateGenerationRecord,
    ChannelZoneResourceState,
    DecisionResult,
    DecisionTiming,
    DepartureInformation,
    ExecutorResourceState,
    FallbackRecord,
    LocationState,
    VehicleState,
)


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
