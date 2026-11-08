"""Type definitions and config expansion for the deterministic engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from parking_opt.domain.state import AuthoritativeState


@dataclass(order=True, slots=True)
class _ScheduledItem:
    time_s: int
    priority: int
    stable_order: int
    kind: str = field(compare=False)
    payload: Any = field(compare=False)


@dataclass(frozen=True, slots=True)
class _DecisionTrigger:
    event_id: str
    event_type: str
    request_id: str | None
    vehicle_id: str | None


@dataclass(frozen=True, slots=True)
class SimulationResult:
    """Replayable C3 simulation result and its isolated decision records."""

    initial_state: AuthoritativeState
    final_state: AuthoritativeState
    events: tuple[dict[str, Any], ...]
    decisions: tuple[dict[str, Any], ...]
    event_log_path: Path | None


def approved_config_from_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    """Expand the scenario config into the frozen v1 decision configuration."""

    source = scenario["config"]
    return {
        "recoverability_policy": source["recoverability_policy"],
        "rolling_enabled": False,
        "arrival_wait_capacity": source["arrival_wait_capacity"],
        "max_arrival_wait_s": source["max_arrival_wait_s"],
        "max_departure_wait_s": source["max_departure_wait_s"],
        "use_soft_departure_information": False,
        "rolling_window_s": 900,
        "optimization_budget_s": 1.0,
        "fallback_target_s": source["fallback_target_s"],
        "minimum_logging_reserve_s": source["minimum_logging_reserve_s"],
        "max_requests_per_solve": 12,
        "max_positions_per_arrival": 8,
        "max_buffer_matchings_per_departure": 4,
        "max_action_plans_total": 64,
        "max_soft_future_records": 20,
        "buffer_count": source["buffer_count"],
        "relocation_executor_capacity": source["relocation_executor_capacity"],
        "executor_type": source["executor_type"],
        "relocation_setup_s": source["relocation_setup_s"],
        "relocation_speed_mps": source["relocation_speed_mps"],
        "active_buffer_position_ids": list(source["active_buffer_position_ids"]),
    }
