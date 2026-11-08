"""Type definitions and selection mapping for the bounded rolling candidate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from parking_opt.contracts.canonical import canonical_sha256
from parking_opt.domain.conversion import action_to_mapping, transaction_to_mapping
from parking_opt.domain.records import CandidateGenerationRecord
from parking_opt.strategies._selection import Selection

_HARD_MAX_REQUESTS = 12
_HARD_MAX_POSITIONS = 8
_HARD_MAX_BUFFER_MATCHINGS = 4
_HARD_MAX_PLANS = 64
_HARD_MAX_SOFT_RECORDS = 20


@dataclass(frozen=True, slots=True)
class RollingObjective:
    """Frozen R1a-R5b window objective in natural units."""

    overdue_departures_unfinished: int
    departures_unfinished: int
    active_transactions_unfinished: int
    admitted_arrivals_unfinished: int
    arrivals_completed: int
    waiting_s: int
    relocation_legs: int
    relocation_distance_m: float
    non_relocation_distance_m: float
    blocked_exposure_vehicle_s: int
    reservation_position_s: int

    def key(self) -> tuple[int | float, ...]:
        return (
            self.overdue_departures_unfinished,
            self.departures_unfinished,
            self.active_transactions_unfinished,
            self.admitted_arrivals_unfinished,
            -self.arrivals_completed,
            self.waiting_s,
            self.relocation_legs,
            self.relocation_distance_m,
            self.non_relocation_distance_m,
            self.blocked_exposure_vehicle_s,
            self.reservation_position_s,
        )

    def to_mapping(self) -> dict[str, int | float]:
        return {
            "overdue_departures_unfinished": self.overdue_departures_unfinished,
            "departures_unfinished": self.departures_unfinished,
            "active_transactions_unfinished": self.active_transactions_unfinished,
            "admitted_arrivals_unfinished": self.admitted_arrivals_unfinished,
            "arrivals_completed": self.arrivals_completed,
            "waiting_s": self.waiting_s,
            "relocation_legs": self.relocation_legs,
            "relocation_distance_m": self.relocation_distance_m,
            "non_relocation_distance_m": self.non_relocation_distance_m,
            "blocked_exposure_vehicle_s": self.blocked_exposure_vehicle_s,
            "reservation_position_s": self.reservation_position_s,
        }


@dataclass(frozen=True, slots=True)
class WindowPlan:
    """One complete disposition for every retained visible request."""

    plan_id: str
    selections: tuple[Selection, ...]
    objective: RollingObjective
    is_warm_start: bool = False

    @property
    def first_selection(self) -> Selection:
        return self.selections[0]


@dataclass(frozen=True, slots=True)
class BoundedRollingInput:
    """Immutable candidate set and audit evidence supplied to the selector."""

    input_model_sha256: str
    retained_request_ids: tuple[str, ...]
    legal_soft_record_ids: tuple[str, ...]
    warm_start: WindowPlan
    plans: tuple[WindowPlan, ...]
    candidate_generation: CandidateGenerationRecord


def _selection_mapping(selection: Selection) -> dict[str, Any]:
    return {
        "target_request_id": selection.target.request_id,
        "target_anonymous_vehicle_id": selection.target.anonymous_vehicle_id,
        "primary_decision": selection.primary_decision.value,
        "recommended_actions": [action_to_mapping(item) for item in selection.actions],
        "candidate_transaction": (
            transaction_to_mapping(selection.transaction)
            if selection.transaction is not None
            else None
        ),
        "explanation_codes": list(selection.explanation_codes),
    }


def _selection_signature(selection: Selection) -> str:
    return canonical_sha256(_selection_mapping(selection))
