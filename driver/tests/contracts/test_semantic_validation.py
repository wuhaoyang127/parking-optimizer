"""Cross-record constraints and policy information-boundary tests."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from parking_opt.contracts.canonical import canonical_sha256, snapshot_content_sha256
from parking_opt.contracts.errors import ContractValidationError
from parking_opt.contracts.semantic_validation import (
    validate_decision_request_semantics,
    validate_layout_semantics,
    validate_snapshot_semantics,
)


def _constraint_id(error: ContractValidationError) -> str:
    return error.issues[0].constraint_id


def test_valid_layout_snapshot_and_decision_request_pass(
    valid_layout: dict[str, Any],
    valid_snapshot: dict[str, Any],
    valid_decision_request: dict[str, Any],
) -> None:
    validate_layout_semantics(valid_layout)
    validate_snapshot_semantics(valid_snapshot)
    validate_decision_request_semantics(valid_decision_request)


def test_layout_requires_contiguous_tandem_depths(valid_layout: dict[str, Any]) -> None:
    valid_layout["slots"][0]["depth"] = 2

    with pytest.raises(ContractValidationError) as caught:
        validate_layout_semantics(valid_layout)

    assert _constraint_id(caught.value) == "C1_CONTIGUOUS_DEPTH"


def test_layout_keeps_normal_and_buffer_positions_disjoint(
    valid_layout: dict[str, Any],
) -> None:
    valid_layout["buffer_slots"][0]["position_id"] = "slot-1"

    with pytest.raises(ContractValidationError) as caught:
        validate_layout_semantics(valid_layout)

    assert _constraint_id(caught.value) == "C1_POSITION_SET_DISJOINT"


def test_layout_rejects_duplicate_runtime_ids(valid_layout: dict[str, Any]) -> None:
    valid_layout["road_nodes"].append(deepcopy(valid_layout["road_nodes"][0]))

    with pytest.raises(ContractValidationError) as caught:
        validate_layout_semantics(valid_layout)

    assert _constraint_id(caught.value) == "C1_ID_UNIQUENESS"


def test_layout_rejects_a_path_with_the_wrong_direction(
    valid_layout: dict[str, Any],
) -> None:
    valid_layout["path_costs"][0]["from_node_id"] = "access"
    valid_layout["path_costs"][0]["to_node_id"] = "entry"

    with pytest.raises(ContractValidationError) as caught:
        validate_layout_semantics(valid_layout)

    assert _constraint_id(caught.value) == "C1_PATH_CONTINUITY"


@pytest.mark.parametrize(
    "forbidden_name",
    ["actual_departure_time_s", "license_plate", "simpy_env"],
)
def test_snapshot_rejects_future_truth_pii_and_simulator_objects(
    valid_snapshot: dict[str, Any],
    forbidden_name: str,
) -> None:
    valid_snapshot["nested_probe"] = {forbidden_name: "forbidden"}

    with pytest.raises(ContractValidationError) as caught:
        validate_snapshot_semantics(valid_snapshot)

    assert _constraint_id(caught.value) == "C1_FORBIDDEN_INFORMATION_FIELD"


def test_snapshot_rejects_information_not_visible_at_decision_time(
    valid_snapshot: dict[str, Any],
) -> None:
    valid_snapshot["vehicles"] = [
        {
            "anonymous_vehicle_id": "vehicle-1",
            "location_state": {"kind": "ENTRY_QUEUE"},
            "arrival_status": "PENDING",
            "departure_status": "NONE",
            "manual_status": "NONE",
            "ever_admitted": False,
            "admitted_at_s": None,
            "waiting_since_s": 0,
            "action_context_id": None,
            "active_transaction_id": None,
            "reservation_status": "NONE",
            "departure_information": {
                "expected_departure_time_s": 100,
                "source": "user_estimate",
                "known_at_time_s": 1,
                "source_record_id": "estimate-1",
                "model_id": None,
                "generated_at_time_s": None,
                "training_data_cutoff_s": None,
                "feature_window_end_s": None,
            },
        }
    ]

    with pytest.raises(ContractValidationError) as caught:
        validate_snapshot_semantics(valid_snapshot)

    assert _constraint_id(caught.value) == "C1_INFORMATION_VISIBILITY"


def test_snapshot_rejects_hash_mismatch(valid_snapshot: dict[str, Any]) -> None:
    valid_snapshot["decision_time_s"] = 1

    with pytest.raises(ContractValidationError) as caught:
        validate_snapshot_semantics(valid_snapshot)

    assert _constraint_id(caught.value) == "C1_SNAPSHOT_HASH"


def test_decision_request_hashes_are_bound_to_visible_inputs(
    valid_decision_request: dict[str, Any],
) -> None:
    valid_decision_request["approved_config"]["max_requests_per_solve"] = 5

    with pytest.raises(ContractValidationError) as caught:
        validate_decision_request_semantics(valid_decision_request)

    assert _constraint_id(caught.value) == "C1_DECISION_HASH"


def test_arrival_trigger_must_match_one_visible_pending_request(
    valid_decision_request: dict[str, Any],
) -> None:
    request = deepcopy(valid_decision_request)
    request["trigger_event_type"] = "ARRIVAL_REQUESTED"
    request["trigger_request_id"] = "arrival-1"
    request["trigger_anonymous_vehicle_id"] = "vehicle-1"
    request["observed_snapshot"]["snapshot_content_sha256"] = snapshot_content_sha256(
        request["observed_snapshot"]
    )
    request["visible_snapshot_sha256"] = request["observed_snapshot"]["snapshot_content_sha256"]
    request["config_sha256"] = canonical_sha256(request["approved_config"])
    request["layout_sha256"] = canonical_sha256(request["layout"])

    with pytest.raises(ContractValidationError) as caught:
        validate_decision_request_semantics(request)

    assert _constraint_id(caught.value) == "C1_TRIGGER_TARGET_MATCH"
