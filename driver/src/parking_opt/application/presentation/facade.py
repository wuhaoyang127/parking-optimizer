"""Fail-closed loading, replay, audit, and metric views for the future UI."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from statistics import fmean
from typing import Any, cast

from parking_opt.application.presentation.models import (
    DecisionActionView,
    DecisionAuditView,
    FileDigest,
    ImportPolicy,
    ImportRejectedError,
    ImportValidationReport,
    MetricSummaryView,
    MetricValueView,
    ReplayActionView,
    ReplayEventView,
    ReplayFrame,
    ReplayIndex,
    ReplayPositionView,
    ReplayTimeline,
    ReplayVehicleView,
    RequestMetricSummaryView,
    ValidatedDemoBundle,
    ValidationCheck,
)
from parking_opt.contracts.errors import ContractValidationError
from parking_opt.contracts.schema_validation import SchemaCatalog
from parking_opt.contracts.semantic_validation import (
    validate_layout_semantics,
    validate_scenario_semantics,
)
from parking_opt.domain.enums import ActionStatus, LocationKind, ManualStatus
from parking_opt.domain.records import freeze_mapping
from parking_opt.domain.state import AuthoritativeState
from parking_opt.domain.transitions import apply_event
from parking_opt.experiments.runner import REQUIRED_RUN_ARTIFACTS, validate_completed_run
from parking_opt.layout.model import layout_from_mapping
from parking_opt.layout.state_adapter import initial_state_from_layout

_INDEX_NAME = "artifact-index.json"
_EXPECTED_FILES = frozenset({*REQUIRED_RUN_ARTIFACTS, _INDEX_NAME})
_JSON_FILES = frozenset(
    {"layout.json", "scenario.json", "run-manifest.json", "artifact-index.json"}
)
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
    return ValidationCheck(
        stage,
        status,
        code,
        artifact,
        message,
        json_pointer,
        constraint_id,
        fix_hint,
    )


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
        raise _SyntaxIssue(
            path.name,
            f"invalid JSON at line {exc.lineno}, column {exc.colno}",
        ) from exc
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
                    raise _SyntaxIssue(
                        path.name,
                        f"invalid JSONL at line {line_number}, column {exc.colno}",
                    ) from exc
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
        checks.append(
            _check("path", "failed", "D1_PATH_NOT_FOUND", "selected bundle does not exist")
        )
        return ImportValidationReport(False, source_label, 0, 0, 0, tuple(checks)), None

    if not source.is_dir() or not _inside(source, allowed_root):
        checks.append(
            _check(
                "path",
                "failed",
                "D1_PATH_BOUNDARY",
                "selected bundle must be a directory inside the allowed root",
            )
        )
        return ImportValidationReport(False, source_label, 0, 0, 0, tuple(checks)), None
    checks.append(_check("path", "passed", "D1_PATH_OK", "path boundary accepted"))

    try:
        entries = tuple(source.iterdir())
    except OSError:
        checks.append(
            _check("path", "failed", "D1_PATH_UNREADABLE", "bundle directory is unreadable")
        )
        return ImportValidationReport(False, source_label, 0, 0, 0, tuple(checks)), None
    if (not policy.allow_symlinks and any(item.is_symlink() for item in entries)) or any(
        not item.is_file() for item in entries
    ):
        checks.append(
            _check(
                "path",
                "failed",
                "D1_UNSAFE_ENTRY",
                "bundle may contain only regular non-symlink files",
            )
        )
        return ImportValidationReport(False, source_label, 0, 0, 0, tuple(checks)), None
    names = {item.name for item in entries}
    if names != _EXPECTED_FILES:
        checks.append(
            _check(
                "shape",
                "failed",
                "D1_ARTIFACT_SET",
                "bundle artifact set is incomplete or contains unsupported files",
            )
        )
        return ImportValidationReport(False, source_label, len(entries), 0, 0, tuple(checks)), None

    sizes = {item.name: item.stat().st_size for item in entries}
    total_bytes = sum(sizes.values())
    if any(size > policy.max_file_bytes for size in sizes.values()) or (
        total_bytes > policy.max_total_bytes
    ):
        checks.append(
            _check(
                "limits",
                "failed",
                "D1_SIZE_LIMIT",
                "bundle exceeds the configured byte budget",
            )
        )
        return (
            ImportValidationReport(
                False, source_label, len(entries), total_bytes, 0, tuple(checks)
            ),
            None,
        )
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
        checks.append(
            _check(
                "syntax",
                "failed",
                "D1_JSON_SYNTAX",
                str(exc),
                exc.artifact,
                fix_hint="repair the named UTF-8 JSON/JSONL artifact and export the bundle again",
            )
        )
        return (
            ImportValidationReport(
                False, source_label, len(entries), total_bytes, record_count, tuple(checks)
            ),
            None,
        )
    except OverflowError:
        checks.append(_check("limits", "failed", "D1_RECORD_LIMIT", "record budget exceeded"))
        return (
            ImportValidationReport(
                False, source_label, len(entries), total_bytes, record_count, tuple(checks)
            ),
            None,
        )
    checks.append(_check("syntax", "passed", "D1_JSON_OK", "JSON syntax accepted"))

    all_values: tuple[object, ...] = (*objects.values(), *(streams.values()))
    if any(_contains_pii_key(item) for item in all_values):
        checks.append(
            _check(
                "privacy",
                "failed",
                "D1_PII_FIELD",
                "direct identifier or re-identification mapping field detected",
            )
        )
        return (
            ImportValidationReport(
                False, source_label, len(entries), total_bytes, record_count, tuple(checks)
            ),
            None,
        )
    checks.append(_check("privacy", "passed", "D1_PRIVACY_OK", "PII field scan accepted"))

    index = objects[_INDEX_NAME]
    if index.get("schema_version") != "1.0.0":
        checks.append(
            _check(
                "schema",
                "failed",
                "D1_UNKNOWN_SCHEMA_VERSION",
                "artifact index schema version is unsupported",
                _INDEX_NAME,
            )
        )
        return (
            ImportValidationReport(
                False, source_label, len(entries), total_bytes, record_count, tuple(checks)
            ),
            None,
        )
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
        checks.append(
            _check(
                "schema",
                "failed",
                "D1_SCHEMA_REJECTED",
                "an artifact does not satisfy the frozen v1 schema",
                schema_artifact,
                json_pointer=issue.json_pointer,
                constraint_id=issue.constraint_id,
                fix_hint="repair the named field against schemas/v1 and export a complete bundle",
            )
        )
        return (
            ImportValidationReport(
                False, source_label, len(entries), total_bytes, record_count, tuple(checks)
            ),
            None,
        )
    except (KeyError, OSError, TypeError, ValueError):
        checks.append(
            _check(
                "schema",
                "failed",
                "D1_SCHEMA_REJECTED",
                "the frozen v1 schema catalog or artifact structure is invalid",
                schema_artifact,
                fix_hint="restore the approved schemas/v1 catalog and export the bundle again",
            )
        )
        return (
            ImportValidationReport(
                False, source_label, len(entries), total_bytes, record_count, tuple(checks)
            ),
            None,
        )
    checks.append(_check("schema", "passed", "D1_SCHEMA_OK", "frozen v1 schemas accepted"))

    try:
        validate_completed_run(source, schema_catalog=catalog)
    except (OSError, TypeError, ValueError):
        checks.append(
            _check(
                "integrity",
                "failed",
                "D1_HASH_MISMATCH",
                "artifact set is missing, altered, or inconsistent with its saved hashes",
            )
        )
        return (
            ImportValidationReport(
                False, source_label, len(entries), total_bytes, record_count, tuple(checks)
            ),
            None,
        )
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
        if not _identity_matches(
            events, manifest=manifest, include_run=True, include_algorithm=False
        ):
            raise ValueError("event identity mismatch")
        if not _identity_matches(
            decisions, manifest=manifest, include_run=False, include_algorithm=True
        ):
            raise ValueError("decision identity mismatch")
        if not _identity_matches(
            metrics, manifest=manifest, include_run=True, include_algorithm=True
        ):
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
        checks.append(
            _check(
                "semantics",
                "failed",
                "D1_SEMANTIC_REJECTED",
                "cross-record references, order, or exact replay are invalid",
            )
        )
        return (
            ImportValidationReport(
                False, source_label, len(entries), total_bytes, record_count, tuple(checks)
            ),
            None,
        )
    checks.append(
        _check("semantics", "passed", "D1_REPLAY_OK", "semantic checks and exact replay accepted")
    )

    digests = tuple(
        FileDigest(name, sizes[name], _sha256_file(source / name)) for name in sorted(names)
    )
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
    report = ImportValidationReport(
        True, source_label, len(entries), total_bytes, record_count, tuple(checks)
    )
    return report, bundle


def validate_import(path: Path, *, policy: ImportPolicy) -> ImportValidationReport:
    """Validate an import without exposing parsed values or retaining mutable input."""

    report, _ = _load_validated(path, policy)
    return report


def load_demo_bundle(path: Path, *, policy: ImportPolicy) -> ValidatedDemoBundle:
    """Return an immutable bundle only after every D1 validation stage passes."""

    report, bundle = _load_validated(path, policy)
    if bundle is None:
        raise ImportRejectedError(report)
    return bundle


def build_replay_index(
    bundle: ValidatedDemoBundle,
    *,
    checkpoint_interval: int = 64,
) -> ReplayIndex:
    """Replay once and retain immutable checkpoints for bounded frame lookup."""

    if checkpoint_interval < 1:
        raise ValueError("checkpoint_interval must be positive")
    checkpoints = [bundle._initial_state]
    state = bundle._initial_state
    for event in bundle._events:
        state = apply_event(state, event)
        if state.sequence_no % checkpoint_interval == 0:
            checkpoints.append(state)
    if checkpoints[-1].sequence_no != state.sequence_no:
        checkpoints.append(state)
    return ReplayIndex(
        run_id=bundle.run_id,
        scenario_id=bundle.scenario_id,
        first_sequence_no=0,
        last_sequence_no=len(bundle._events),
        checkpoint_interval=checkpoint_interval,
        _events=bundle._events,
        _checkpoints=tuple(checkpoints),
    )


def _frame_from_state(
    state: AuthoritativeState,
    event: Mapping[str, Any] | None,
) -> ReplayFrame:
    metadata = {item.position_id: item for item in state.position_metadata}
    blockers: dict[str, tuple[str, ...]] = {}
    for position in state.positions:
        item_metadata = metadata[position.position_id]
        if (
            item_metadata.stack_group_id is None
            or item_metadata.depth is None
            or position.occupant_vehicle_id is None
        ):
            blockers[position.position_id] = ()
            continue
        shallower = tuple(
            candidate.occupant_vehicle_id
            for candidate in state.positions
            if candidate.occupant_vehicle_id is not None
            and metadata[candidate.position_id].stack_group_id == item_metadata.stack_group_id
            and cast(int, metadata[candidate.position_id].depth) < item_metadata.depth
        )
        blockers[position.position_id] = shallower
    positions = tuple(
        ReplayPositionView(
            position_id=item.position_id,
            position_kind=item.position_kind.value,
            stack_group_id=metadata[item.position_id].stack_group_id,
            depth=metadata[item.position_id].depth,
            occupant_vehicle_id=item.occupant_vehicle_id,
            physically_available=item.physically_available,
            assignable=item.assignable,
            blocker_vehicle_ids=blockers[item.position_id],
        )
        for item in sorted(state.positions, key=lambda value: value.position_id)
    )
    vehicles = tuple(
        ReplayVehicleView(
            anonymous_vehicle_id=item.anonymous_vehicle_id,
            location_kind=item.location_state.kind.value,
            position_id=item.location_state.position_id,
            arrival_status=item.arrival_status.value,
            departure_status=item.departure_status.value,
            manual_status=item.manual_status.value,
        )
        for item in sorted(state.vehicles, key=lambda value: value.anonymous_vehicle_id)
    )
    warnings: list[str] = []
    if any(item.location_state.kind is LocationKind.POSITION_UNCERTAIN for item in state.vehicles):
        warnings.append("POSITION_UNKNOWN")
    if any(item.manual_status is not ManualStatus.NONE for item in state.vehicles):
        warnings.append("MANUAL_INTERVENTION")
    if any(item.status is ActionStatus.FAILED for item in state.actions):
        warnings.append("ACTION_FAILURE_RETAINED")
    active_actions = tuple(
        ReplayActionView(
            action_id=item.action_id,
            transaction_id=item.transaction_id,
            action_type=item.action_type.value,
            status=item.status.value,
            anonymous_vehicle_id=item.anonymous_vehicle_id,
            origin_position_id=item.origin_position_id,
            destination_position_id=item.destination_position_id,
            destination_exit_id=item.destination_exit_id,
            distance_m=item.distance_m,
            modeled_duration_s=item.modeled_duration_s,
            executor_units=item.executor_units,
            channel_zone_ids=item.channel_zone_ids,
            failure_reason=item.failure_reason,
        )
        for item in sorted(state.actions, key=lambda value: value.action_id)
        if item.status
        in {
            ActionStatus.ACCEPTED,
            ActionStatus.WAITING_FOR_RESOURCES,
            ActionStatus.STARTED,
        }
    )
    return ReplayFrame(
        run_id=state.run_id,
        scenario_id=state.scenario_id,
        sequence_no=state.sequence_no,
        sim_time_s=state.sim_time_s,
        event_id=None if event is None else cast(str, event["event_id"]),
        event_type=None if event is None else cast(str, event["event_type"]),
        positions=positions,
        vehicles=vehicles,
        reserved_position_ids=tuple(sorted({item.position_id for item in state.reservations})),
        active_actions=active_actions,
        transaction_states=tuple(
            (item.transaction_id, item.status.value)
            for item in sorted(state.transactions, key=lambda value: value.transaction_id)
        ),
        reservation_count=len(state.reservations),
        active_action_count=len(active_actions),
        transaction_count=len(state.transactions),
        pending_request_count=len(state.pending_requests),
        executor_used=state.executor_resource.used,
        executor_capacity=state.executor_resource.capacity,
        channel_zone_usage=tuple(
            (item.channel_zone_id, item.used, item.capacity)
            for item in state.channel_zone_resources
        ),
        warnings=tuple(warnings),
    )


def frame_at(index: ReplayIndex, sequence_no: int) -> ReplayFrame:
    """Project one frame from the shortest checkpointed event prefix."""

    if not index.first_sequence_no <= sequence_no <= index.last_sequence_no:
        raise IndexError("sequence_no is outside the replay index")
    checkpoint = max(
        (item for item in index._checkpoints if item.sequence_no <= sequence_no),
        key=lambda item: item.sequence_no,
    )
    state = checkpoint
    for event in index._events[checkpoint.sequence_no : sequence_no]:
        state = apply_event(state, event)
    selected_event: Mapping[str, Any] | None = (
        None if sequence_no == 0 else index._events[sequence_no - 1]
    )
    return _frame_from_state(state, selected_event)


_EVENT_CATEGORIES = {
    "ASSIGN_RECOMMENDED": "recommendation",
    "ACTION_RECOMMENDED": "recommendation",
    "ASSIGNMENT_ACCEPTED": "acceptance",
    "ACTION_ACCEPTED": "acceptance",
    "WAIT_DECIDED": "wait",
    "ACTION_WAITING_FOR_RESOURCES": "resource_wait",
    "ACTION_STARTED": "action_start",
    "ACTION_COMPLETED": "action_complete",
    "ACTION_FAILED_KNOWN_POSITION": "failure",
    "ACTION_FAILED_POSITION_UNKNOWN": "failure",
    "POSITION_RECONCILED": "reconciliation",
    "TRANSACTION_RECONCILED": "reconciliation",
    "RELOCATION_TRANSACTION_CREATED": "transaction",
    "TRANSACTION_STAGE_ADVANCED": "transaction",
    "TRANSACTION_CANCELLED_BEFORE_EXECUTION": "transaction",
    "FALLBACK_USED": "fallback",
    "MANUAL_INTERVENTION_REQUESTED": "manual",
    "MANUAL_STATUS_CHANGED": "manual",
    "REJECT_DECIDED": "failure",
    "ABORTED_BEFORE_START": "failure",
}


def _safe_text(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _event_action(event: Mapping[str, Any]) -> ReplayActionView | None:
    action = cast(Mapping[str, Any] | None, event.get("action"))
    if action is None:
        return None
    return ReplayActionView(
        action_id=cast(str, action["action_id"]),
        transaction_id=cast(str | None, action["transaction_id"]),
        action_type=cast(str, action["action_type"]),
        status=cast(str, action["status"]),
        anonymous_vehicle_id=cast(str, action["anonymous_vehicle_id"]),
        origin_position_id=cast(str | None, action["origin_position_id"]),
        destination_position_id=cast(str | None, action["destination_position_id"]),
        destination_exit_id=cast(str | None, action["destination_exit_id"]),
        distance_m=float(action["distance_m"]),
        modeled_duration_s=int(action["modeled_duration_s"]),
        executor_units=int(action["executor_units"]),
        channel_zone_ids=tuple(cast(Sequence[str], action["channel_zone_ids"])),
        failure_reason=_safe_text(action.get("failure_reason")),
    )


def _event_detail_items(
    event: Mapping[str, Any],
    action: ReplayActionView | None,
) -> tuple[tuple[str, str], ...]:
    """Expose only approved audit fields; never echo arbitrary payload values."""

    items: list[tuple[str, str]] = []
    if action is not None:
        items.extend(
            (
                ("action_id", action.action_id),
                ("action_type", action.action_type),
                ("action_status", action.status),
                ("distance_m", f"{action.distance_m:.3f}"),
                ("modeled_duration_s", str(action.modeled_duration_s)),
            )
        )
        if action.origin_position_id:
            items.append(("origin_position_id", action.origin_position_id))
        if action.destination_position_id:
            items.append(("destination_position_id", action.destination_position_id))
        if action.destination_exit_id:
            items.append(("destination_exit_id", action.destination_exit_id))
        if action.failure_reason:
            items.append(("failure_reason", action.failure_reason))
    transaction = cast(Mapping[str, Any] | None, event.get("transaction"))
    if transaction is not None and _safe_text(transaction.get("status")):
        items.append(("transaction_status", cast(str, transaction["status"])))
    payload = cast(Mapping[str, Any], event.get("payload") or {})
    request_id = _safe_text(payload.get("request_id"))
    if request_id:
        items.append(("request_id", request_id))
    confirmed = cast(Mapping[str, Any] | None, payload.get("confirmed_location_state"))
    if confirmed is not None:
        kind = _safe_text(confirmed.get("kind"))
        position_id = _safe_text(confirmed.get("position_id"))
        if kind:
            items.append(("confirmed_location_kind", kind))
        if position_id:
            items.append(("confirmed_position_id", position_id))
    manual_status = _safe_text(payload.get("manual_status"))
    if manual_status:
        items.append(("manual_status", manual_status))
    fallback = cast(Mapping[str, Any] | None, payload.get("fallback_record"))
    if fallback is not None:
        for key in (
            "original_method",
            "original_solver_status",
            "reason",
            "used_strategy",
            "result_validation_status",
        ):
            value = _safe_text(fallback.get(key))
            if value:
                items.append((f"fallback_{key}", value))
        elapsed_s = fallback.get("elapsed_s")
        if isinstance(elapsed_s, int | float):
            items.append(("fallback_elapsed_s", f"{float(elapsed_s):.3f}"))
    return tuple(items)


def _event_summary(
    event_type: str,
    action: ReplayActionView | None,
    transaction_status: str | None,
) -> str:
    if action is not None:
        return f"{action.action_type} · {action.status} · {action.anonymous_vehicle_id}"
    if transaction_status:
        return f"{event_type} · {transaction_status}"
    return event_type


def build_replay_timeline(bundle: ValidatedDemoBundle) -> ReplayTimeline:
    """Build a sanitized event catalog without exposing raw events or scenario truth."""

    views: list[ReplayEventView] = []
    for event in bundle._events:
        event_type = cast(str, event["event_type"])
        action = _event_action(event)
        transaction = cast(Mapping[str, Any] | None, event.get("transaction"))
        transaction_status = None if transaction is None else _safe_text(transaction.get("status"))
        category = _EVENT_CATEGORIES.get(event_type, "request_or_signal")
        warnings: list[str] = []
        if event_type == "ACTION_FAILED_POSITION_UNKNOWN":
            warnings.append("POSITION_UNKNOWN")
        if category == "manual":
            warnings.append("MANUAL_INTERVENTION")
        if category == "fallback":
            warnings.append("FALLBACK_USED")
        views.append(
            ReplayEventView(
                sequence_no=int(event["sequence_no"]),
                sim_time_s=int(event["sim_time_s"]),
                event_id=cast(str, event["event_id"]),
                event_type=event_type,
                category=category,
                anonymous_vehicle_id=cast(str | None, event["anonymous_vehicle_id"]),
                transaction_id=cast(str | None, event["transaction_id"]),
                transaction_status=transaction_status,
                action=action,
                summary=_event_summary(event_type, action, transaction_status),
                detail_items=_event_detail_items(event, action),
                warning_codes=tuple(warnings),
            )
        )
    return ReplayTimeline(
        run_id=bundle.run_id,
        scenario_id=bundle.scenario_id,
        events=tuple(views),
        event_types=tuple(sorted({item.event_type for item in views})),
        transaction_ids=tuple(
            sorted({item.transaction_id for item in views if item.transaction_id is not None})
        ),
    )


def decision_audit(bundle: ValidatedDemoBundle, decision_id: str) -> DecisionAuditView:
    """Return a sanitized immutable explanation for one saved decision."""

    try:
        decision = next(item for item in bundle._decisions if item["decision_id"] == decision_id)
    except StopIteration as exc:
        raise KeyError(f"unknown decision_id: {decision_id}") from exc
    fallback = cast(Mapping[str, Any] | None, decision["fallback_record"])
    generation = cast(Mapping[str, Any] | None, decision["candidate_generation"])
    timing = cast(Mapping[str, Any], decision["timing"])
    target_request_id = cast(str, decision["target_request_id"])
    trigger = next(
        (
            event
            for event in bundle._events
            if cast(Mapping[str, Any], event.get("payload") or {})
            .get("pending_request", {})
            .get("request_id")
            == target_request_id
        ),
        None,
    )
    solver_status = cast(str, decision["solver_status"])
    if solver_status == "TIME_LIMIT_FEASIBLE":
        incumbent_status = "SAVED_VALIDATED_INCUMBENT"
    elif solver_status == "OPTIMAL":
        incumbent_status = "NOT_APPLICABLE_OPTIMAL"
    elif solver_status == "TIME_LIMIT_NO_FEASIBLE":
        incumbent_status = "NO_FEASIBLE_INCUMBENT"
    else:
        incumbent_status = "NOT_REPORTED_BY_SAVED_RESULT"
    generation_counts = (
        ()
        if generation is None
        else tuple(
            (key, int(generation[key]))
            for key in (
                "requests_seen",
                "requests_kept",
                "positions_seen",
                "positions_kept",
                "buffer_matchings_seen",
                "buffer_matchings_kept",
                "action_plans_kept",
            )
        )
    )
    return DecisionAuditView(
        decision_id=cast(str, decision["decision_id"]),
        request_id=cast(str, decision["request_id"]),
        algorithm_id=cast(str, decision["algorithm_id"]),
        algorithm_version=cast(str, decision["algorithm_version"]),
        target_request_id=target_request_id,
        target_anonymous_vehicle_id=cast(str, decision["target_anonymous_vehicle_id"]),
        primary_decision=cast(str, decision["primary_decision"]),
        solver_status=solver_status,
        validation_status=cast(str, decision["validation_status"]),
        config_sha256=cast(str, decision["config_sha256"]),
        layout_sha256=cast(str, decision["layout_sha256"]),
        visible_snapshot_sha256=cast(str, decision["visible_snapshot_sha256"]),
        input_model_sha256=cast(str | None, decision["input_model_sha256"]),
        trigger_event_id=None if trigger is None else cast(str, trigger["event_id"]),
        trigger_event_type=None if trigger is None else cast(str, trigger["event_type"]),
        trigger_sim_time_s=None if trigger is None else int(trigger["sim_time_s"]),
        snapshot_content_status="HASH_ONLY_NOT_PERSISTED",
        explanation_codes=tuple(cast(Sequence[str], decision["explanation_codes"])),
        actions=tuple(
            DecisionActionView(
                action_id=item["action_id"],
                action_type=item["action_type"],
                anonymous_vehicle_id=item["anonymous_vehicle_id"],
                origin_position_id=item["origin_position_id"],
                destination_position_id=item["destination_position_id"],
                destination_exit_id=item["destination_exit_id"],
                distance_m=float(item["distance_m"]),
                modeled_duration_s=item["modeled_duration_s"],
            )
            for item in cast(Sequence[Mapping[str, Any]], decision["recommended_actions"])
        ),
        used_fallback=fallback is not None,
        fallback_original_method=(
            None if fallback is None else cast(str, fallback["original_method"])
        ),
        fallback_original_solver_status=(
            None if fallback is None else cast(str, fallback["original_solver_status"])
        ),
        fallback_reason=None if fallback is None else cast(str, fallback["reason"]),
        fallback_strategy=None if fallback is None else cast(str, fallback["used_strategy"]),
        fallback_elapsed_s=None if fallback is None else float(fallback["elapsed_s"]),
        fallback_validation_status=(
            None if fallback is None else cast(str, fallback["result_validation_status"])
        ),
        incumbent_status=incumbent_status,
        end_to_end_s=float(timing["end_to_end_s"]),
        validation_and_modeling_s=float(timing["validation_and_modeling_s"]),
        solver_s=float(timing["solver_s"]),
        postsolve_validation_s=float(timing["postsolve_validation_s"]),
        minimum_logging_s=float(timing["minimum_logging_s"]),
        solver_time_limit_s=float(timing["solver_time_limit_s"]),
        candidate_generation=generation_counts,
        candidate_truncation_reasons=(
            ()
            if generation is None
            else tuple(cast(Sequence[str], generation["truncation_reasons"]))
        ),
    )


def metric_summary(bundle: ValidatedDemoBundle, run_id: str) -> MetricSummaryView:
    """Expose saved metric records without recomputing or changing frozen definitions."""

    if run_id != bundle.run_id:
        raise KeyError(f"unknown run_id: {run_id}")
    aggregates: list[MetricValueView] = []
    request_records: list[Mapping[str, Any]] = []
    request_groups: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    not_applicable = 0
    for metric in bundle._metrics:
        if metric["value"] is None:
            not_applicable += 1
        if metric["record_level"] in {"instantaneous", "run_aggregate"}:
            dimensions = cast(Mapping[str, str | int], metric["dimensions"])
            aggregates.append(
                MetricValueView(
                    metric_name=cast(str, metric["metric_name"]),
                    value=cast(float | None, metric["value"]),
                    unit=cast(str, metric["unit"]),
                    numerator=cast(float | None, metric["numerator"]),
                    denominator=cast(float | None, metric["denominator"]),
                    not_applicable_reason=cast(str | None, metric["not_applicable_reason"]),
                    dimensions=tuple(sorted(dimensions.items())),
                    record_level=cast(str, metric["record_level"]),
                    window_start_s=int(metric["window_start_s"]),
                    window_end_s=int(metric["window_end_s"]),
                    measured_at_s=cast(int | None, metric["measured_at_s"]),
                )
            )
        elif metric["record_level"] == "request_observation":
            request_records.append(metric)
            request_groups[cast(str, metric["metric_name"])].append(metric)
    aggregates.sort(key=lambda item: item.metric_name)
    request_summaries: list[RequestMetricSummaryView] = []
    for metric_name, records in sorted(request_groups.items()):
        completed_values = [
            float(item["value"])
            for item in records
            if item["event_observed"] is True and item["value"] is not None
        ]
        request_summaries.append(
            RequestMetricSummaryView(
                metric_name=metric_name,
                unit=cast(str, records[0]["unit"]),
                observation_count=len(records),
                completed_count=len(completed_values),
                censored_count=sum(item["event_observed"] is False for item in records),
                pending_count=sum(item["pending_at_horizon"] is True for item in records),
                completed_only_mean=(
                    None if not completed_values else float(fmean(completed_values))
                ),
                observed_lower_bound_count=sum(
                    item["observed_wait_lower_bound_s"] is not None for item in records
                ),
            )
        )
    window_start_s = int(bundle._metrics[0]["window_start_s"]) if bundle._metrics else 0
    window_end_s = int(bundle._metrics[0]["window_end_s"]) if bundle._metrics else 0
    return MetricSummaryView(
        run_id=bundle.run_id,
        scenario_id=bundle.scenario_id,
        algorithm_id=bundle.algorithm_id,
        algorithm_version=bundle.algorithm_version,
        window_start_s=window_start_s,
        window_end_s=window_end_s,
        aggregates=tuple(aggregates),
        request_summaries=tuple(request_summaries),
        request_observation_count=len(request_records),
        censored_request_count=sum(item["pending_at_horizon"] is True for item in request_records),
        pending_at_horizon_count=sum(
            item["pending_at_horizon"] is True for item in request_records
        ),
        unobserved_request_count=sum(item["event_observed"] is False for item in request_records),
        not_applicable_metric_count=not_applicable,
    )
