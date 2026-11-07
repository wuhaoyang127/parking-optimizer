"""Positive and negative tests for all eight approved v1 schemas."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from conftest import (
    minimal_approved_config,
    minimal_decision_request,
    minimal_layout,
    minimal_snapshot,
)

from parking_opt.contracts.errors import ContractValidationError
from parking_opt.contracts.schema_validation import SchemaCatalog


def _valid_scenario() -> dict[str, Any]:
    config = minimal_approved_config()
    scenario_config_keys = {
        "recoverability_policy",
        "buffer_count",
        "active_buffer_position_ids",
        "relocation_executor_capacity",
        "executor_type",
        "relocation_setup_s",
        "relocation_speed_mps",
        "arrival_wait_capacity",
        "max_arrival_wait_s",
        "max_departure_wait_s",
        "fallback_target_s",
        "minimum_logging_reserve_s",
    }
    return {
        "schema_version": "1.0.0",
        "scenario_id": "scenario-1",
        "layout_id": "layout-tiny",
        "data_source": "synthetic",
        "purpose": "manual_case",
        "random_seed": 7,
        "arrival_window_end_s": 60,
        "drain_deadline_s": 120,
        "config": {key: config[key] for key in scenario_config_keys},
        "vehicle_requests": [],
        "truth_events": [],
        "information_updates": [],
    }


def _valid_event() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "event_id": "event-1",
        "run_id": "run-1",
        "scenario_id": "scenario-1",
        "sequence_no": 1,
        "sim_time_s": 0,
        "recorded_at": "2026-07-28T00:00:00Z",
        "event_type": "DECISION_TIMER_TRIGGERED",
        "anonymous_vehicle_id": None,
        "action": None,
        "transaction_id": None,
        "transaction": None,
        "payload": {"timer_reason": "ROLLING_WINDOW_TICK"},
    }


def _valid_metric() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "run_id": "run-1",
        "scenario_id": "scenario-1",
        "algorithm_id": "rule-baseline",
        "algorithm_version": "0.1.0",
        "record_level": "instantaneous",
        "subject_vehicle_id": None,
        "subject_request_id": None,
        "window_start_s": 0,
        "window_end_s": 0,
        "measured_at_s": 0,
        "metric_name": "occupancy_rate",
        "value": 0.0,
        "unit": "ratio",
        "numerator": 0.0,
        "denominator": 1.0,
        "not_applicable_reason": None,
        "event_observed": None,
        "pending_at_horizon": None,
        "observed_wait_lower_bound_s": None,
        "dimensions": {
            "load_level": "manual_case",
            "layout_class": "independent",
            "buffer_count": 1,
            "relocation_executor_capacity": 1,
            "recoverability_policy": "strict_recoverable",
            "facility_comparison_mode": "fixed_total_positions",
        },
    }


def _valid_manifest() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "run_id": "run-1",
        "scenario_id": "scenario-1",
        "algorithm_id": "rule-baseline",
        "algorithm_version": "0.1.0",
        "git_commit": "a" * 40,
        "git_dirty": False,
        "config_sha256": "b" * 64,
        "input_data_sha256": "c" * 64,
        "random_seed": 7,
        "started_at": "2026-07-28T00:00:00Z",
        "ended_at": "2026-07-28T00:00:01Z",
        "python_version": "3.11.15",
        "dependencies": [{"name": "jsonschema", "version": "4.25.1", "license": "MIT"}],
        "solver": {"name": None, "version": None},
        "operating_system": "Windows",
        "hardware_summary": "C1 contract test",
        "command": "pytest",
        "run_status": "COMPLETED",
    }


def _valid_examples() -> dict[str, object]:
    return {
        "common.schema.json": {},
        "decision.schema.json": minimal_decision_request(),
        "event.schema.json": _valid_event(),
        "layout.schema.json": minimal_layout(),
        "metric.schema.json": _valid_metric(),
        "run-manifest.schema.json": _valid_manifest(),
        "scenario.schema.json": _valid_scenario(),
        "snapshot.schema.json": minimal_snapshot(),
    }


def test_catalog_contains_exactly_the_frozen_eight_schemas(
    schema_catalog: SchemaCatalog,
) -> None:
    assert schema_catalog.names == tuple(sorted(_valid_examples()))


@pytest.mark.parametrize(("schema_name", "instance"), _valid_examples().items())
def test_each_v1_schema_accepts_a_minimal_valid_example(
    schema_catalog: SchemaCatalog,
    schema_name: str,
    instance: object,
) -> None:
    schema_catalog.validate(schema_name, deepcopy(instance))


@pytest.mark.parametrize(
    ("schema_name", "mutation", "pointer"),
    [
        (
            "layout.schema.json",
            lambda value: value.update({"unexpected": True}),
            "/",
        ),
        (
            "snapshot.schema.json",
            lambda value: value.update({"schema_version": "2.0.0"}),
            "/schema_version",
        ),
        (
            "run-manifest.schema.json",
            lambda value: value.update({"started_at": "not-a-time"}),
            "/started_at",
        ),
        (
            "metric.schema.json",
            lambda value: value.update({"unit": "count"}),
            "/unit",
        ),
    ],
)
def test_schema_errors_are_actionable(
    schema_catalog: SchemaCatalog,
    schema_name: str,
    mutation: Any,
    pointer: str,
) -> None:
    instance = deepcopy(_valid_examples()[schema_name])
    mutation(instance)

    with pytest.raises(ContractValidationError) as caught:
        schema_catalog.validate(schema_name, instance)

    assert any(issue.json_pointer == pointer for issue in caught.value.issues)
    constraint_prefix = f"schema:{schema_name}:"
    assert all(issue.constraint_id.startswith(constraint_prefix) for issue in caught.value.issues)
