"""Type definitions for audited navigation replanning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from parking_opt.api.models import ReplanDecision, Route
from parking_opt.api.sessions import JourneyRecord


@dataclass(frozen=True, slots=True)
class ReplanResult:
    journey: JourneyRecord
    decision: ReplanDecision


@dataclass(frozen=True, slots=True)
class NavigationRecovery:
    current_route: Route
    current_node_id: str
    last_replan: ReplanDecision | None = None


@dataclass(frozen=True, slots=True)
class _Replay:
    payload_sha256: str
    result: ReplanResult


@dataclass(frozen=True, slots=True)
class _DemoReplay:
    request_sha256: str
    result: ReplanResult


ReplanTrigger = Literal["deviation", "cost_update", "manual_refresh"]
ReplanOutcome = Literal["success", "warning", "failed"]
DriverDemoAction = Literal["simulate_deviation", "simulate_cost_update"]
