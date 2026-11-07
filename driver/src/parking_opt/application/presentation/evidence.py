"""Fail-closed D4 loading of saved C6 comparison evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from parking_opt.application.presentation.models import ComparisonRunView

_EXPECTED_FILES = frozenset(
    {"evidence-metadata.json", "paired-statistics.json", "report-index.json"}
)
_PAIR_FIELDS = (
    "unit_id",
    "random_seed",
    "protocol_sha256",
    "layout_sha256",
    "scenario_sha256",
    "event_truth_sha256",
    "arrival_count",
)
_BASELINE_ID = "online-rule-v1"
_CANDIDATE_ID = "rolling-candidate-v1"
_UNIT_BY_METRIC = {
    "occupancy_rate": "ratio",
    "normal_space_time_utilization": "ratio",
    "facility_position_space_time_utilization": "ratio",
    "buffer_utilization": "ratio",
    "demand_satisfaction_rate": "ratio",
    "throughput_per_hour": "per_hour",
    "relocation_count": "count",
    "relocation_distance_m": "meter",
    "executor_utilization": "ratio",
    "channel_zone_utilization": "ratio",
    "fallback_count": "count",
    "manual_intervention_count": "count",
    "sla_violation_count": "count",
    "failed_action_count": "count",
}


class ComparisonEvidenceError(ValueError):
    """Raised when saved comparison evidence is incomplete or inconsistent."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ComparisonEvidenceError(f"D4_SIZE_LIMIT: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ComparisonEvidenceError(f"D4_JSON_SYNTAX: {path.name}") from exc
    if not isinstance(value, dict):
        raise ComparisonEvidenceError(f"D4_JSON_OBJECT_REQUIRED: {path.name}")
    return cast(dict[str, Any], value)


def _require_fields(value: Mapping[str, Any], fields: Sequence[str], *, label: str) -> None:
    missing = [field for field in fields if field not in value]
    if missing:
        raise ComparisonEvidenceError(f"D4_MISSING_FIELDS: {label}: {missing}")


def _resolve_evidence_root(path: Path, allowed_root: Path) -> Path:
    root = allowed_root.resolve(strict=True)
    candidate = path.resolve(strict=True)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ComparisonEvidenceError("D4_PATH_BOUNDARY") from exc
    if candidate.is_symlink() or any(parent.is_symlink() for parent in candidate.parents):
        raise ComparisonEvidenceError("D4_SYMLINK_REJECTED")
    if not candidate.is_dir():
        raise ComparisonEvidenceError("D4_DIRECTORY_REQUIRED")
    files = frozenset(item.name for item in candidate.iterdir() if item.is_file())
    if files != _EXPECTED_FILES:
        raise ComparisonEvidenceError(
            f"D4_ARTIFACT_SET: expected {sorted(_EXPECTED_FILES)}, found {sorted(files)}"
        )
    return candidate


def _run_view(value: Mapping[str, Any]) -> ComparisonRunView:
    _require_fields(
        value,
        (
            *_PAIR_FIELDS,
            "run_id",
            "scenario_id",
            "algorithm_id",
            "algorithm_version",
            "git_commit",
            "run_status",
            "input_data_sha256",
            "config_sha256",
            "source_artifact_index_sha256",
            "fallback_count",
            "fallback_rate",
            "pending_request_count_at_horizon",
            "hard_deadline_violation_count",
            "state_invariant_violation_count",
        ),
        label="comparison run",
    )
    fallback_rate = float(value["fallback_rate"])
    if not 0.0 <= fallback_rate <= 1.0:
        raise ComparisonEvidenceError("D4_FALLBACK_RATE_RANGE")
    return ComparisonRunView(
        run_id=cast(str, value["run_id"]),
        scenario_id=cast(str, value["scenario_id"]),
        algorithm_id=cast(str, value["algorithm_id"]),
        algorithm_version=cast(str, value["algorithm_version"]),
        git_commit=cast(str, value["git_commit"]),
        random_seed=int(value["random_seed"]),
        run_status=cast(str, value["run_status"]),
        input_data_sha256=cast(str, value["input_data_sha256"]),
        config_sha256=cast(str, value["config_sha256"]),
        fallback_count=int(value["fallback_count"]),
        fallback_rate=fallback_rate,
        pending_request_count_at_horizon=int(value["pending_request_count_at_horizon"]),
        hard_deadline_violation_count=int(value["hard_deadline_violation_count"]),
        state_invariant_violation_count=int(value["state_invariant_violation_count"]),
    )


def _metric_unit(metric_name: str) -> str:
    if metric_name.endswith("_completed_only_mean"):
        return "second"
    if metric_name.endswith("_censoring_rate"):
        return "ratio"
    try:
        return _UNIT_BY_METRIC[metric_name]
    except KeyError as exc:
        raise ComparisonEvidenceError(f"D4_UNKNOWN_METRIC: {metric_name}") from exc


from parking_opt.application.presentation.evidence_loader import load_comparison_evidence  # noqa: E402
