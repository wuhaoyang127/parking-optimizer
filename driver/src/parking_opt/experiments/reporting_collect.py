"""Collect and pair completed runs for experiment reporting."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from parking_opt.experiments.protocol import (
    core_experiment_units,
    sensitivity_experiment_units,
)
from parking_opt.experiments.reporting import (
    BASELINE_ID,
    CANDIDATE_ID,
    _completed_run_roots,
    _failed_attempt_rows,
    _read_jsonl,
    _validate_pair,
)
from parking_opt.experiments.runner import validate_completed_run


def collect_completed_runs(experiment_root: Path) -> dict[str, Any]:
    """Read validated indexes, metrics, and failures from every completed run."""

    indexes: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    metrics_by_run: dict[str, tuple[dict[str, Any], ...]] = {}
    all_metrics: list[dict[str, Any]] = []
    all_failures: list[dict[str, Any]] = list(_failed_attempt_rows(experiment_root))
    for run_root in _completed_run_roots(experiment_root):
        index = validate_completed_run(run_root)
        unit_id = str(index["unit_id"])
        algorithm_id = str(index["algorithm_id"])
        if algorithm_id in indexes[unit_id]:
            raise ValueError(f"duplicate algorithm run for unit {unit_id}: {algorithm_id}")
        indexes[unit_id][algorithm_id] = index
        run_metrics = _read_jsonl(run_root / "metrics.jsonl")
        metrics_by_run[str(index["run_id"])] = run_metrics
        all_metrics.extend(run_metrics)
        for failure in _read_jsonl(run_root / "failures.jsonl"):
            all_failures.append(
                {"run_id": index["run_id"], "algorithm_id": algorithm_id, "record": failure}
            )
    return {
        "indexes": indexes,
        "metrics_by_run": metrics_by_run,
        "all_metrics": all_metrics,
        "all_failures": all_failures,
    }


def build_pairs(indexes: dict[str, dict[str, dict[str, Any]]], protocol: Mapping[str, Any]) -> dict[str, Any]:
    """Pair baseline and candidate runs and classify incomplete or rolling-only units."""

    complete_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    rolling_only_units: list[dict[str, Any]] = []
    incomplete_units: list[str] = []
    for unit_id, algorithms in sorted(indexes.items()):
        slice_name = str(next(iter(algorithms.values())).get("experiment_slice", "core"))
        if slice_name == "budget":
            if CANDIDATE_ID not in algorithms:
                incomplete_units.append(unit_id)
            else:
                rolling_only_units.append(algorithms[CANDIDATE_ID])
            continue
        if BASELINE_ID not in algorithms or CANDIDATE_ID not in algorithms:
            incomplete_units.append(unit_id)
            continue
        baseline = algorithms[BASELINE_ID]
        candidate = algorithms[CANDIDATE_ID]
        _validate_pair(baseline, candidate)
        complete_pairs.append((baseline, candidate))
    observed_formal_ids = {
        unit_id
        for unit_id, algorithms in indexes.items()
        if any(index["seed_partition"] == "formal_core" for index in algorithms.values())
    }
    expected_formal_ids: set[str] = set()
    if observed_formal_ids:
        expected_formal_ids = {unit.unit_id for unit in core_experiment_units(protocol)}
        unknown = observed_formal_ids - expected_formal_ids
        if unknown:
            raise ValueError(f"formal runs contain units outside the frozen core matrix: {sorted(unknown)}")
        incomplete_units = sorted(set(incomplete_units) | (expected_formal_ids - observed_formal_ids))
    observed_extension_ids = {
        unit_id
        for unit_id, algorithms in indexes.items()
        if any(index["seed_partition"] == "formal_extension" for index in algorithms.values())
    }
    expected_extension_ids: set[str] = set()
    if observed_extension_ids:
        expected_extension_ids = {unit.unit_id for unit in sensitivity_experiment_units(protocol)}
        unknown = observed_extension_ids - expected_extension_ids
        if unknown:
            raise ValueError(
                "formal extension contains units outside the sensitivity plan: " f"{sorted(unknown)}"
            )
        incomplete_units = sorted(
            set(incomplete_units) | (expected_extension_ids - observed_extension_ids)
        )
    return {
        "complete_pairs": complete_pairs,
        "rolling_only_units": rolling_only_units,
        "incomplete_units": incomplete_units,
        "observed_formal_ids": observed_formal_ids,
        "observed_extension_ids": observed_extension_ids,
        "expected_formal_ids": expected_formal_ids,
        "expected_extension_ids": expected_extension_ids,
    }
