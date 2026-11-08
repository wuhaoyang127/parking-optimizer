"""Report construction helpers for anonymous data adaptation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from parking_opt.application.data_adaptation_helpers import _check
from parking_opt.application.data_adaptation_types import (
    _SUPPORTED_VERSION,
    DataAdaptationReport,
    DataQualityCheck,
    SourceDigest,
)


@dataclass(frozen=True, slots=True)
class _AdaptationPreview:
    report: DataAdaptationReport
    layout: Mapping[str, Any] | None
    events: tuple[Mapping[str, Any], ...]


def _empty_report(checks: Sequence[DataQualityCheck]) -> DataAdaptationReport:
    return DataAdaptationReport(
        accepted=False,
        source_label="selected-import-package",
        source_kind="unknown",
        privacy_classification="unknown",
        mode="unknown",
        target_schema_version=_SUPPORTED_VERSION,
        file_count=0,
        total_bytes=0,
        event_count=0,
        mapped_layout_field_count=0,
        mapped_event_field_count=0,
        checks=tuple(checks),
        source_digests=(),
        unrecognized_fields=(),
        calibration_gaps=(),
    )


def _report_with_failure(
    *,
    checks: list[DataQualityCheck],
    code: str,
    stage: str,
    message: str,
    artifact: str | None = None,
    file_count: int = 0,
    total_bytes: int = 0,
    event_count: int = 0,
    digests: tuple[SourceDigest, ...] = (),
    spec: Mapping[str, Any] | None = None,
    layout_count: int = 0,
    event_count_mapped: int = 0,
    fix_hint: str | None = None,
    json_pointer: str | None = None,
) -> _AdaptationPreview:
    checks.append(
        _check(stage, "failed", code, message, artifact, json_pointer=json_pointer, fix_hint=fix_hint)
    )
    report = DataAdaptationReport(
        accepted=False,
        source_label="selected-import-package",
        source_kind=str(spec.get("source_kind", "unknown")) if spec else "unknown",
        privacy_classification=str(spec.get("privacy_classification", "unknown")) if spec else "unknown",
        mode=str(spec.get("mode", "unknown")) if spec else "unknown",
        target_schema_version=str(spec.get("target_schema_version", _SUPPORTED_VERSION)) if spec else _SUPPORTED_VERSION,
        file_count=file_count,
        total_bytes=total_bytes,
        event_count=event_count,
        mapped_layout_field_count=layout_count,
        mapped_event_field_count=event_count_mapped,
        checks=tuple(checks),
        source_digests=digests,
        unrecognized_fields=(),
        calibration_gaps=(),
    )
    return _AdaptationPreview(report, None, ())
