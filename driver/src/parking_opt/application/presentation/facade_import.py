"""Fail-closed import validation for demo bundles."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from parking_opt.application.presentation.facade import (
    _EXPECTED_FILES,
    _JSON_FILES,
    _JSONL_SCHEMAS,
    _OTHER_JSONL,
    _check,
    _contains_pii_key,
    _identity_matches,
    _inside,
    _read_json_object,
    _read_jsonl,
    _safe_label,
    _sha256_file,
    _validate_event_order,
    _SyntaxIssue,
)
from parking_opt.application.presentation.models import (
    FileDigest,
    ImportPolicy,
    ImportValidationReport,
    ValidatedDemoBundle,
    ValidationCheck,
)
from parking_opt.contracts.errors import ContractValidationError
from parking_opt.contracts.schema_validation import SchemaCatalog
from parking_opt.contracts.semantic_validation import (
    validate_layout_semantics,
    validate_scenario_semantics,
)
from parking_opt.domain.records import freeze_mapping
from parking_opt.domain.transitions import apply_event
from parking_opt.experiments.runner import validate_completed_run
from parking_opt.layout.model import layout_from_mapping
from parking_opt.layout.state_adapter import initial_state_from_layout


def _load_validated(
    path: Path,
    policy: ImportPolicy,
) -> tuple[ImportValidationReport, ValidatedDemoBundle | None]:
    checks: list[ValidationCheck] = []
    source_label = _safe_label(path)
    try:
        allowed_root = policy.allowed_root.resolve(strict=True)
        source = path.resolve(strict=True)
    except OSError:
        checks.append(_check("path", "failed", "D1_PATH_NOT_FOUND", "selected bundle does not exist"))
        return ImportValidationReport(False, source_label, 0, 0, 0, tuple(checks)), None
    if not source.is_dir() or not _inside(source, allowed_root):
        checks.append(_check("path", "failed", "D1_PATH_BOUNDARY", "selected bundle must be a directory inside the allowed root"))
        return ImportValidationReport(False, source_label, 0, 0, 0, tuple(checks)), None
    checks.append(_check("path", "passed", "D1_PATH_OK", "path boundary accepted"))
    try:
        entries = tuple(source.iterdir())
    except OSError:
        checks.append(_check("path", "failed", "D1_PATH_UNREADABLE", "bundle directory is unreadable"))
        return ImportValidationReport(False, source_label, 0, 0, 0, tuple(checks)), None
    if (not policy.allow_symlinks and any(item.is_symlink() for item in entries)) or any(
        not item.is_file() for item in entries
    ):
        checks.append(_check("path", "failed", "D1_UNSAFE_ENTRY", "bundle may contain only regular non-symlink files"))
        return ImportValidationReport(False, source_label, 0, 0, 0, tuple(checks)), None
    names = {item.name for item in entries}
    if names != _EXPECTED_FILES:
        checks.append(_check("shape", "failed", "D1_ARTIFACT_SET", "bundle artifact set is incomplete or contains unsupported files"))
        return ImportValidationReport(False, source_label, len(entries), 0, 0, tuple(checks)), None
    sizes = {item.name: item.stat().st_size for item in entries}
    total_bytes = sum(sizes.values())
    if any(size > policy.max_file_bytes for size in sizes.values()) or (total_bytes > policy.max_total_bytes):
        checks.append(_check("limits", "failed", "D1_SIZE_LIMIT", "bundle exceeds the configured byte budget"))
        return ImportValidationReport(False, source_label, len(entries), total_bytes, 0, tuple(checks)), None
    checks.append(_check("limits", "passed", "D1_SIZE_OK", "byte budget accepted"))

    objects: dict[str, dict[str, Any]] = {}
    streams: dict[str, list[dict[str, Any]]] = {}
    record_count = 0
    try:
        for name in sorted(_JSON_FILES):
            objects[name] = _read_json_object(source / name)
        for name in sorted(_JSONL_SCHEMAS.keys() | _OTHER_JSONL):
            remaining = policy.max_records - record_count
            records = _read_jsonl(source / name, remaining)
            streams[name] = records
            record_count += len(records)
    except _SyntaxIssue as exc:
        checks.append(_check("syntax", "failed", "D1_JSON_SYNTAX", str(exc), exc.artifact, fix_hint="repair the named UTF-8 JSON/JSONL artifact and export the bundle again"))
        return ImportValidationReport(False, source_label, len(entries), total_bytes, record_count, tuple(checks)), None
    except OverflowError:
        checks.append(_check("limits", "failed", "D1_RECORD_LIMIT", "record budget exceeded"))
        return ImportValidationReport(False, source_label, len(entries), total_bytes, record_count, tuple(checks)), None
    checks.append(_check("syntax", "passed", "D1_JSON_OK", "JSON syntax accepted"))

    all_values: tuple[object, ...] = (*objects.values(), *(streams.values()))
    if any(_contains_pii_key(item) for item in all_values):
        checks.append(_check("privacy", "failed", "D1_PII_FIELD", "direct identifier or re-identification mapping field detected"))
        return ImportValidationReport(False, source_label, len(entries), total_bytes, record_count, tuple(checks)), None
    checks.append(_check("privacy", "passed", "D1_PRIVACY_OK", "PII field scan accepted"))

    index = objects["artifact-index.json"]
    if index.get("schema_version") != "1.0.0":
        checks.append(_check("schema", "failed", "D1_UNKNOWN_SCHEMA_VERSION", "artifact index schema version is unsupported", "artifact-index.json"))
        return ImportValidationReport(False, source_label, len(entries), total_bytes, record_count, tuple(checks)), None
    schema_artifact: str | None = None
    try:
        catalog = SchemaCatalog(policy.schema_dir)
        for schema_artifact, schema_name in (
            ("layout.json", "layout.schema.json"),
            ("scenario.json", "scenario.schema.json"),
            ("run-manifest.json", "run-manifest.schema.json"),
        ):
            catalog.validate(schema_name, objects[schema_artifact])
        for schema_artifact, schema_name in _JSONL_SCHEMAS.items():
            for record in streams[schema_artifact]:
                catalog.validate(schema_name, record)
    except ContractValidationError as exc:
        issue = exc.issues[0]
        checks.append(_check("schema", "failed", "D1_SCHEMA_REJECTED", "an artifact does not satisfy the frozen v1 schema", schema_artifact, json_pointer=issue.json_pointer, constraint_id=issue.constraint_id, fix_hint="repair the named field against schemas/v1 and export a complete bundle"))
        return ImportValidationReport(False, source_label, len(entries), total_bytes, record_count, tuple(checks)), None
    except (KeyError, OSError, TypeError, ValueError):
        checks.append(_check("schema", "failed", "D1_SCHEMA_REJECTED", "the frozen v1 schema catalog or artifact structure is invalid", schema_artifact, fix_hint="restore the approved schemas/v1 catalog and export the bundle again"))
        return ImportValidationReport(False, source_label, len(entries), total_bytes, record_count, tuple(checks)), None
    checks.append(_check("schema", "passed", "D1_SCHEMA_OK", "frozen v1 schemas accepted"))

    try:
        validate_completed_run(source, schema_catalog=catalog)
    except (OSError, TypeError, ValueError):
        checks.append(_check("integrity", "failed", "D1_HASH_MISMATCH", "artifact set is missing, altered, or inconsistent with its saved hashes"))
        return ImportValidationReport(False, source_label, len(entries), total_bytes, record_count, tuple(checks)), None
    checks.append(_check("integrity", "passed", "D1_HASH_OK", "saved artifact hashes accepted"))

    layout_mapping = objects["layout.json"]
    scenario = objects["scenario.json"]
    manifest = objects["run-manifest.json"]
    events = streams["events.jsonl"]
    decisions = streams["decisions.jsonl"]
    metrics = streams["metrics.jsonl"]
    try:
        validate_layout_semantics(layout_mapping)
        validate_scenario_semantics(scenario, layout_mapping)
        _validate_event_order(events)
        if not _identity_matches(events, manifest=manifest, include_run=True, include_algorithm=False):
            raise ValueError("event identity mismatch")
        if not _identity_matches(decisions, manifest=manifest, include_run=False, include_algorithm=True):
            raise ValueError("decision identity mismatch")
        if not _identity_matches(metrics, manifest=manifest, include_run=True, include_algorithm=True):
            raise ValueError("metric identity mismatch")
        decision_ids = [item["decision_id"] for item in decisions]
        if len(decision_ids) != len(set(decision_ids)):
            raise ValueError("decision IDs must be unique")
        layout = layout_from_mapping(layout_mapping)
        config = scenario["config"]
        initial_state = initial_state_from_layout(
            layout,
            run_id=manifest["run_id"],
            scenario_id=manifest["scenario_id"],
            active_buffer_position_ids=tuple(config["active_buffer_position_ids"]),
            relocation_executor_capacity=config["relocation_executor_capacity"],
            arrival_wait_capacity=config["arrival_wait_capacity"],
            max_arrival_wait_s=config["max_arrival_wait_s"],
        )
        state = initial_state
        for event in events:
            state = apply_event(state, event)
    except (ContractValidationError, KeyError, TypeError, ValueError):
        checks.append(_check("semantics", "failed", "D1_SEMANTIC_REJECTED", "cross-record references, order, or exact replay are invalid"))
        return ImportValidationReport(False, source_label, len(entries), total_bytes, record_count, tuple(checks)), None
    checks.append(_check("semantics", "passed", "D1_REPLAY_OK", "semantic checks and exact replay accepted"))

    digests = tuple(FileDigest(name, sizes[name], _sha256_file(source / name)) for name in sorted(names))
    bundle = ValidatedDemoBundle(
        run_id=manifest["run_id"],
        scenario_id=manifest["scenario_id"],
        algorithm_id=manifest["algorithm_id"],
        algorithm_version=manifest["algorithm_version"],
        source_kind=scenario["data_source"],
        purpose=scenario["purpose"],
        layout=layout,
        manifest=freeze_mapping(manifest),
        file_digests=digests,
        event_count=len(events),
        decision_count=len(decisions),
        decision_ids=tuple(item["decision_id"] for item in decisions),
        metric_count=len(metrics),
        _initial_state=initial_state,
        _events=tuple(freeze_mapping(item) for item in events),
        _decisions=tuple(freeze_mapping(item) for item in decisions),
        _metrics=tuple(freeze_mapping(item) for item in metrics),
    )
    report = ImportValidationReport(True, source_label, len(entries), total_bytes, record_count, tuple(checks))
    return report, bundle
