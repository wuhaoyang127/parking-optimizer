"""Immutable DTOs crossing the read-only presentation boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from parking_opt.domain.state import AuthoritativeState
from parking_opt.layout.model import Layout


@dataclass(frozen=True, slots=True)
class ImportPolicy:
    allowed_root: Path
    schema_dir: Path
    max_file_bytes: int = 32 * 1024 * 1024
    max_total_bytes: int = 128 * 1024 * 1024
    max_records: int = 250_000
    allow_symlinks: bool = False

    def __post_init__(self) -> None:
        if self.max_file_bytes < 1 or self.max_total_bytes < self.max_file_bytes:
            raise ValueError("import byte limits must be positive and consistently ordered")
        if self.max_records < 1:
            raise ValueError("max_records must be positive")


@dataclass(frozen=True, slots=True)
class ValidationCheck:
    stage: str
    status: str
    code: str
    artifact: str | None
    message: str
    json_pointer: str | None = None
    constraint_id: str | None = None
    fix_hint: str | None = None


@dataclass(frozen=True, slots=True)
class ImportValidationReport:
    accepted: bool
    source_label: str
    file_count: int
    total_bytes: int
    record_count: int
    checks: tuple[ValidationCheck, ...]

    @property
    def failures(self) -> tuple[ValidationCheck, ...]:
        return tuple(item for item in self.checks if item.status == "failed")


class ImportRejectedError(ValueError):
    def __init__(self, report: ImportValidationReport) -> None:
        self.report = report
        codes = ", ".join(item.code for item in report.failures) or "D1_IMPORT_REJECTED"
        super().__init__(f"demo bundle rejected: {codes}")


@dataclass(frozen=True, slots=True)
class FileDigest:
    artifact: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ValidatedDemoBundle:
    run_id: str
    scenario_id: str
    algorithm_id: str
    algorithm_version: str
    source_kind: str
    purpose: str
    layout: Layout
    manifest: Mapping[str, Any]
    file_digests: tuple[FileDigest, ...]
    event_count: int
    decision_count: int
    decision_ids: tuple[str, ...]
    metric_count: int
    _initial_state: AuthoritativeState
    _events: tuple[Mapping[str, Any], ...]
    _decisions: tuple[Mapping[str, Any], ...]
    _metrics: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class ReplayPositionView:
    position_id: str
    position_kind: str
    stack_group_id: str | None
    depth: int | None
    occupant_vehicle_id: str | None
    physically_available: bool
    assignable: bool
    blocker_vehicle_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReplayVehicleView:
    anonymous_vehicle_id: str
    location_kind: str
    position_id: str | None
    arrival_status: str
    departure_status: str
    manual_status: str


@dataclass(frozen=True, slots=True)
class ReplayActionView:
    action_id: str
    transaction_id: str | None
    action_type: str
    status: str
    anonymous_vehicle_id: str
    origin_position_id: str | None
    destination_position_id: str | None
    destination_exit_id: str | None
    distance_m: float
    modeled_duration_s: int
    executor_units: int
    channel_zone_ids: tuple[str, ...]
    failure_reason: str | None


@dataclass(frozen=True, slots=True)
class ReplayFrame:
    run_id: str
    scenario_id: str
    sequence_no: int
    sim_time_s: int
    event_id: str | None
    event_type: str | None
    positions: tuple[ReplayPositionView, ...]
    vehicles: tuple[ReplayVehicleView, ...]
    reserved_position_ids: tuple[str, ...]
    active_actions: tuple[ReplayActionView, ...]
    transaction_states: tuple[tuple[str, str], ...]
    reservation_count: int
    active_action_count: int
    transaction_count: int
    pending_request_count: int
    executor_used: int
    executor_capacity: int
    channel_zone_usage: tuple[tuple[str, int, int], ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReplayIndex:
    run_id: str
    scenario_id: str
    first_sequence_no: int
    last_sequence_no: int
    checkpoint_interval: int
    _events: tuple[Mapping[str, Any], ...]
    _checkpoints: tuple[AuthoritativeState, ...]


@dataclass(frozen=True, slots=True)
class ReplayEventView:
    sequence_no: int
    sim_time_s: int
    event_id: str
    event_type: str
    category: str
    anonymous_vehicle_id: str | None
    transaction_id: str | None
    transaction_status: str | None
    action: ReplayActionView | None
    summary: str
    detail_items: tuple[tuple[str, str], ...]
    warning_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReplayTimeline:
    run_id: str
    scenario_id: str
    events: tuple[ReplayEventView, ...]
    event_types: tuple[str, ...]
    transaction_ids: tuple[str, ...]


from parking_opt.application.presentation.models_comparison import ComparisonEvidenceView, ComparisonMetricView, ComparisonRunView, DecisionActionView, DecisionAuditView, MetricSummaryView, MetricValueView, RequestMetricSummaryView  # noqa: E402
