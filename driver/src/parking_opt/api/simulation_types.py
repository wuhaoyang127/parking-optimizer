"""Type definitions for the deterministic management-level simulation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from parking_opt.api.models import SimulationEvent


@dataclass(frozen=True, slots=True)
class SimulationCommand:
    simulation_time_s: int
    priority: int
    sequence_hint: int
    event_type: str
    vehicle_id: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SimulationSummary:
    vehicle_count: int
    occupied_space_count: int
    waiting_vehicle_count: int
    relocation_count: int
    failure_count: int
    final_state_sha256: str


@dataclass(frozen=True, slots=True)
class SimulationRun:
    seed: int
    events: tuple[SimulationEvent, ...]
    summary: SimulationSummary


class ReplayMismatchError(ValueError):
    """Recorded event hashes or ordering do not reproduce the same state."""
