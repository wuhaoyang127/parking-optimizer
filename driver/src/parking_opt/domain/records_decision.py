"""Immutable decision request, timing, fallback, and result records."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from parking_opt.domain.enums import PrimaryDecision, SolverStatus, ValidationStatus
from parking_opt.domain.records import _require_id, _require_non_negative, freeze_mapping
from parking_opt.domain.records_claims import Action, RelocationTransaction
from parking_opt.domain.records_resources import ObservedSnapshot


@dataclass(frozen=True, slots=True)
class DecisionRequest:
    """Immutable policy boundary with no path back to simulator truth."""

    request_id: str
    algorithm_id: str
    algorithm_version: str
    trigger_event_id: str
    trigger_event_type: str
    trigger_request_id: str | None
    trigger_anonymous_vehicle_id: str | None
    decision_time_s: int
    layout: Mapping[str, Any]
    approved_config: Mapping[str, Any]
    observed_snapshot: ObservedSnapshot
    config_sha256: str
    layout_sha256: str
    visible_snapshot_sha256: str
    decision_target_s: float
    decision_deadline_s: float

    def __post_init__(self) -> None:
        for field_name, value in (
            ("request_id", self.request_id),
            ("algorithm_id", self.algorithm_id),
            ("algorithm_version", self.algorithm_version),
            ("trigger_event_id", self.trigger_event_id),
        ):
            _require_id(field_name, value)
        _require_non_negative("decision_time_s", self.decision_time_s)
        object.__setattr__(self, "layout", freeze_mapping(self.layout))
        object.__setattr__(self, "approved_config", freeze_mapping(self.approved_config))
        if not 0 < self.decision_target_s <= self.decision_deadline_s:
            raise ValueError("decision target must be positive and no greater than deadline")


@dataclass(frozen=True, slots=True)
class DecisionTiming:
    """Separated timing fields required by the v1 decision result."""

    end_to_end_s: float
    validation_and_modeling_s: float
    solver_s: float
    postsolve_validation_s: float
    minimum_logging_s: float
    solver_time_limit_s: float

    def __post_init__(self) -> None:
        for field_name, value in (
            ("end_to_end_s", self.end_to_end_s),
            ("validation_and_modeling_s", self.validation_and_modeling_s),
            ("solver_s", self.solver_s),
            ("postsolve_validation_s", self.postsolve_validation_s),
            ("minimum_logging_s", self.minimum_logging_s),
            ("solver_time_limit_s", self.solver_time_limit_s),
        ):
            _require_non_negative(field_name, value)


@dataclass(frozen=True, slots=True)
class FallbackRecord:
    """Explicit provenance for a deterministic fallback result."""

    original_method: str
    original_solver_status: SolverStatus
    reason: str
    used_strategy: str
    elapsed_s: float
    result_validation_status: ValidationStatus

    def __post_init__(self) -> None:
        _require_id("original_method", self.original_method)
        _require_id("used_strategy", self.used_strategy)
        if not self.reason:
            raise ValueError("fallback reason must be non-empty")
        _require_non_negative("elapsed_s", self.elapsed_s)


@dataclass(frozen=True, slots=True)
class CandidateGenerationRecord:
    """Bounded rolling-candidate counts and explicit truncation provenance."""

    requests_seen: int
    requests_kept: int
    positions_seen: int
    positions_kept: int
    buffer_matchings_seen: int
    buffer_matchings_kept: int
    action_plans_kept: int
    truncation_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name, value in (
            ("requests_seen", self.requests_seen),
            ("requests_kept", self.requests_kept),
            ("positions_seen", self.positions_seen),
            ("positions_kept", self.positions_kept),
            ("buffer_matchings_seen", self.buffer_matchings_seen),
            ("buffer_matchings_kept", self.buffer_matchings_kept),
            ("action_plans_kept", self.action_plans_kept),
        ):
            _require_non_negative(field_name, value)
        if len(set(self.truncation_reasons)) != len(self.truncation_reasons):
            raise ValueError("truncation_reasons must be unique")
        if any(not item or len(item) > 128 for item in self.truncation_reasons):
            raise ValueError("truncation reasons must contain 1 to 128 characters")


@dataclass(frozen=True, slots=True)
class DecisionResult:
    """Immutable candidate result; it never changes authoritative state."""

    decision_id: str
    request_id: str
    algorithm_id: str
    algorithm_version: str
    config_sha256: str
    layout_sha256: str
    visible_snapshot_sha256: str
    input_model_sha256: str | None
    target_request_id: str
    target_anonymous_vehicle_id: str
    primary_decision: PrimaryDecision
    recommended_actions: tuple[Action, ...]
    candidate_transaction: RelocationTransaction | None
    solver_status: SolverStatus
    fallback_record: FallbackRecord | None
    validation_status: ValidationStatus
    explanation_codes: tuple[str, ...]
    timing: DecisionTiming
    candidate_generation: CandidateGenerationRecord | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("decision_id", self.decision_id),
            ("request_id", self.request_id),
            ("algorithm_id", self.algorithm_id),
            ("algorithm_version", self.algorithm_version),
            ("target_request_id", self.target_request_id),
            ("target_anonymous_vehicle_id", self.target_anonymous_vehicle_id),
        ):
            _require_id(field_name, value)
        if self.primary_decision is PrimaryDecision.RECOMMEND_ACTIONS:
            if not self.recommended_actions:
                raise ValueError("RECOMMEND_ACTIONS requires at least one action")
        elif self.recommended_actions or self.candidate_transaction is not None:
            raise ValueError("non-action decisions cannot contain actions or a transaction")


DecisionResultStatus = DecisionResult
