"""Source inspection front half for anonymous data adaptation."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from parking_opt.application.data_adaptation_helpers import (
    _check,
    _contains_pii,
    _inside,
    _mapping_references_pii,
    _read_jsonl,
    _read_object,
    _sha256_file,
)
from parking_opt.application.data_adaptation_report import _AdaptationPreview, _empty_report, _report_with_failure
from parking_opt.application.data_adaptation_types import (
    _EVENTS_NAME,
    _LAYOUT_NAME,
    _MAPPING_NAME,
    _SAFE_FILENAME,
    _SPEC_KEYS,
    _SPEC_NAME,
    _TIMEZONE,
    _SUPPORTED_VERSION,
    AdaptationPolicy,
    DataQualityCheck,
    SourceDigest,
)
from parking_opt.application.data_adaptation_build import _build_adaptation


def _inspect_source(source_path: Path, policy: AdaptationPolicy) -> _AdaptationPreview:
    checks: list[DataQualityCheck] = []
    if source_path.is_symlink():
        return _AdaptationPreview(
            _empty_report([_check("path", "failed", "D5_UNSAFE_ENTRY", "source directory symlinks are not accepted")]),
            None,
            (),
        )
    try:
        input_root = policy.input_root.resolve(strict=True)
        source = source_path.resolve(strict=True)
    except OSError:
        return _AdaptationPreview(
            _empty_report([_check("path", "failed", "D5_PATH_NOT_FOUND", "selected source does not exist")]),
            None,
            (),
        )
    if not source.is_dir() or not _inside(source, input_root):
        return _AdaptationPreview(
            _empty_report([_check("path", "failed", "D5_PATH_BOUNDARY", "source must be a directory inside the configured input root")]),
            None,
            (),
        )
    checks.append(_check("path", "passed", "D5_INPUT_PATH_OK", "input boundary accepted"))
    try:
        entries = tuple(source.iterdir())
    except OSError:
        return _report_with_failure(checks=checks, stage="path", code="D5_PATH_UNREADABLE", message="source directory is unreadable")
    if any(item.is_symlink() or not item.is_file() for item in entries):
        return _report_with_failure(checks=checks, stage="path", code="D5_UNSAFE_ENTRY", message="source may contain only regular non-symlink files", file_count=len(entries))
    if not (source / _SPEC_NAME).is_file():
        return _report_with_failure(checks=checks, stage="shape", code="D5_MISSING_SPEC", message="import-spec.json is required", file_count=len(entries))
    try:
        spec = _read_object(source / _SPEC_NAME)
    except (OSError, ValueError):
        return _report_with_failure(checks=checks, stage="syntax", code="D5_JSON_SYNTAX", message="import specification is not valid UTF-8 JSON", artifact=_SPEC_NAME, file_count=len(entries))
    if set(spec) != _SPEC_KEYS:
        return _report_with_failure(checks=checks, stage="shape", code="D5_SPEC_FIELDS", message="import specification fields do not match the frozen D5 template", artifact=_SPEC_NAME, file_count=len(entries), spec=spec)
    mode = spec.get("mode")
    expected_events = _EVENTS_NAME if mode == "layout_and_events" else None
    if (
        spec.get("layout_file") != _LAYOUT_NAME
        or spec.get("mapping_file") != _MAPPING_NAME
        or spec.get("events_file") != expected_events
    ):
        return _report_with_failure(checks=checks, stage="path", code="D5_PATH_BOUNDARY", message="source artifact names must use the fixed safe D5 filenames", artifact=_SPEC_NAME, file_count=len(entries), spec=spec)
    expected_names = {_SPEC_NAME, _MAPPING_NAME, _LAYOUT_NAME}
    if expected_events is not None:
        expected_names.add(_EVENTS_NAME)
    names = {item.name for item in entries}
    if names != expected_names or any(not _SAFE_FILENAME.fullmatch(name) for name in names):
        return _report_with_failure(checks=checks, stage="shape", code="D5_ARTIFACT_SET", message="source artifact set is incomplete or contains unsupported files", file_count=len(entries), spec=spec)

    sizes = {item.name: item.stat().st_size for item in entries}
    total_bytes = sum(sizes.values())
    if any(size > policy.max_file_bytes for size in sizes.values()) or (total_bytes > policy.max_total_bytes):
        return _report_with_failure(checks=checks, stage="limits", code="D5_SIZE_LIMIT", message="source exceeds the configured byte budget", file_count=len(entries), total_bytes=total_bytes, spec=spec)
    digests = tuple(SourceDigest(name, sizes[name], _sha256_file(source / name)) for name in sorted(names))
    checks.append(_check("integrity", "passed", "D5_SOURCE_HASH_OK", "source SHA-256 captured"))

    try:
        mapping = _read_object(source / _MAPPING_NAME)
        layout_source = _read_object(source / _LAYOUT_NAME)
        event_sources = [] if expected_events is None else _read_jsonl(source / _EVENTS_NAME, policy.max_records)
    except OverflowError:
        return _report_with_failure(checks=checks, stage="limits", code="D5_RECORD_LIMIT", message="event record budget exceeded", file_count=len(entries), total_bytes=total_bytes, digests=digests, spec=spec)
    except (OSError, ValueError):
        return _report_with_failure(checks=checks, stage="syntax", code="D5_JSON_SYNTAX", message="a source artifact is not valid UTF-8 JSON/JSONL", file_count=len(entries), total_bytes=total_bytes, digests=digests, spec=spec)
    checks.append(_check("syntax", "passed", "D5_JSON_OK", "source JSON syntax accepted"))

    if (
        _contains_pii(spec)
        or _contains_pii(mapping)
        or _contains_pii(layout_source)
        or _contains_pii(event_sources)
        or _mapping_references_pii(mapping)
    ):
        return _report_with_failure(checks=checks, stage="privacy", code="D5_PII_FIELD", message="direct identifier, reversible mapping, or PII-like value detected", file_count=len(entries), total_bytes=total_bytes, event_count=len(event_sources), digests=digests, spec=spec, fix_hint="remove PII and perform irreversible anonymization outside the repository")
    if spec["privacy_classification"] != "anonymous" or spec["source_kind"] not in {"synthetic", "real_anonymized"}:
        return _report_with_failure(checks=checks, stage="privacy", code="D5_PRIVACY_LABEL", message="only anonymous synthetic or real_anonymized input is accepted", file_count=len(entries), total_bytes=total_bytes, event_count=len(event_sources), digests=digests, spec=spec)
    checks.append(_check("privacy", "passed", "D5_PRIVACY_OK", "anonymous data label accepted"))

    if (
        spec["adapter_spec_version"] != _SUPPORTED_VERSION
        or spec["target_schema_version"] != _SUPPORTED_VERSION
        or not isinstance(mapping.get("layout"), Mapping)
        or not isinstance(mapping.get("events"), Mapping)
        or mapping.get("mapping_version") != _SUPPORTED_VERSION
        or mapping.get("target_schema_version") != _SUPPORTED_VERSION
    ):
        return _report_with_failure(checks=checks, stage="mapping", code="D5_SCHEMA_VERSION", message="adapter, mapping, and target schema versions must all be 1.0.0", file_count=len(entries), total_bytes=total_bytes, event_count=len(event_sources), digests=digests, spec=spec)
    if mode not in {"layout_only", "layout_and_events"} or spec["distance_unit"] != "m" or spec["time_unit"] != "s":
        return _report_with_failure(checks=checks, stage="units", code="D5_UNIT", message="mode or units are unsupported; v1 requires meters and integer seconds", file_count=len(entries), total_bytes=total_bytes, event_count=len(event_sources), digests=digests, spec=spec)
    if not isinstance(spec["timezone"], str) or not _TIMEZONE.fullmatch(spec["timezone"]):
        return _report_with_failure(checks=checks, stage="time", code="D5_TIMEZONE", message="timezone must be UTC or an explicit ISO 8601 offset", file_count=len(entries), total_bytes=total_bytes, event_count=len(event_sources), digests=digests, spec=spec)
    checks.append(_check("units", "passed", "D5_UNITS_OK", "meters and seconds accepted"))
    checks.append(_check("time", "passed", "D5_TIMEZONE_OK", "explicit timezone accepted"))

    ctx = {
        "source": source,
        "entries": entries,
        "sizes": sizes,
        "total_bytes": total_bytes,
        "digests": digests,
        "checks": checks,
        "spec": spec,
        "mapping": mapping,
        "layout_source": layout_source,
        "event_sources": event_sources,
        "expected_events": expected_events,
        "mode": mode,
    }
    return _build_adaptation(ctx, policy)
