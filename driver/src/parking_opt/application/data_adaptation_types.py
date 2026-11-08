"""Type and constant definitions for anonymous data adaptation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_SPEC_NAME = "import-spec.json"
_MAPPING_NAME = "field-mapping.json"
_LAYOUT_NAME = "layout-source.json"
_EVENTS_NAME = "events-source.jsonl"
_SUPPORTED_VERSION = "1.0.0"
_SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_TIMEZONE = re.compile(r"^(?:UTC|[+-](?:0\d|1[0-4]):[0-5]\d)$")
_EMAIL = re.compile(r"(?i)\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b")
_PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_PLATE = re.compile(r"[\u4e00-\u9fff][A-Z][A-Z0-9]{5,6}")
_PII_KEYS = frozenset(
    {
        "contact",
        "deidentification_map",
        "email",
        "full_name",
        "government_id",
        "id_card",
        "license_plate",
        "name",
        "original_vehicle_id",
        "person_id",
        "phone",
        "pii_mapping",
        "plate",
        "plate_number",
        "telephone",
        "vehicle_id",
        "vehicle_plate",
    }
)
_SPEC_KEYS = frozenset(
    {
        "adapter_spec_version",
        "target_schema_version",
        "source_kind",
        "privacy_classification",
        "mode",
        "timezone",
        "distance_unit",
        "time_unit",
        "layout_file",
        "events_file",
        "mapping_file",
        "calibration_parameters",
    }
)


@dataclass(frozen=True, slots=True)
class AdaptationPolicy:
    input_root: Path
    output_root: Path
    schema_dir: Path
    max_file_bytes: int = 32 * 1024 * 1024
    max_total_bytes: int = 128 * 1024 * 1024
    max_records: int = 250_000

    def __post_init__(self) -> None:
        if self.max_file_bytes < 1 or self.max_total_bytes < self.max_file_bytes:
            raise ValueError("adaptation byte limits must be positive and consistently ordered")
        if self.max_records < 1:
            raise ValueError("max_records must be positive")


@dataclass(frozen=True, slots=True)
class DataQualityCheck:
    stage: str
    status: str
    code: str
    artifact: str | None
    message: str
    json_pointer: str | None = None
    fix_hint: str | None = None


@dataclass(frozen=True, slots=True)
class SourceDigest:
    artifact: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class CalibrationGap:
    parameter: str
    status: str
    reason: str


@dataclass(frozen=True, slots=True)
class DataAdaptationReport:
    accepted: bool
    source_label: str
    source_kind: str
    privacy_classification: str
    mode: str
    target_schema_version: str
    file_count: int
    total_bytes: int
    event_count: int
    mapped_layout_field_count: int
    mapped_event_field_count: int
    checks: tuple[DataQualityCheck, ...]
    source_digests: tuple[SourceDigest, ...]
    unrecognized_fields: tuple[str, ...]
    calibration_gaps: tuple[CalibrationGap, ...]

    @property
    def failures(self) -> tuple[DataQualityCheck, ...]:
        return tuple(item for item in self.checks if item.status == "failed")

    @property
    def warnings(self) -> tuple[DataQualityCheck, ...]:
        return tuple(item for item in self.checks if item.status == "warning")


class AdaptationRejectedError(ValueError):
    def __init__(self, report: DataAdaptationReport) -> None:
        self.report = report
        codes = ", ".join(item.code for item in report.failures) or "D5_ADAPTATION_REJECTED"
        super().__init__(f"anonymous data adaptation rejected: {codes}")
