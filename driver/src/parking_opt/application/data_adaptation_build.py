"""Build and validate mapped v1 output for anonymous data adaptation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from parking_opt.application.data_adaptation_helpers import (
    _check,
    _mapping_section,
    _top_level_sources,
    _validate_events,
    _validate_reachability,
)
from parking_opt.application.data_adaptation_report import _AdaptationPreview, _report_with_failure
from parking_opt.application.data_adaptation_types import (
    _EVENTS_NAME,
    _LAYOUT_NAME,
    _SUPPORTED_VERSION,
    AdaptationPolicy,
    CalibrationGap,
    DataAdaptationReport,
)
from parking_opt.contracts.errors import ContractValidationError
from parking_opt.contracts.schema_validation import SchemaCatalog
from parking_opt.contracts.semantic_validation import validate_layout_semantics
from parking_opt.domain.records import freeze_mapping


def _build_adaptation(ctx: dict[str, Any], policy: AdaptationPolicy) -> _AdaptationPreview:
    checks = ctx["checks"]
    spec = ctx["spec"]
    mapping = ctx["mapping"]
    layout_source = ctx["layout_source"]
    event_sources = ctx["event_sources"]
    entries = ctx["entries"]
    total_bytes = ctx["total_bytes"]
    digests = ctx["digests"]
    source = ctx["source"]
    mode = ctx["mode"]

    layout_count = 0
    mapped_event_count = 0
    try:
        layout, layout_count = _mapping_section(layout_source, cast(Mapping[str, Any], mapping["layout"]))
        events: list[dict[str, Any]] = []
        for source_event in event_sources:
            event, count = _mapping_section(source_event, cast(Mapping[str, Any], mapping["events"]))
            events.append(event)
            mapped_event_count = count
    except KeyError:
        return _report_with_failure(checks=checks, stage="mapping", code="D5_MAPPING_SOURCE_MISSING", message="a mapped source field is missing", file_count=len(entries), total_bytes=total_bytes, event_count=len(event_sources), digests=digests, spec=spec, layout_count=layout_count, event_count_mapped=mapped_event_count)
    except (TypeError, ValueError):
        return _report_with_failure(checks=checks, stage="mapping", code="D5_MAPPING_INVALID", message="field mapping is malformed, overlapping, or duplicated", file_count=len(entries), total_bytes=total_bytes, event_count=len(event_sources), digests=digests, spec=spec, layout_count=layout_count, event_count_mapped=mapped_event_count)
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
        return _report_with_failure(checks=checks, stage="schema", code="D5_SCHEMA_REJECTED", message="mapped output does not satisfy the frozen v1 schema", artifact=schema_artifact, json_pointer=issue.json_pointer, file_count=len(entries), total_bytes=total_bytes, event_count=len(events), digests=digests, spec=spec, layout_count=layout_count, event_count_mapped=mapped_event_count, fix_hint="repair the external field mapping without changing schemas/v1")
    except (OSError, TypeError, ValueError):
        return _report_with_failure(checks=checks, stage="schema", code="D5_SCHEMA_REJECTED", message="frozen v1 schema catalog or mapped output is invalid", artifact=schema_artifact, file_count=len(entries), total_bytes=total_bytes, event_count=len(events), digests=digests, spec=spec, layout_count=layout_count, event_count_mapped=mapped_event_count)
    checks.append(_check("schema", "passed", "D5_SCHEMA_OK", "frozen v1 schemas accepted"))

    try:
        validate_layout_semantics(layout)
    except (ContractValidationError, KeyError, TypeError, ValueError):
        return _report_with_failure(checks=checks, stage="semantics", code="D5_LAYOUT_SEMANTIC", message="layout references, IDs, path costs, or tandem depths are invalid", artifact=_LAYOUT_NAME, file_count=len(entries), total_bytes=total_bytes, event_count=len(events), digests=digests, spec=spec, layout_count=layout_count, event_count_mapped=mapped_event_count)
    try:
        _validate_reachability(layout)
    except (KeyError, TypeError, ValueError):
        return _report_with_failure(checks=checks, stage="reachability", code="D5_REACHABILITY", message="entrance, exit, or parking-position reachability check failed", artifact=_LAYOUT_NAME, file_count=len(entries), total_bytes=total_bytes, event_count=len(events), digests=digests, spec=spec, layout_count=layout_count, event_count_mapped=mapped_event_count)
    try:
        _validate_events(events, layout)
    except (KeyError, TypeError, ValueError) as exc:
        message = str(exc)
        code = "D5_DUPLICATE_ID" if "unique" in message else "D5_EVENT_SEMANTIC"
        return _report_with_failure(checks=checks, stage="semantics", code=code, message="event order, references, timestamp, or identifier checks failed", artifact=_EVENTS_NAME if events else None, file_count=len(entries), total_bytes=total_bytes, event_count=len(events), digests=digests, spec=spec, layout_count=layout_count, event_count_mapped=mapped_event_count)
    checks.append(_check("semantics", "passed", "D5_SEMANTICS_OK", "IDs, references, tandem depths, event order, and timestamps accepted"))
    checks.append(_check("reachability", "passed", "D5_REACHABILITY_OK", "entrance-to-position-to-exit reachability accepted"))

    layout_section = cast(Mapping[str, Any], mapping["layout"])
    event_section = cast(Mapping[str, Any], mapping["events"])
    unrecognized = {f"layout:{key}" for key in layout_source if key not in _top_level_sources(layout_section)}
    for event in event_sources:
        unrecognized.update(f"events:{key}" for key in event if key not in _top_level_sources(event_section))
    if unrecognized:
        checks.append(_check("mapping", "warning", "D5_UNRECOGNIZED_FIELDS", "unmapped source field names were retained only in the report"))

    calibration = spec["calibration_parameters"]
    if not isinstance(calibration, Mapping):
        return _report_with_failure(checks=checks, stage="calibration", code="D5_CALIBRATION_FIELDS", message="calibration_parameters must be an object", file_count=len(entries), total_bytes=total_bytes, event_count=len(events), digests=digests, spec=spec, layout_count=layout_count, event_count_mapped=mapped_event_count)
    gaps = tuple(
        CalibrationGap(
            parameter=str(name),
            status="not_calibrated" if value is None else "provided_not_validated",
            reason="no anonymous real evidence supplied" if value is None else "value is retained as source metadata and is not a calibration conclusion",
        )
        for name, value in sorted(calibration.items())
    )
    if gaps:
        checks.append(_check("calibration", "warning", "D5_CALIBRATION_INCOMPLETE", "calibration gaps remain and no real-world calibration conclusion is produced"))

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
