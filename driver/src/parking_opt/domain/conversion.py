"""Lossless conversion between v1 JSON records and immutable domain values."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from parking_opt.domain.enums import DepartureInformationSource, LocationKind
from parking_opt.domain.records import (
    DepartureInformation,
    LocationState,
    PositionState,
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


from parking_opt.domain.conversion_records import (  # noqa: E402
    action_from_mapping,
    action_to_mapping,
    lock_from_mapping,
    lock_to_mapping,
    pending_request_from_mapping,
    pending_request_to_mapping,
    reservation_from_mapping,
    reservation_to_mapping,
    transaction_from_mapping,
    transaction_to_mapping,
)
from parking_opt.domain.conversion_resources import (  # noqa: E402
    candidate_generation_to_mapping,
    channel_resource_to_mapping,
    decision_result_to_mapping,
    decision_timing_to_mapping,
    default_unknown_departure_information,
    executor_resource_to_mapping,
    fallback_record_to_mapping,
    initial_vehicle_state,
)
