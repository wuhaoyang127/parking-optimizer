"""Fail-closed adaptation of anonymous external layout and event data to v1."""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from parking_opt.application.data_adaptation_helpers import _inside
from parking_opt.application.data_adaptation_inspect import _inspect_source
from parking_opt.application.data_adaptation_report import _report_with_failure
from parking_opt.application.data_adaptation_types import (
    _SAFE_FILENAME,
    _SUPPORTED_VERSION,
    AdaptationPolicy,
    AdaptationRejectedError,
    CalibrationGap,
    DataAdaptationReport,
    DataQualityCheck,
    SourceDigest,
)


def validate_data_source(source_path: Path, *, policy: AdaptationPolicy) -> DataAdaptationReport:
    return _inspect_source(source_path, policy).report


def _report_mapping(report: DataAdaptationReport) -> dict[str, Any]:
    return {
        "accepted": report.accepted,
        "source_label": report.source_label,
        "source_kind": report.source_kind,
        "privacy_classification": report.privacy_classification,
        "mode": report.mode,
        "target_schema_version": report.target_schema_version,
        "file_count": report.file_count,
        "total_bytes": report.total_bytes,
        "event_count": report.event_count,
        "mapped_layout_field_count": report.mapped_layout_field_count,
        "mapped_event_field_count": report.mapped_event_field_count,
        "checks": [
            {
                "stage": item.stage,
                "status": item.status,
                "code": item.code,
                "artifact": item.artifact,
                "message": item.message,
                "json_pointer": item.json_pointer,
                "fix_hint": item.fix_hint,
            }
            for item in report.checks
        ],
        "source_digests": [
            {"artifact": item.artifact, "size_bytes": item.size_bytes, "sha256": item.sha256}
            for item in report.source_digests
        ],
        "unrecognized_fields": list(report.unrecognized_fields),
        "calibration_gaps": [
            {"parameter": item.parameter, "status": item.status, "reason": item.reason}
            for item in report.calibration_gaps
        ],
    }


def _jsonable(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(child) for key, child in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(child) for child in value]
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def write_migration_copy(
    source_path: Path,
    output_path: Path,
    *,
    policy: AdaptationPolicy,
) -> DataAdaptationReport:
    preview = _inspect_source(source_path, policy)
    if not preview.report.accepted or preview.layout is None:
        raise AdaptationRejectedError(preview.report)
    spec = {
        "source_kind": preview.report.source_kind,
        "privacy_classification": preview.report.privacy_classification,
        "mode": preview.report.mode,
        "target_schema_version": preview.report.target_schema_version,
    }
    try:
        output_root = policy.output_root.resolve(strict=True)
        source = source_path.resolve(strict=True)
        output_parent = output_path.parent.resolve(strict=True)
        output = output_parent / output_path.name
    except OSError:
        failed = _report_with_failure(
            checks=list(preview.report.checks),
            stage="output",
            code="D5_OUTPUT_BOUNDARY",
            message="output parent must already exist inside the configured output root",
            spec=spec,
        )
        raise AdaptationRejectedError(failed.report) from None
    if not _inside(output, output_root) or _inside(output, source) or output == source or not _SAFE_FILENAME.fullmatch(output.name):
        failed = _report_with_failure(
            checks=list(preview.report.checks),
            stage="output",
            code="D5_OUTPUT_BOUNDARY",
            message="output must be a new safe directory outside the source",
            spec=spec,
        )
        raise AdaptationRejectedError(failed.report)
    if output.exists():
        failed = _report_with_failure(
            checks=list(preview.report.checks),
            stage="output",
            code="D5_OUTPUT_EXISTS",
            message="output already exists; in-place overwrite is forbidden",
            spec=spec,
        )
        raise AdaptationRejectedError(failed.report)

    temp_dir = Path(tempfile.mkdtemp(prefix=".d5-adapt-", dir=output_parent))
    try:
        _write_json(temp_dir / "layout.v1.json", preview.layout)
        if preview.events:
            with (temp_dir / "events.v1.jsonl").open("x", encoding="utf-8", newline="\n") as handle:
                for event in preview.events:
                    handle.write(
                        json.dumps(_jsonable(event), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                        + "\n"
                    )
        _write_json(temp_dir / "data-quality-report.json", _report_mapping(preview.report))
        _write_json(
            temp_dir / "source-provenance.json",
            {
                "schema_version": _SUPPORTED_VERSION,
                "source_kind": preview.report.source_kind,
                "privacy_classification": preview.report.privacy_classification,
                "mode": preview.report.mode,
                "target_schema_version": preview.report.target_schema_version,
                "source_sha256": {item.artifact: item.sha256 for item in preview.report.source_digests},
                "raw_source_preserved": True,
                "calibration_status": "not_completed",
            },
        )
        temp_dir.rename(output)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    return preview.report


__all__ = [
    "AdaptationPolicy",
    "AdaptationRejectedError",
    "CalibrationGap",
    "DataAdaptationReport",
    "DataQualityCheck",
    "SourceDigest",
    "validate_data_source",
    "write_migration_copy",
]
