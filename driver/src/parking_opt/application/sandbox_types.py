"""Type definitions for the synthetic in-memory sandbox."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from parking_opt.domain.records import DecisionRequest, DecisionResult
from parking_opt.domain.state import AuthoritativeState
from parking_opt.layout.model import Layout

_SCHEMA_VERSION = "1.0.0"
_ALGORITHM_ID = "online-rule-v1"
_ALGORITHM_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class SandboxTemplate:
    """One validated synthetic layout and its crowded initial state."""

    template_id: str
    label: str
    note: str
    layout: Layout
    initial_state: AuthoritativeState


@dataclass(frozen=True, slots=True)
class CandidateExplanation:
    """Safe presentation projection of one online-rule arrival candidate."""

    rank: int | None
    position_id: str
    stack_group_id: str
    depth: int
    feasible: bool
    reason_codes: tuple[str, ...]
    distance_m: float | None
    incremental_unrecoverable_exposure: int | None
    incremental_blocked_vehicle_count: int | None
    remaining_one_step_assignable_capacity: int | None
    departure_order_mismatch_count: int | None
    score: tuple[object, ...] | None


@dataclass(frozen=True, slots=True)
class SandboxDecision:
    """One real online-rule decision plus its safe explanatory projection."""

    decision_kind: str
    input_state: AuthoritativeState
    request: DecisionRequest
    result: DecisionResult
    candidates: tuple[CandidateExplanation, ...]
    selected_position_id: str | None
    nearest_feasible_position_id: str | None
    story_steps: tuple[str, ...]
