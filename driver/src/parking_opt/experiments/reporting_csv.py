"""CSV emission for experiment reporting."""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def _write_metrics_csv(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    fieldnames = (
        "run_id",
        "scenario_id",
        "algorithm_id",
        "record_level",
        "subject_vehicle_id",
        "subject_request_id",
        "metric_name",
        "value",
        "unit",
        "event_observed",
        "pending_at_horizon",
        "observed_wait_lower_bound_s",
        "dimensions_json",
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    **{name: record.get(name) for name in fieldnames[:-1]},
                    "dimensions_json": json.dumps(
                        record["dimensions"],
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                }
            )


def _write_failures_csv(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = ("run_id", "algorithm_id", "record_json")
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "run_id": row["run_id"],
                    "algorithm_id": row["algorithm_id"],
                    "record_json": json.dumps(
                        row["record"],
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                }
            )
