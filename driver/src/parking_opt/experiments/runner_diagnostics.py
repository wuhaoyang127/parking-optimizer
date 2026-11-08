"""Diagnostic, failure-record, and completed-run validation helpers."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from parking_opt.contracts import SchemaCatalog, canonical_sha256
from parking_opt.experiments.runner import (
    REQUIRED_RUN_ARTIFACTS,
    _read_object,
    sha256_file,
)

_FAILURE_EVENT_TYPES = {
    "ACTION_FAILED_KNOWN_POSITION",
    "ACTION_FAILED_POSITION_UNKNOWN",
    "MANUAL_INTERVENTION_REQUESTED",
}


def _percentile_95(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, int(0.95 * len(ordered)) - 1))]


def _decision_diagnostics(
    decisions: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    *,
    deadline_s: float,
) -> dict[str, Any]:
    timings = [float(item["timing"]["end_to_end_s"]) for item in decisions]
    fallback_decisions = [item for item in decisions if item["fallback_record"] is not None]
    fallback_decision_ids = Counter(str(item["decision_id"]) for item in fallback_decisions)
    logged_fallback_ids = Counter(
        str(item["payload"].get("decision_id"))
        for item in events
        if item["event_type"] == "FALLBACK_USED"
    )
    unlogged_fallbacks = sum((fallback_decision_ids - logged_fallback_ids).values())
    orphan_fallback_logs = sum((logged_fallback_ids - fallback_decision_ids).values())
    statuses = Counter(str(item["solver_status"]) for item in decisions)
    reasons = Counter(
        str(item["fallback_record"]["reason"])
        for item in fallback_decisions
        if item["fallback_record"] is not None
    )
    return {
        "decision_count": len(decisions),
        "solver_status_counts": dict(sorted(statuses.items())),
        "fallback_reason_counts": dict(sorted(reasons.items())),
        "fallback_count": len(fallback_decisions),
        "fallback_rate": len(fallback_decisions) / len(decisions) if decisions else 0.0,
        "logged_fallback_count": sum(logged_fallback_ids.values()),
        "unlogged_fallback_count": unlogged_fallbacks,
        "orphan_fallback_log_count": orphan_fallback_logs,
        "fallback_log_mismatch_count": unlogged_fallbacks + orphan_fallback_logs,
        "hard_deadline_violation_count": sum(value > deadline_s for value in timings),
        "decision_end_to_end_s_max": max(timings, default=0.0),
        "decision_end_to_end_s_p95": _percentile_95(timings),
    }


def _failure_records(
    decisions: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    records: list[dict[str, Any]] = []
    for decision in decisions:
        fallback = decision["fallback_record"]
        if fallback is not None:
            records.append(
                {
                    "record_type": "fallback",
                    "decision_id": decision["decision_id"],
                    "reason": fallback["reason"],
                    "original_solver_status": fallback["original_solver_status"],
                    "used_strategy": fallback["used_strategy"],
                    "elapsed_s": fallback["elapsed_s"],
                }
            )
    for event in events:
        if event["event_type"] in _FAILURE_EVENT_TYPES:
            records.append(
                {
                    "record_type": "event_failure",
                    "event_id": event["event_id"],
                    "event_type": event["event_type"],
                    "sim_time_s": event["sim_time_s"],
                    "anonymous_vehicle_id": event["anonymous_vehicle_id"],
                    "payload": event["payload"],
                }
            )
    return tuple(records)


def _completed_index_is_valid(
    run_root: Path,
    *,
    schema_catalog: SchemaCatalog | None = None,
) -> bool:
    index_path = run_root / "artifact-index.json"
    if not index_path.exists():
        return False
    try:
        index = _read_object(index_path)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    if index.get("run_status") != "COMPLETED":
        return False
    hashes = index.get("artifact_sha256")
    if not isinstance(hashes, dict):
        return False
    if set(hashes) != REQUIRED_RUN_ARTIFACTS:
        return False
    if not all(
        isinstance(relative, str)
        and isinstance(expected, str)
        and len(expected) == 64
        and (path := run_root / relative).is_file()
        and path.parent == run_root
        and sha256_file(path) == expected
        for relative, expected in hashes.items()
    ):
        return False
    try:
        manifest = _read_object(run_root / "run-manifest.json")
        if schema_catalog is not None:
            schema_catalog.validate("run-manifest.schema.json", manifest)
        if (
            manifest.get("run_status") != "COMPLETED"
            or manifest.get("run_id") != index.get("run_id")
            or manifest.get("algorithm_id") != index.get("algorithm_id")
            or manifest.get("algorithm_version") != index.get("algorithm_version")
            or manifest.get("random_seed") != index.get("random_seed")
        ):
            return False
        scenario = _read_object(run_root / "scenario.json")
        layout = _read_object(run_root / "layout.json")
        if schema_catalog is not None:
            schema_catalog.validate("scenario.schema.json", scenario)
            schema_catalog.validate("layout.schema.json", layout)
        if (
            scenario.get("scenario_id") != manifest.get("scenario_id")
            or scenario.get("layout_id") != layout.get("layout_id")
            or canonical_sha256(scenario) != index.get("scenario_sha256")
            or canonical_sha256(layout) != index.get("layout_sha256")
        ):
            return False
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return False
    return True


def validate_completed_run(
    run_root: Path,
    *,
    schema_catalog: SchemaCatalog | None = None,
) -> dict[str, Any]:
    """Validate every indexed byte before a run is reused."""

    if not _completed_index_is_valid(run_root, schema_catalog=schema_catalog):
        raise ValueError(f"completed run is missing or has a hash mismatch: {run_root}")
    return _read_object(run_root / "artifact-index.json")
