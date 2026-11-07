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
    """Explicit trust boundary and bounded-resource policy for one import."""

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
    """One sanitized import validation result."""

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
    """Complete fail-closed report with no raw values or absolute paths."""

    accepted: bool
    source_label: str
    file_count: int
    total_bytes: int
    record_count: int
    checks: tuple[ValidationCheck, ...]

    @property
    def failures(self) -> tuple[ValidationCheck, ...]:
        """Return only rejected checks."""

        return tuple(item for item in self.checks if item.status == "failed")


class ImportRejectedError(ValueError):
    """Raised when a caller requests loading after validation rejected a bundle."""

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
    """Validated immutable bundle; truth-bearing scenario data is deliberately absent."""

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
class ReplayFrame:
    """One deterministic frame projected only from an event-log prefix."""

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
    """Opaque checkpoint index; no simulator, truth store, or solver object is retained."""

    run_id: str
    scenario_id: str
    first_sequence_no: int
    last_sequence_no: int
    checkpoint_interval: int
    _events: tuple[Mapping[str, Any], ...]
    _checkpoints: tuple[AuthoritativeState, ...]


@dataclass(frozen=True, slots=True)
class ReplayActionView:
    """Sanitized action fields attached to one saved event."""

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
class ReplayEventView:
    """Whitelisted event detail with no raw payload or future truth."""

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
    """Deterministic event catalog used for navigation and filtering."""

    run_id: str
    scenario_id: str
    events: tuple[ReplayEventView, ...]
    event_types: tuple[str, ...]
    transaction_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DecisionActionView:
    action_id: str
    action_type: str
    anonymous_vehicle_id: str
    origin_position_id: str | None
    destination_position_id: str | None
    destination_exit_id: str | None
    distance_m: float
    modeled_duration_s: int


@dataclass(frozen=True, slots=True)
class DecisionAuditView:
    decision_id: str
    request_id: str
    algorithm_id: str
    algorithm_version: str
    target_request_id: str
    target_anonymous_vehicle_id: str
    primary_decision: str
    solver_status: str
    validation_status: str
    config_sha256: str
    layout_sha256: str
    visible_snapshot_sha256: str
    input_model_sha256: str | None
    trigger_event_id: str | None
    trigger_event_type: str | None
    trigger_sim_time_s: int | None
    snapshot_content_status: str
    explanation_codes: tuple[str, ...]
    actions: tuple[DecisionActionView, ...]
    used_fallback: bool
    fallback_original_method: str | None
    fallback_original_solver_status: str | None
    fallback_reason: str | None
    fallback_strategy: str | None
    fallback_elapsed_s: float | None
    fallback_validation_status: str | None
    incumbent_status: str
    end_to_end_s: float
    validation_and_modeling_s: float
    solver_s: float
    postsolve_validation_s: float
    minimum_logging_s: float
    solver_time_limit_s: float
    candidate_generation: tuple[tuple[str, int], ...]
    candidate_truncation_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MetricValueView:
    metric_name: str
    value: float | None
    unit: str
    numerator: float | None
    denominator: float | None
    not_applicable_reason: str | None
    dimensions: tuple[tuple[str, str | int], ...]
    record_level: str
    window_start_s: int
    window_end_s: int
    measured_at_s: int | None


@dataclass(frozen=True, slots=True)
class RequestMetricSummaryView:
    """Completed-only descriptive value plus explicit censoring counts."""

    metric_name: str
    unit: str
    observation_count: int
    completed_count: int
    censored_count: int
    pending_count: int
    completed_only_mean: float | None
    observed_lower_bound_count: int


@dataclass(frozen=True, slots=True)
class MetricSummaryView:
    run_id: str
    scenario_id: str
    algorithm_id: str
    algorithm_version: str
    window_start_s: int
    window_end_s: int
    aggregates: tuple[MetricValueView, ...]
    request_summaries: tuple[RequestMetricSummaryView, ...]
    request_observation_count: int
    censored_request_count: int
    pending_at_horizon_count: int
    unobserved_request_count: int
    not_applicable_metric_count: int


@dataclass(frozen=True, slots=True)
class ComparisonRunView:
    """Whitelisted evidence for one saved member of a fair pair."""

    run_id: str
    scenario_id: str
    algorithm_id: str
    algorithm_version: str
    git_commit: str
    random_seed: int
    run_status: str
    input_data_sha256: str
    config_sha256: str
    fallback_count: int
    fallback_rate: float
    pending_request_count_at_horizon: int
    hard_deadline_violation_count: int
    state_invariant_violation_count: int


@dataclass(frozen=True, slots=True)
class ComparisonMetricView:
    """One saved candidate-minus-baseline paired statistic."""

    metric_name: str
    unit: str
    baseline_value: float
    candidate_value: float
    paired_difference: float
    sample_n: int
    completed_only: bool
    censoring_rate: bool


@dataclass(frozen=True, slots=True)
class ComparisonEvidenceView:
    """Fail-closed D4 projection of the saved C6 formal evidence."""

    source_kind: str
    purpose: str
    pair_key_status: str
    pair_key: tuple[tuple[str, str | int], ...]
    baseline: ComparisonRunView
    candidate: ComparisonRunView
    metrics: tuple[ComparisonMetricView, ...]
    formal_pair_count: int
    required_formal_pair_count: int
    formal_seed_count: int
    required_formal_seed_count: int
    research_gate_status: str
    rolling_default_enabled: bool
    ten_second_budget_role: str
    artifact_sha256: tuple[tuple[str, str], ...]
