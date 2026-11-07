"""Fail-closed adaptation of anonymous external layout and event data to v1."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from collections import deque
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from parking_opt.contracts.errors import ContractValidationError
from parking_opt.contracts.schema_validation import SchemaCatalog
from parking_opt.contracts.semantic_validation import validate_layout_semantics
from parking_opt.domain.records import freeze_mapping

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
    """Bounded input/output roots for one adaptation operation."""

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
    """Sanitized report; it never contains raw values or absolute paths."""

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
    """Raised when an unsafe source or output request is rejected."""

    def __init__(self, report: DataAdaptationReport) -> None:
        self.report = report
        codes = ", ".join(item.code for item in report.failures) or "D5_ADAPTATION_REJECTED"
        super().__init__(f"anonymous data adaptation rejected: {codes}")


@dataclass(frozen=True, slots=True)
class _AdaptationPreview:
    report: DataAdaptationReport
    layout: Mapping[str, Any] | None
    events: tuple[Mapping[str, Any], ...]


def _check(
    stage: str,
    status: str,
    code: str,
    message: str,
    artifact: str | None = None,
    *,
    json_pointer: str | None = None,
    fix_hint: str | None = None,
) -> DataQualityCheck:
    return DataQualityCheck(
        stage=stage,
        status=status,
        code=code,
        artifact=artifact,
        message=message,
        json_pointer=json_pointer,
        fix_hint=fix_hint,
    )


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeError as exc:
        raise ValueError("source artifact is not valid UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON at line {exc.lineno}, column {exc.colno}") from exc
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
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
                    raise ValueError(
                        f"invalid JSONL at line {line_number}, column {exc.colno}"
                    ) from exc
                if not isinstance(value, dict):
                    raise ValueError(f"JSONL line {line_number} must be an object")
                records.append(cast(dict[str, Any], value))
    except UnicodeError as exc:
        raise ValueError("source artifact is not valid UTF-8") from exc
    return records


def _pii_key(key: object) -> bool:
    text = str(key).casefold()
    return text != "anonymous_vehicle_id" and text in _PII_KEYS


def _contains_pii(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(_pii_key(key) or _contains_pii(child) for key, child in value.items())
    if isinstance(value, list | tuple):
        return any(_contains_pii(child) for child in value)
    if isinstance(value, str):
        return bool(_EMAIL.search(value) or _PHONE.search(value) or _PLATE.search(value))
    return False


def _mapping_references_pii(mapping: Mapping[str, Any]) -> bool:
    for section_name in ("layout", "events"):
        section = mapping.get(section_name)
        if not isinstance(section, Mapping):
            continue
        fields = section.get("fields")
        if not isinstance(fields, list):
            continue
        for item in fields:
            if not isinstance(item, Mapping):
                continue
            source = item.get("source")
            if isinstance(source, str) and any(
                _pii_key(part.replace("~1", "/").replace("~0", "~"))
                for part in source.split("/")[1:]
            ):
                return True
    return False


def _pointer_parts(pointer: str) -> tuple[str, ...]:
    if not pointer.startswith("/") or pointer == "/":
        raise ValueError("JSON Pointer must identify a non-root object field")
    return tuple(part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/"))


def _pointer_get(source: Mapping[str, Any], pointer: str) -> Any:
    value: Any = source
    for part in _pointer_parts(pointer):
        if not isinstance(value, Mapping) or part not in value:
            raise KeyError(pointer)
        value = value[part]
    return deepcopy(value)


def _pointer_set(target: dict[str, Any], pointer: str, value: Any) -> None:
    parts = _pointer_parts(pointer)
    current = target
    for part in parts[:-1]:
        child = current.setdefault(part, {})
        if not isinstance(child, dict):
            raise ValueError("mapping targets overlap")
        current = child
    if parts[-1] in current:
        raise ValueError("mapping target is duplicated")
    current[parts[-1]] = deepcopy(value)


def _mapping_section(
    source: Mapping[str, Any],
    section: Mapping[str, Any],
) -> tuple[dict[str, Any], int]:
    if set(section) != {"constants", "fields"}:
        raise ValueError("mapping section must contain only constants and fields")
    constants = section["constants"]
    fields = section["fields"]
    if not isinstance(constants, Mapping) or not isinstance(fields, list):
        raise ValueError("mapping constants/fields have invalid types")
    target: dict[str, Any] = {}
    for pointer, value in constants.items():
        if not isinstance(pointer, str):
            raise ValueError("constant target must be a JSON Pointer")
        _pointer_set(target, pointer, value)
    count = len(constants)
    for item in fields:
        if not isinstance(item, Mapping) or set(item) != {"source", "target"}:
            raise ValueError("each field mapping requires source and target")
        source_pointer = item["source"]
        target_pointer = item["target"]
        if not isinstance(source_pointer, str) or not isinstance(target_pointer, str):
            raise ValueError("field mappings must use JSON Pointer strings")
        _pointer_set(target, target_pointer, _pointer_get(source, source_pointer))
        count += 1
    return target, count


def _top_level_sources(section: Mapping[str, Any]) -> set[str]:
    fields = cast(Sequence[Mapping[str, Any]], section["fields"])
    return {
        _pointer_parts(cast(str, item["source"]))[0]
        for item in fields
        if isinstance(item.get("source"), str)
    }


def _reachable(starts: set[str], adjacency: Mapping[str, set[str]]) -> set[str]:
    seen = set(starts)
    queue = deque(starts)
    while queue:
        node = queue.popleft()
        for neighbor in adjacency.get(node, set()):
            if neighbor not in seen:
                seen.add(neighbor)
                queue.append(neighbor)
    return seen


def _validate_reachability(layout: Mapping[str, Any]) -> None:
    nodes = cast(Sequence[Mapping[str, Any]], layout["road_nodes"])
    entrances = {
        cast(str, item["road_node_id"]) for item in nodes if item["node_kind"] == "entrance"
    }
    exits = {cast(str, item["road_node_id"]) for item in nodes if item["node_kind"] == "exit"}
    if not entrances or not exits:
        raise ValueError("layout must provide at least one entrance and one exit")
    adjacency: dict[str, set[str]] = {}
    reverse: dict[str, set[str]] = {}
    for edge in cast(Sequence[Mapping[str, Any]], layout["road_edges"]):
        origin = cast(str, edge["from_node_id"])
        destination = cast(str, edge["to_node_id"])
        adjacency.setdefault(origin, set()).add(destination)
        reverse.setdefault(destination, set()).add(origin)
        if edge["directed"] is False:
            adjacency.setdefault(destination, set()).add(origin)
            reverse.setdefault(origin, set()).add(destination)
    from_entrance = _reachable(entrances, adjacency)
    to_exit = _reachable(exits, reverse)
    access_nodes = {
        cast(str, item["access_node_id"])
        for collection in ("slots", "buffer_slots")
        for item in cast(Sequence[Mapping[str, Any]], layout[collection])
    }
    if access_nodes - from_entrance or access_nodes - to_exit:
        raise ValueError("one or more parking positions are not entrance-to-exit reachable")


def _aware_iso8601(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _validate_events(events: Sequence[Mapping[str, Any]], layout: Mapping[str, Any]) -> None:
    event_ids = [item["event_id"] for item in events]
    sequences = [item["sequence_no"] for item in events]
    if len(event_ids) != len(set(event_ids)) or len(sequences) != len(set(sequences)):
        raise ValueError("event IDs and sequence numbers must be unique")
    if sequences != list(range(1, len(events) + 1)):
        raise ValueError("event sequence numbers must be contiguous from one")
    sim_times = [item["sim_time_s"] for item in events]
    if sim_times != sorted(sim_times):
        raise ValueError("event simulation times must be nondecreasing")
    if any(not _aware_iso8601(item["recorded_at"]) for item in events):
        raise ValueError("event recorded_at values must be timezone-aware ISO 8601")

    positions = {
        item["position_id"]
        for collection in ("slots", "buffer_slots")
        for item in cast(Sequence[Mapping[str, Any]], layout[collection])
    }
    nodes = {
        item["road_node_id"]: item["node_kind"]
        for item in cast(Sequence[Mapping[str, Any]], layout["road_nodes"])
    }
    zones = {
        item["channel_zone_id"]
        for item in cast(Sequence[Mapping[str, Any]], layout["channel_zones"])
    }
    for event in events:
        actions: list[Mapping[str, Any]] = []
        action = event.get("action")
        if isinstance(action, Mapping):
            actions.append(action)
        payload = cast(Mapping[str, Any], event.get("payload") or {})
        extra_actions = payload.get("transaction_actions")
        if isinstance(extra_actions, list):
            actions.extend(item for item in extra_actions if isinstance(item, Mapping))
        for item in actions:
            for key in ("origin_position_id", "destination_position_id"):
                if item.get(key) is not None and item[key] not in positions:
                    raise ValueError("event action references an unknown parking position")
            if (
                item.get("destination_exit_id") is not None
                and nodes.get(item["destination_exit_id"]) != "exit"
            ):
                raise ValueError("event action references an unknown exit")
            if set(cast(Sequence[str], item["channel_zone_ids"])) - zones:
                raise ValueError("event action references an unknown channel zone")
        pending = payload.get("pending_request")
        if isinstance(pending, Mapping) and pending.get("entrance_node_id") is not None:
            if nodes.get(pending["entrance_node_id"]) != "entrance":
                raise ValueError("arrival request references an unknown entrance")
        confirmed = payload.get("confirmed_location_state")
        if (
            isinstance(confirmed, Mapping)
            and confirmed.get("position_id") is not None
            and confirmed["position_id"] not in positions
        ):
            raise ValueError("position reconciliation references an unknown position")


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
        _check(
            stage,
            "failed",
            code,
            message,
            artifact,
            json_pointer=json_pointer,
            fix_hint=fix_hint,
        )
    )
    report = DataAdaptationReport(
        accepted=False,
        source_label="selected-import-package",
        source_kind=str(spec.get("source_kind", "unknown")) if spec else "unknown",
        privacy_classification=(
            str(spec.get("privacy_classification", "unknown")) if spec else "unknown"
        ),
        mode=str(spec.get("mode", "unknown")) if spec else "unknown",
        target_schema_version=(
            str(spec.get("target_schema_version", _SUPPORTED_VERSION))
            if spec
            else _SUPPORTED_VERSION
        ),
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


def _inspect_source(source_path: Path, policy: AdaptationPolicy) -> _AdaptationPreview:
    checks: list[DataQualityCheck] = []
    if source_path.is_symlink():
        return _AdaptationPreview(
            _empty_report(
                [
                    _check(
                        "path",
                        "failed",
                        "D5_UNSAFE_ENTRY",
                        "source directory symlinks are not accepted",
                    )
                ]
            ),
            None,
            (),
        )
    try:
        input_root = policy.input_root.resolve(strict=True)
        source = source_path.resolve(strict=True)
    except OSError:
        return _AdaptationPreview(
            _empty_report(
                [_check("path", "failed", "D5_PATH_NOT_FOUND", "selected source does not exist")]
            ),
            None,
            (),
        )
    if not source.is_dir() or not _inside(source, input_root):
        return _AdaptationPreview(
            _empty_report(
                [
                    _check(
                        "path",
                        "failed",
                        "D5_PATH_BOUNDARY",
                        "source must be a directory inside the configured input root",
                    )
                ]
            ),
            None,
            (),
        )
    checks.append(_check("path", "passed", "D5_INPUT_PATH_OK", "input boundary accepted"))

    try:
        entries = tuple(source.iterdir())
    except OSError:
        return _report_with_failure(
            checks=checks,
            stage="path",
            code="D5_PATH_UNREADABLE",
            message="source directory is unreadable",
        )
    if any(item.is_symlink() or not item.is_file() for item in entries):
        return _report_with_failure(
            checks=checks,
            stage="path",
            code="D5_UNSAFE_ENTRY",
            message="source may contain only regular non-symlink files",
            file_count=len(entries),
        )
    if not (source / _SPEC_NAME).is_file():
        return _report_with_failure(
            checks=checks,
            stage="shape",
            code="D5_MISSING_SPEC",
            message="import-spec.json is required",
            file_count=len(entries),
        )
    try:
        spec = _read_object(source / _SPEC_NAME)
    except (OSError, ValueError):
        return _report_with_failure(
            checks=checks,
            stage="syntax",
            code="D5_JSON_SYNTAX",
            message="import specification is not valid UTF-8 JSON",
            artifact=_SPEC_NAME,
            file_count=len(entries),
        )
    if set(spec) != _SPEC_KEYS:
        return _report_with_failure(
            checks=checks,
            stage="shape",
            code="D5_SPEC_FIELDS",
            message="import specification fields do not match the frozen D5 template",
            artifact=_SPEC_NAME,
            file_count=len(entries),
            spec=spec,
        )
    mode = spec.get("mode")
    expected_events = _EVENTS_NAME if mode == "layout_and_events" else None
    if (
        spec.get("layout_file") != _LAYOUT_NAME
        or spec.get("mapping_file") != _MAPPING_NAME
        or spec.get("events_file") != expected_events
    ):
        return _report_with_failure(
            checks=checks,
            stage="path",
            code="D5_PATH_BOUNDARY",
            message="source artifact names must use the fixed safe D5 filenames",
            artifact=_SPEC_NAME,
            file_count=len(entries),
            spec=spec,
        )
    expected_names = {_SPEC_NAME, _MAPPING_NAME, _LAYOUT_NAME}
    if expected_events is not None:
        expected_names.add(_EVENTS_NAME)
    names = {item.name for item in entries}
    if names != expected_names or any(not _SAFE_FILENAME.fullmatch(name) for name in names):
        return _report_with_failure(
            checks=checks,
            stage="shape",
            code="D5_ARTIFACT_SET",
            message="source artifact set is incomplete or contains unsupported files",
            file_count=len(entries),
            spec=spec,
        )

    sizes = {item.name: item.stat().st_size for item in entries}
    total_bytes = sum(sizes.values())
    if any(size > policy.max_file_bytes for size in sizes.values()) or (
        total_bytes > policy.max_total_bytes
    ):
        return _report_with_failure(
            checks=checks,
            stage="limits",
            code="D5_SIZE_LIMIT",
            message="source exceeds the configured byte budget",
            file_count=len(entries),
            total_bytes=total_bytes,
            spec=spec,
        )
    digests = tuple(
        SourceDigest(name, sizes[name], _sha256_file(source / name)) for name in sorted(names)
    )
    checks.append(_check("integrity", "passed", "D5_SOURCE_HASH_OK", "source SHA-256 captured"))

    try:
        mapping = _read_object(source / _MAPPING_NAME)
        layout_source = _read_object(source / _LAYOUT_NAME)
        event_sources = (
            []
            if expected_events is None
            else _read_jsonl(source / _EVENTS_NAME, policy.max_records)
        )
    except OverflowError:
        return _report_with_failure(
            checks=checks,
            stage="limits",
            code="D5_RECORD_LIMIT",
            message="event record budget exceeded",
            file_count=len(entries),
            total_bytes=total_bytes,
            digests=digests,
            spec=spec,
        )
    except (OSError, ValueError):
        return _report_with_failure(
            checks=checks,
            stage="syntax",
            code="D5_JSON_SYNTAX",
            message="a source artifact is not valid UTF-8 JSON/JSONL",
            file_count=len(entries),
            total_bytes=total_bytes,
            digests=digests,
            spec=spec,
        )
    checks.append(_check("syntax", "passed", "D5_JSON_OK", "source JSON syntax accepted"))

    if (
        _contains_pii(spec)
        or _contains_pii(mapping)
        or _contains_pii(layout_source)
        or _contains_pii(event_sources)
        or _mapping_references_pii(mapping)
    ):
        return _report_with_failure(
            checks=checks,
            stage="privacy",
            code="D5_PII_FIELD",
            message="direct identifier, reversible mapping, or PII-like value detected",
            file_count=len(entries),
            total_bytes=total_bytes,
            event_count=len(event_sources),
            digests=digests,
            spec=spec,
            fix_hint="remove PII and perform irreversible anonymization outside the repository",
        )
    if spec["privacy_classification"] != "anonymous" or spec["source_kind"] not in {
        "synthetic",
        "real_anonymized",
    }:
        return _report_with_failure(
            checks=checks,
            stage="privacy",
            code="D5_PRIVACY_LABEL",
            message="only anonymous synthetic or real_anonymized input is accepted",
            file_count=len(entries),
            total_bytes=total_bytes,
            event_count=len(event_sources),
            digests=digests,
            spec=spec,
        )
    checks.append(_check("privacy", "passed", "D5_PRIVACY_OK", "anonymous data label accepted"))

    if (
        spec["adapter_spec_version"] != _SUPPORTED_VERSION
        or spec["target_schema_version"] != _SUPPORTED_VERSION
        or not isinstance(mapping.get("layout"), Mapping)
        or not isinstance(mapping.get("events"), Mapping)
        or mapping.get("mapping_version") != _SUPPORTED_VERSION
        or mapping.get("target_schema_version") != _SUPPORTED_VERSION
    ):
        return _report_with_failure(
            checks=checks,
            stage="mapping",
            code="D5_SCHEMA_VERSION",
            message="adapter, mapping, and target schema versions must all be 1.0.0",
            file_count=len(entries),
            total_bytes=total_bytes,
            event_count=len(event_sources),
            digests=digests,
            spec=spec,
        )
    if (
        mode not in {"layout_only", "layout_and_events"}
        or spec["distance_unit"] != "m"
        or spec["time_unit"] != "s"
    ):
        return _report_with_failure(
            checks=checks,
            stage="units",
            code="D5_UNIT",
            message="mode or units are unsupported; v1 requires meters and integer seconds",
            file_count=len(entries),
            total_bytes=total_bytes,
            event_count=len(event_sources),
            digests=digests,
            spec=spec,
        )
    if not isinstance(spec["timezone"], str) or not _TIMEZONE.fullmatch(spec["timezone"]):
        return _report_with_failure(
            checks=checks,
            stage="time",
            code="D5_TIMEZONE",
            message="timezone must be UTC or an explicit ISO 8601 offset",
            file_count=len(entries),
            total_bytes=total_bytes,
            event_count=len(event_sources),
            digests=digests,
            spec=spec,
        )
    checks.append(_check("units", "passed", "D5_UNITS_OK", "meters and seconds accepted"))
    checks.append(_check("time", "passed", "D5_TIMEZONE_OK", "explicit timezone accepted"))

    layout_count = 0
    mapped_event_count = 0
    try:
        layout, layout_count = _mapping_section(
            layout_source, cast(Mapping[str, Any], mapping["layout"])
        )
        events: list[dict[str, Any]] = []
        for source_event in event_sources:
            event, count = _mapping_section(
                source_event, cast(Mapping[str, Any], mapping["events"])
            )
            events.append(event)
            mapped_event_count = count
    except KeyError:
        return _report_with_failure(
            checks=checks,
            stage="mapping",
            code="D5_MAPPING_SOURCE_MISSING",
            message="a mapped source field is missing",
            file_count=len(entries),
            total_bytes=total_bytes,
            event_count=len(event_sources),
            digests=digests,
            spec=spec,
            layout_count=layout_count,
            event_count_mapped=mapped_event_count,
        )
    except (TypeError, ValueError):
        return _report_with_failure(
            checks=checks,
            stage="mapping",
            code="D5_MAPPING_INVALID",
            message="field mapping is malformed, overlapping, or duplicated",
            file_count=len(entries),
            total_bytes=total_bytes,
            event_count=len(event_sources),
            digests=digests,
            spec=spec,
            layout_count=layout_count,
            event_count_mapped=mapped_event_count,
        )
    checks.append(_check("mapping", "passed", "D5_MAPPING_OK", "explicit field mapping applied"))

    schema_artifact = _LAYOUT_NAME
    try:
        catalog = SchemaCatalog(policy.schema_dir)
        catalog.validate("layout.schema.json", layout)
        for event in events:
            schema_artifact = _EVENTS_NAME
            catalog.validate("event.schema.json", event)
    except ContractValidationError as exc:
        issue = exc.issues[0]
        return _report_with_failure(
            checks=checks,
            stage="schema",
            code="D5_SCHEMA_REJECTED",
            message="mapped output does not satisfy the frozen v1 schema",
            artifact=schema_artifact,
            json_pointer=issue.json_pointer,
            file_count=len(entries),
            total_bytes=total_bytes,
            event_count=len(events),
            digests=digests,
            spec=spec,
            layout_count=layout_count,
            event_count_mapped=mapped_event_count,
            fix_hint="repair the external field mapping without changing schemas/v1",
        )
    except (OSError, TypeError, ValueError):
        return _report_with_failure(
            checks=checks,
            stage="schema",
            code="D5_SCHEMA_REJECTED",
            message="frozen v1 schema catalog or mapped output is invalid",
            artifact=schema_artifact,
            file_count=len(entries),
            total_bytes=total_bytes,
            event_count=len(events),
            digests=digests,
            spec=spec,
            layout_count=layout_count,
            event_count_mapped=mapped_event_count,
        )
    checks.append(_check("schema", "passed", "D5_SCHEMA_OK", "frozen v1 schemas accepted"))

    try:
        validate_layout_semantics(layout)
    except (ContractValidationError, KeyError, TypeError, ValueError):
        return _report_with_failure(
            checks=checks,
            stage="semantics",
            code="D5_LAYOUT_SEMANTIC",
            message="layout references, IDs, path costs, or tandem depths are invalid",
            artifact=_LAYOUT_NAME,
            file_count=len(entries),
            total_bytes=total_bytes,
            event_count=len(events),
            digests=digests,
            spec=spec,
            layout_count=layout_count,
            event_count_mapped=mapped_event_count,
        )
    try:
        _validate_reachability(layout)
    except (KeyError, TypeError, ValueError):
        return _report_with_failure(
            checks=checks,
            stage="reachability",
            code="D5_REACHABILITY",
            message="entrance, exit, or parking-position reachability check failed",
            artifact=_LAYOUT_NAME,
            file_count=len(entries),
            total_bytes=total_bytes,
            event_count=len(events),
            digests=digests,
            spec=spec,
            layout_count=layout_count,
            event_count_mapped=mapped_event_count,
        )
    try:
        _validate_events(events, layout)
    except (KeyError, TypeError, ValueError) as exc:
        message = str(exc)
        code = "D5_DUPLICATE_ID" if "unique" in message else "D5_EVENT_SEMANTIC"
        return _report_with_failure(
            checks=checks,
            stage="semantics",
            code=code,
            message="event order, references, timestamp, or identifier checks failed",
            artifact=_EVENTS_NAME if events else None,
            file_count=len(entries),
            total_bytes=total_bytes,
            event_count=len(events),
            digests=digests,
            spec=spec,
            layout_count=layout_count,
            event_count_mapped=mapped_event_count,
        )
    checks.append(
        _check(
            "semantics",
            "passed",
            "D5_SEMANTICS_OK",
            "IDs, references, tandem depths, event order, and timestamps accepted",
        )
    )
    checks.append(
        _check(
            "reachability",
            "passed",
            "D5_REACHABILITY_OK",
            "entrance-to-position-to-exit reachability accepted",
        )
    )

    layout_section = cast(Mapping[str, Any], mapping["layout"])
    event_section = cast(Mapping[str, Any], mapping["events"])
    unrecognized = {
        f"layout:{key}" for key in layout_source if key not in _top_level_sources(layout_section)
    }
    for event in event_sources:
        unrecognized.update(
            f"events:{key}" for key in event if key not in _top_level_sources(event_section)
        )
    if unrecognized:
        checks.append(
            _check(
                "mapping",
                "warning",
                "D5_UNRECOGNIZED_FIELDS",
                "unmapped source field names were retained only in the report",
            )
        )

    calibration = spec["calibration_parameters"]
    if not isinstance(calibration, Mapping):
        return _report_with_failure(
            checks=checks,
            stage="calibration",
            code="D5_CALIBRATION_FIELDS",
            message="calibration_parameters must be an object",
            file_count=len(entries),
            total_bytes=total_bytes,
            event_count=len(events),
            digests=digests,
            spec=spec,
            layout_count=layout_count,
            event_count_mapped=mapped_event_count,
        )
    gaps = tuple(
        CalibrationGap(
            parameter=str(name),
            status="not_calibrated" if value is None else "provided_not_validated",
            reason=(
                "no anonymous real evidence supplied"
                if value is None
                else "value is retained as source metadata and is not a calibration conclusion"
            ),
        )
        for name, value in sorted(calibration.items())
    )
    if gaps:
        checks.append(
            _check(
                "calibration",
                "warning",
                "D5_CALIBRATION_INCOMPLETE",
                "calibration gaps remain and no real-world calibration conclusion is produced",
            )
        )

    report = DataAdaptationReport(
        accepted=True,
        source_label="selected-import-package",
        source_kind=cast(str, spec["source_kind"]),
        privacy_classification=cast(str, spec["privacy_classification"]),
        mode=cast(str, mode),
        target_schema_version=_SUPPORTED_VERSION,
        file_count=len(entries),
        total_bytes=total_bytes,
        event_count=len(events),
        mapped_layout_field_count=layout_count,
        mapped_event_field_count=mapped_event_count,
        checks=tuple(checks),
        source_digests=digests,
        unrecognized_fields=tuple(sorted(unrecognized)),
        calibration_gaps=gaps,
    )
    return _AdaptationPreview(
        report,
        freeze_mapping(layout),
        tuple(freeze_mapping(item) for item in events),
    )


def validate_data_source(source_path: Path, *, policy: AdaptationPolicy) -> DataAdaptationReport:
    """Validate and preview a source package without writing any output."""

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
            {
                "artifact": item.artifact,
                "size_bytes": item.size_bytes,
                "sha256": item.sha256,
            }
            for item in report.source_digests
        ],
        "unrecognized_fields": list(report.unrecognized_fields),
        "calibration_gaps": [
            {
                "parameter": item.parameter,
                "status": item.status,
                "reason": item.reason,
            }
            for item in report.calibration_gaps
        ],
    }


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _jsonable(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(child) for key, child in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(child) for child in value]
    return value


def write_migration_copy(
    source_path: Path,
    output_path: Path,
    *,
    policy: AdaptationPolicy,
) -> DataAdaptationReport:
    """Write validated v1 data to a new directory; never overwrite source or output."""

    preview = _inspect_source(source_path, policy)
    if not preview.report.accepted or preview.layout is None:
        raise AdaptationRejectedError(preview.report)
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
            spec={
                "source_kind": preview.report.source_kind,
                "privacy_classification": preview.report.privacy_classification,
                "mode": preview.report.mode,
                "target_schema_version": preview.report.target_schema_version,
            },
        )
        raise AdaptationRejectedError(failed.report) from None
    if (
        not _inside(output, output_root)
        or _inside(output, source)
        or output == source
        or not _SAFE_FILENAME.fullmatch(output.name)
    ):
        failed = _report_with_failure(
            checks=list(preview.report.checks),
            stage="output",
            code="D5_OUTPUT_BOUNDARY",
            message="output must be a new safe directory outside the source",
            spec={
                "source_kind": preview.report.source_kind,
                "privacy_classification": preview.report.privacy_classification,
                "mode": preview.report.mode,
                "target_schema_version": preview.report.target_schema_version,
            },
        )
        raise AdaptationRejectedError(failed.report)
    if output.exists():
        failed = _report_with_failure(
            checks=list(preview.report.checks),
            stage="output",
            code="D5_OUTPUT_EXISTS",
            message="output already exists; in-place overwrite is forbidden",
            spec={
                "source_kind": preview.report.source_kind,
                "privacy_classification": preview.report.privacy_classification,
                "mode": preview.report.mode,
                "target_schema_version": preview.report.target_schema_version,
            },
        )
        raise AdaptationRejectedError(failed.report)

    temp_dir = Path(tempfile.mkdtemp(prefix=".d5-adapt-", dir=output_parent))
    try:
        _write_json(temp_dir / "layout.v1.json", preview.layout)
        if preview.events:
            with (temp_dir / "events.v1.jsonl").open("x", encoding="utf-8", newline="\n") as handle:
                for event in preview.events:
                    handle.write(
                        json.dumps(
                            _jsonable(event),
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
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
                "source_sha256": {
                    item.artifact: item.sha256 for item in preview.report.source_digests
                },
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
