"""Fail-closed loading, replay, audit, and metric views for the future UI."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from parking_opt.application.presentation.facade_import import _load_validated
from parking_opt.application.presentation.facade_replay import build_replay_index, frame_at
from parking_opt.application.presentation.facade_timeline import build_replay_timeline
from parking_opt.application.presentation.facade_views import decision_audit, metric_summary
from parking_opt.application.presentation.models import (
    ImportPolicy,
    ImportRejectedError,
    ImportValidationReport,
    ValidatedDemoBundle,
    ValidationCheck,
)
from parking_opt.experiments.runner import REQUIRED_RUN_ARTIFACTS

_INDEX_NAME = "artifact-index.json"
_EXPECTED_FILES = frozenset({*REQUIRED_RUN_ARTIFACTS, _INDEX_NAME})
_JSON_FILES = frozenset({"layout.json", "scenario.json", "run-manifest.json", "artifact-index.json"})
_JSONL_SCHEMAS = {
    "events.jsonl": "event.schema.json",
    "decisions.jsonl": "decision.schema.json",
    "metrics.jsonl": "metric.schema.json",
}
_OTHER_JSONL = frozenset({"requests.jsonl", "failures.jsonl"})
_PII_FIELD_NAMES = frozenset(
    {
        "contact",
        "deidentification_map",
        "email",
        "full_name",
        "government_id",
        "id_card",
        "license_plate",
        "original_vehicle_id",
        "phone",
        "pii_mapping",
        "plate_number",
        "telephone",
        "vehicle_plate",
    }
)


class _SyntaxIssue(ValueError):
    def __init__(self, artifact: str, message: str) -> None:
        self.artifact = artifact
        super().__init__(message)


def _check(
    stage: str,
    status: str,
    code: str,
    message: str,
    artifact: str | None = None,
    *,
    json_pointer: str | None = None,
    constraint_id: str | None = None,
    fix_hint: str | None = None,
) -> ValidationCheck:
    return ValidationCheck(stage, status, code, artifact, message, json_pointer, constraint_id, fix_hint)


def _safe_label(path: Path) -> str:
    return path.name or "selected-bundle"


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _contains_pii_key(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(
            str(key).casefold() in _PII_FIELD_NAMES or _contains_pii_key(child)
            for key, child in value.items()
        )
    if isinstance(value, list | tuple):
        return any(_contains_pii_key(child) for child in value)
    return False


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeError as exc:
        raise _SyntaxIssue(path.name, "artifact is not valid UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise _SyntaxIssue(path.name, f"invalid JSON at line {exc.lineno}, column {exc.colno}") from exc
    if not isinstance(value, dict):
        raise _SyntaxIssue(path.name, "JSON root must be an object")
    return cast(dict[str, Any], value)


def _read_jsonl(path: Path, max_records: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                if len(records) >= max_records:
                    raise OverflowError("record limit exceeded")
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise _SyntaxIssue(path.name, f"invalid JSONL at line {line_number}, column {exc.colno}") from exc
                if not isinstance(value, dict):
                    raise _SyntaxIssue(path.name, f"JSONL line {line_number} must be an object")
                records.append(cast(dict[str, Any], value))
    except UnicodeError as exc:
        raise _SyntaxIssue(path.name, "artifact is not valid UTF-8") from exc
    return records


def _identity_matches(
    records: Sequence[Mapping[str, Any]],
    *,
    manifest: Mapping[str, Any],
    include_run: bool,
    include_algorithm: bool,
) -> bool:
    for record in records:
        if include_run and (
            record.get("run_id") != manifest["run_id"]
            or record.get("scenario_id") != manifest["scenario_id"]
        ):
            return False
        if include_algorithm and (
            record.get("algorithm_id") != manifest["algorithm_id"]
            or record.get("algorithm_version") != manifest["algorithm_version"]
        ):
            return False
    return True


def _validate_event_order(events: Sequence[Mapping[str, Any]]) -> None:
    sequences = [item["sequence_no"] for item in events]
    if sequences != list(range(1, len(events) + 1)):
        raise ValueError("event sequence must be contiguous from one")
    event_ids = [item["event_id"] for item in events]
    if len(event_ids) != len(set(event_ids)):
        raise ValueError("event IDs must be unique")


def validate_import(path: Path, *, policy: ImportPolicy) -> ImportValidationReport:
    report, _ = _load_validated(path, policy)
    return report


def load_demo_bundle(path: Path, *, policy: ImportPolicy) -> ValidatedDemoBundle:
    report, bundle = _load_validated(path, policy)
    if bundle is None:
        raise ImportRejectedError(report)
    return bundle
