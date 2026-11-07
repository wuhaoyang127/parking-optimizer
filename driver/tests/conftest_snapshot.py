"""Shared minimal snapshot example for C1 tests."""
from __future__ import annotations

from typing import Any

from parking_opt.contracts.canonical import snapshot_content_sha256


def minimal_snapshot() -> dict[str, Any]:
    """Return an empty but structurally complete observed snapshot."""

    snapshot: dict[str, Any] = {
        "schema_version": "1.0.0",
        "snapshot_id": "snapshot-1",
        "snapshot_content_sha256": "0" * 64,
        "run_id": "run-1",
        "scenario_id": "scenario-1",
        "layout_id": "layout-tiny",
        "decision_time_s": 0,
        "vehicles": [],
        "positions": [
            {
                "position_id": "slot-1",
                "position_kind": "normal",
                "physically_available": True,
                "assignable": True,
                "planned_closure": False,
                "occupant_vehicle_id": None,
            },
            {
                "position_id": "buffer-1",
                "position_kind": "buffer",
                "physically_available": True,
                "assignable": False,
                "planned_closure": False,
                "occupant_vehicle_id": None,
            },
        ],
        "reservations": [],
        "locks": [],
        "actions": [],
        "transactions": [],
        "executor_resource": {"capacity": 1, "used": 0, "active_action_ids": []},
        "channel_zone_resources": [
            {
                "channel_zone_id": "zone-1",
                "capacity": 1,
                "used": 0,
                "active_action_ids": [],
            }
        ],
        "pending_requests": [],
    }
    snapshot["snapshot_content_sha256"] = snapshot_content_sha256(snapshot)
    return snapshot
