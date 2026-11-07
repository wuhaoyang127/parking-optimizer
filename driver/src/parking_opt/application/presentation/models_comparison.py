"""Comparison and decision-audit DTOs for the read-only presentation boundary."""

from __future__ import annotations

from dataclasses import dataclass


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
