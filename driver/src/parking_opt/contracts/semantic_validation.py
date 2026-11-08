"""Cross-record semantic guards that JSON Schema cannot express."""

from collections.abc import Mapping, Sequence
from typing import Any

from parking_opt.contracts.errors import ContractValidationError, ValidationIssue

FORBIDDEN_FIELD_NAMES = frozenset(
    {
        "actual_arrival_time_s",
        "actual_departure_time_s",
        "event_queue",
        "future_events",
        "license_plate",
        "oracle_result",
        "plate_number",
        "simpy_env",
        "truth_events",
        "truth_store",
    }
)


def _issue(
    constraint_id: str,
    pointer: str,
    message: str,
    observed_value: object | None = None,
) -> ContractValidationError:
    return ContractValidationError(
        (
            ValidationIssue(
                error_code="SEMANTIC_VALIDATION_FAILED",
                json_pointer=pointer,
                constraint_id=constraint_id,
                message=message,
                observed_value=observed_value,
            ),
        )
    )


def _unique_ids(records: Sequence[Mapping[str, Any]], field: str, pointer: str) -> set[str]:
    values = [record[field] for record in records]
    if len(values) != len(set(values)):
        raise _issue("C1_ID_UNIQUENESS", pointer, f"{field} values must be unique", values)
    return set(values)


def assert_no_forbidden_fields(value: object, pointer: str = "") -> None:
    """Reject truth, simulator, oracle, and direct-identifier fields recursively."""

    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            child_pointer = f"{pointer}/{key_text}"
            if key_text.casefold() in FORBIDDEN_FIELD_NAMES:
                raise _issue(
                    "C1_FORBIDDEN_INFORMATION_FIELD",
                    child_pointer,
                    "field is forbidden at the policy contract boundary",
                    key_text,
                )
            assert_no_forbidden_fields(child, child_pointer)
    elif isinstance(value, list | tuple):
        for index, child in enumerate(value):
            assert_no_forbidden_fields(child, f"{pointer}/{index}")


def _validate_departure_information(
    information: Mapping[str, Any],
    decision_time_s: int,
    pointer: str,
) -> None:
    if information["known_at_time_s"] > decision_time_s:
        raise _issue(
            "C1_INFORMATION_VISIBILITY",
            f"{pointer}/known_at_time_s",
            "departure information is not yet visible",
            information["known_at_time_s"],
        )
    if information["source"] == "model_prediction":
        lineage = (
            information["training_data_cutoff_s"],
            information["feature_window_end_s"],
            information["generated_at_time_s"],
            information["known_at_time_s"],
        )
        if any(value is None for value in lineage) or tuple(lineage) != tuple(sorted(lineage)):
            raise _issue(
                "C1_PREDICTION_LINEAGE",
                pointer,
                "prediction lineage times must be non-null and monotonic",
                lineage,
            )


from parking_opt.contracts.semantic_layout import validate_layout_semantics  # noqa: E402
from parking_opt.contracts.semantic_scenario import (  # noqa: E402
    validate_decision_request_semantics,
    validate_scenario_semantics,
)
from parking_opt.contracts.semantic_snapshot import validate_snapshot_semantics  # noqa: E402
