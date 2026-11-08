"""Shared reporting constants and file/validation helpers."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from statistics import fmean
from typing import Any, cast

from parking_opt.contracts.canonical import canonical_json_bytes

BASELINE_ID = "online-rule-v1"
CANDIDATE_ID = "rolling-candidate-v1"
CO_PRIMARY_METRICS = (
    "normal_space_time_utilization",
    "demand_satisfaction_rate",
    "relocation_distance_m",
)
REQUEST_METRICS = ("arrival_wait_s", "departure_wait_s", "departure_delay_s")


def _read_jsonl(path: Path) -> tuple[dict[str, Any], ...]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise TypeError(f"{path}:{line_number} is not a JSON object")
            records.append(cast(dict[str, Any], value))
    return tuple(records)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def _write_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> None:
    payload = bytearray()
    for record in records:
        payload.extend(canonical_json_bytes(record))
        payload.extend(b"\n")
    path.write_bytes(bytes(payload))


def _completed_run_roots(experiment_root: Path) -> tuple[Path, ...]:
    roots = sorted(
        item.parent for item in (experiment_root / "runs").glob("*/*/artifact-index.json")
    )
    if not roots:
        raise ValueError(f"no completed C6 run artifacts found under {experiment_root}")
    return tuple(roots)


def _failed_attempt_rows(experiment_root: Path) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    attempts_root = experiment_root / "attempts"
    if not attempts_root.exists():
        return ()
    for failure_path in sorted(attempts_root.rglob("run-failure.json")):
        failure = json.loads(failure_path.read_text(encoding="utf-8"))
        if not isinstance(failure, dict):
            raise TypeError(f"{failure_path} is not a JSON object")
        relative = failure_path.relative_to(experiment_root).as_posix()
        algorithm_id = (
            failure_path.parent.parent.name
            if failure_path.parent.parent != failure_path.parent
            else "unknown"
        )
        rows.append(
            {
                "run_id": str(failure.get("run_id", "unknown-failed-run")),
                "algorithm_id": algorithm_id,
                "record": {
                    "record_type": "runtime_failure",
                    "attempt_path": relative,
                    **failure,
                },
            }
        )
    return tuple(rows)


def _run_values(
    metric_records: Sequence[Mapping[str, Any]],
) -> dict[str, float]:
    values: dict[str, float] = {}
    request_values: dict[str, list[float]] = defaultdict(list)
    request_counts: dict[str, int] = defaultdict(int)
    censored_counts: dict[str, int] = defaultdict(int)
    for record in metric_records:
        metric_name = str(record["metric_name"])
        value = record["value"]
        if value is None:
            continue
        if record["record_level"] == "request_observation":
            request_counts[metric_name] += 1
            if record["event_observed"] is True:
                request_values[metric_name].append(float(value))
            else:
                censored_counts[metric_name] += 1
        else:
            values[metric_name] = float(value)
    for metric_name in REQUEST_METRICS:
        observed = request_values.get(metric_name, [])
        if observed:
            values[f"{metric_name}_completed_only_mean"] = fmean(observed)
        total = request_counts.get(metric_name, 0)
        if total:
            values[f"{metric_name}_censoring_rate"] = censored_counts[metric_name] / total
    return values


def _validate_pair(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> None:
    equal_fields = (
        "unit_id",
        "random_seed",
        "protocol_sha256",
        "layout_sha256",
        "scenario_sha256",
        "event_truth_sha256",
        "arrival_count",
    )
    mismatched = [field for field in equal_fields if baseline[field] != candidate[field]]
    if mismatched:
        raise ValueError(f"paired run input mismatch: {mismatched}")
    if baseline["algorithm_id"] != BASELINE_ID:
        raise ValueError("paired baseline has the wrong algorithm ID")
    if candidate["algorithm_id"] != CANDIDATE_ID:
        raise ValueError("paired candidate has the wrong algorithm ID")


def _sensitivity_group(index: Mapping[str, Any]) -> str:
    fields = (
        "experiment_slice",
        "layout_class",
        "load_level",
        "buffer_count",
        "relocation_executor_capacity",
        "recoverability_policy",
        "departure_information_source",
        "facility_comparison_mode",
        "user_cancellation_probability",
        "experiment_budget_s",
    )
    return "|".join(f"{field}={index.get(field)}" for field in fields)


from parking_opt.experiments.reporting_csv import _write_failures_csv, _write_metrics_csv  # noqa: E402
from parking_opt.experiments.reporting_generate import generate_report  # noqa: E402
from parking_opt.experiments.reporting_render import _generate_figures, _render_report  # noqa: E402
