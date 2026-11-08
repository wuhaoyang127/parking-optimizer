"""Shared constants and file helpers for experiment runs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from parking_opt.contracts import canonical_json_bytes
from parking_opt.experiments.protocol import ExperimentUnit

ALGORITHM_VERSION = "1.0.0"
ROLLING_BOUNDS = {
    "max_requests_per_solve": 12,
    "max_positions_per_arrival": 8,
    "max_buffer_matchings_per_departure": 4,
    "max_action_plans_total": 64,
    "max_soft_future_records": 20,
}
REQUIRED_RUN_ARTIFACTS = frozenset(
    {
        "layout.json",
        "scenario.json",
        "events.jsonl",
        "decisions.jsonl",
        "metrics.jsonl",
        "requests.jsonl",
        "failures.jsonl",
        "run-manifest.json",
    }
)


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return cast(dict[str, Any], value)


def _write_object(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def _write_jsonl(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    payload = bytearray()
    for record in records:
        payload.extend(canonical_json_bytes(record))
        payload.extend(b"\n")
    path.write_bytes(bytes(payload))


def sha256_file(path: Path) -> str:
    """Hash one exact saved artifact."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def layout_path_for_unit(repo_root: Path, unit: ExperimentUnit) -> Path:
    """Resolve the preregistered fixed-total layout fixture for a unit."""

    family = "mixed-depth" if unit.layout_class == "mixed_depth" else "independent"
    if unit.facility_comparison_mode == "extra_buffer_space":
        filename = f"mixed-depth-extra-buffer-b{unit.buffer_count}-v1.synthetic.json"
    else:
        filename = f"{family}-fixed-total-b{unit.buffer_count}-v1.synthetic.json"
    return repo_root / "data" / "synthetic" / "fixtures" / "c2" / "layouts" / filename


def run_id_for(unit: ExperimentUnit, algorithm_id: str) -> str:
    """Return a stable run identifier for resume and pairing."""

    partition = {
        "development": "dev",
        "formal_core": "formal",
        "formal_extension": "extension",
        "tuning": "tuning",
    }[unit.partition.value]
    layout = {"mixed_depth": "mixed", "independent": "independent"}[unit.layout_class]
    algorithm = {
        "online-rule-v1": "online",
        "rolling-candidate-v1": "rolling",
    }[algorithm_id]
    core_id = (
        f"c6-{partition}-{layout}-{unit.load_level}-b{unit.buffer_count}"
        f"-e{unit.relocation_executor_capacity}-seed{unit.seed}-{algorithm}"
    )
    if unit.experiment_slice == "core":
        return core_id
    cancellation = str(unit.user_cancellation_probability).replace(".", "p")
    budget = (
        "none"
        if unit.experiment_budget_s is None
        else str(unit.experiment_budget_s).replace(".", "p")
    )
    return (
        f"c6-{partition}-{unit.experiment_slice}-{layout}-{unit.load_level}"
        f"-b{unit.buffer_count}-e{unit.relocation_executor_capacity}"
        f"-{unit.departure_information_source}-cancel{cancellation}"
        f"-budget{budget}-seed{unit.seed}-{algorithm}"
    )


from parking_opt.experiments.runner_diagnostics import (  # noqa: E402
    _completed_index_is_valid,
    _decision_diagnostics,
    _failure_records,
    _percentile_95,
    validate_completed_run,
)
from parking_opt.experiments.runner_run import run_experiment  # noqa: E402
