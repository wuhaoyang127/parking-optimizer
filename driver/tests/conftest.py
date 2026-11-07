"""Shared minimal v1 contract examples for C1 tests."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from parking_opt.contracts.canonical import canonical_sha256
from parking_opt.contracts.schema_validation import SchemaCatalog
from conftest_snapshot import minimal_snapshot

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def schema_catalog() -> SchemaCatalog:
    """Return the frozen v1 schema catalog."""

    return SchemaCatalog(REPO_ROOT / "schemas" / "v1")


def minimal_layout() -> dict[str, Any]:
    """Return a connected two-node layout with one slot and one buffer."""

    return {
        "schema_version": "1.0.0",
        "layout_id": "layout-tiny",
        "coordinate_system": {
            "kind": "local_meters",
            "origin_note": "入口为局部坐标原点",
        },
        "road_nodes": [
            {"road_node_id": "entry", "x_m": 0.0, "y_m": 0.0, "node_kind": "entrance"},
            {
                "road_node_id": "access",
                "x_m": 10.0,
                "y_m": 0.0,
                "node_kind": "position_access",
            },
        ],
        "road_edges": [
            {
                "road_edge_id": "edge-1",
                "from_node_id": "entry",
                "to_node_id": "access",
                "distance_m": 10.0,
                "travel_time_s": 10,
                "directed": True,
                "channel_zone_ids": ["zone-1"],
            }
        ],
        "path_costs": [
            {
                "path_cost_id": "path-entry-access",
                "from_node_id": "entry",
                "to_node_id": "access",
                "distance_m": 10.0,
                "travel_time_s": 10,
                "road_edge_ids": ["edge-1"],
                "channel_zone_ids": ["zone-1"],
            }
        ],
        "slots": [
            {
                "position_id": "slot-1",
                "x_m": 10.0,
                "y_m": 1.0,
                "access_node_id": "access",
                "stack_group_id": "stack-1",
                "depth": 1,
                "channel_zone_ids": ["zone-1"],
            }
        ],
        "buffer_slots": [
            {
                "position_id": "buffer-1",
                "x_m": 10.0,
                "y_m": -1.0,
                "access_node_id": "access",
                "channel_zone_ids": ["zone-1"],
            }
        ],
        "channel_zones": [{"channel_zone_id": "zone-1", "capacity": 1}],
    }


def minimal_approved_config() -> dict[str, Any]:
    """Return the frozen decision configuration fields."""

    return {
        "recoverability_policy": "strict_recoverable",
        "rolling_enabled": False,
        "arrival_wait_capacity": 1,
        "max_arrival_wait_s": 60,
        "max_departure_wait_s": 120,
        "use_soft_departure_information": False,
        "rolling_window_s": 0,
        "optimization_budget_s": 1.0,
        "fallback_target_s": 0.2,
        "minimum_logging_reserve_s": 0.1,
        "max_requests_per_solve": 4,
        "max_positions_per_arrival": 4,
        "max_buffer_matchings_per_departure": 4,
        "max_action_plans_total": 16,
        "max_soft_future_records": 0,
        "buffer_count": 1,
        "relocation_executor_capacity": 1,
        "executor_type": "simulation_only",
        "relocation_setup_s": 5.0,
        "relocation_speed_mps": 1.0,
        "active_buffer_position_ids": ["buffer-1"],
    }


def minimal_decision_request() -> dict[str, Any]:
    """Return a timer-triggered request that contains only visible state."""

    layout = minimal_layout()
    config = minimal_approved_config()
    snapshot = minimal_snapshot()
    return {
        "record_type": "decision_request",
        "schema_version": "1.0.0",
        "request_id": "decision-request-1",
        "algorithm_id": "contract-probe",
        "algorithm_version": "0.1.0",
        "config_sha256": canonical_sha256(config),
        "layout_sha256": canonical_sha256(layout),
        "visible_snapshot_sha256": snapshot["snapshot_content_sha256"],
        "decision_time_s": 0,
        "trigger_event_id": "event-1",
        "trigger_event_type": "DECISION_TIMER_TRIGGERED",
        "trigger_request_id": None,
        "trigger_anonymous_vehicle_id": None,
        "decision_target_s": 0.8,
        "decision_deadline_s": 1.0,
        "approved_config": config,
        "layout": layout,
        "observed_snapshot": snapshot,
    }


@pytest.fixture
def valid_layout() -> dict[str, Any]:
    return deepcopy(minimal_layout())


@pytest.fixture
def valid_snapshot() -> dict[str, Any]:
    return deepcopy(minimal_snapshot())


@pytest.fixture
def valid_decision_request() -> dict[str, Any]:
    return deepcopy(minimal_decision_request())
