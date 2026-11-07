"""Frozen stage B synthetic demand generation with explicit seed partitions."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from parking_opt.contracts.canonical import canonical_sha256
from parking_opt.layout.model import Layout
from parking_opt.demand.scenario_helpers import (
    generate_arrival_events,
    load_experiment_protocol,
    validate_seed_partition,
)


class SeedPartition(StrEnum):
    """Pre-registered random-seed partitions."""

    DEVELOPMENT = "development"
    TUNING = "tuning"
    FORMAL_CORE = "formal_core"
    FORMAL_EXTENSION = "formal_extension"


@dataclass(frozen=True, slots=True)
class ScenarioGenerationResult:
    """Synthetic scenario plus reproducibility and realized-load evidence."""

    scenario: dict[str, Any]
    scenario_content_sha256: str
    event_truth_sha256: str
    realized_offered_load_ratio: float
    arrival_count: int
    seed_partition: SeedPartition
    soft_information_truncation_count: int


def generate_synthetic_scenario(
    *,
    layout: Layout,
    layout_family: str,
    load_level: str,
    seed: int,
    seed_partition: SeedPartition,
    protocol: dict[str, Any],
    recoverability_policy: str = "risk_accepting",
    relocation_executor_capacity: int = 1,
    arrival_wait_capacity: int = 10,
    max_arrival_wait_s: int = 300,
    max_departure_wait_s: int = 300,
    relocation_setup_s: float = 5.0,
    relocation_speed_mps: float = 1.0,
    minimum_logging_reserve_s: float = 0.02,
    cancellation_probability: float = 0.0,
    departure_information_source: str = "unknown",
    base_normal_position_count: int = 100,
) -> ScenarioGenerationResult:
    """Generate one homogeneous-Poisson synthetic truth without future projection."""

    validate_seed_partition(protocol, seed, seed_partition)
    demand = protocol["synthetic_demand"]
    try:
        target_load = float(demand["offered_load_ratio"][load_level])
    except KeyError as exc:
        raise ValueError(f"unknown frozen load level: {load_level}") from exc
    if layout_family not in {"independent", "mixed_depth"}:
        raise ValueError("layout_family must be independent or mixed_depth")
    if not 0 <= cancellation_probability <= 1:
        raise ValueError("cancellation_probability must be in [0,1]")
    if departure_information_source not in {
        "unknown",
        "reservation",
        "user_estimate",
        "model_prediction",
    }:
        raise ValueError("unsupported departure_information_source")
    if base_normal_position_count <= 0:
        raise ValueError("base_normal_position_count must be positive")

    arrival_window_s = int(protocol["time"]["arrival_window_s"])
    drain_deadline_s = arrival_window_s + int(protocol["time"]["max_drain_s"])
    expected_effective_dwell_s = float(demand["expected_effective_dwell_in_arrival_window_s"])
    poisson_rate_per_s = target_load * base_normal_position_count / expected_effective_dwell_s
    dwell_values = tuple(int(item) for item in demand["dwell_time_s"])
    dwell_probabilities = tuple(float(item) for item in demand["dwell_probability"])
    if not math.isclose(sum(dwell_probabilities), 1.0, abs_tol=1e-12):
        raise ValueError("dwell probabilities must sum to one")
    entrances = tuple(
        sorted(item.road_node_id for item in layout.road_nodes if item.node_kind == "entrance")
    )
    if not entrances:
        raise ValueError("layout must contain at least one entrance")
    soft_slice = protocol["sensitivity_slices"]["soft_information"]
    error_values_s = tuple(int(value) for value in soft_slice["error_s"])
    error_probabilities = tuple(float(value) for value in soft_slice["error_probability"])
    if len(error_values_s) != len(error_probabilities) or not math.isclose(
        sum(error_probabilities),
        1.0,
        abs_tol=1e-12,
    ):
        raise ValueError("soft-information error distribution is invalid")

    vehicle_requests, truth_events, information_updates, realized_effective_dwell_s, truncations = (
        generate_arrival_events(
            seed=seed,
            arrival_window_s=arrival_window_s,
            poisson_rate_per_s=poisson_rate_per_s,
            dwell_values=dwell_values,
            dwell_probabilities=dwell_probabilities,
            entrances=entrances,
            departure_information_source=departure_information_source,
            error_values_s=error_values_s,
            error_probabilities=error_probabilities,
            cancellation_probability=cancellation_probability,
        )
    )

    active_buffers = [item.position_id for item in layout.buffer_slots]
    scenario = {
        "schema_version": "1.0.0",
        "scenario_id": f"synthetic-{layout_family}-{load_level}-{seed}",
        "layout_id": layout.layout_id,
        "data_source": "synthetic",
        "purpose": "simulation_truth",
        "random_seed": seed,
        "arrival_window_end_s": arrival_window_s,
        "drain_deadline_s": drain_deadline_s,
        "config": {
            "recoverability_policy": recoverability_policy,
            "buffer_count": len(active_buffers),
            "active_buffer_position_ids": active_buffers,
            "relocation_executor_capacity": relocation_executor_capacity,
            "executor_type": "simulation_only",
            "relocation_setup_s": relocation_setup_s,
            "relocation_speed_mps": relocation_speed_mps,
            "arrival_wait_capacity": arrival_wait_capacity,
            "max_arrival_wait_s": max_arrival_wait_s,
            "max_departure_wait_s": max_departure_wait_s,
            "fallback_target_s": float(protocol["time"]["fallback_target_s"]),
            "minimum_logging_reserve_s": minimum_logging_reserve_s,
        },
        "vehicle_requests": vehicle_requests,
        "truth_events": truth_events,
        "information_updates": information_updates,
    }
    truth_payload = {
        "schema_version": "1.0.0",
        "data_source": "synthetic",
        "random_seed": seed,
        "layout_family": layout_family,
        "load_level": load_level,
        "vehicle_requests": vehicle_requests,
        "truth_events": truth_events,
        "information_updates": [],
    }
    realized_load = realized_effective_dwell_s / (base_normal_position_count * arrival_window_s)
    return ScenarioGenerationResult(
        scenario=scenario,
        scenario_content_sha256=canonical_sha256(scenario),
        event_truth_sha256=canonical_sha256(truth_payload),
        realized_offered_load_ratio=realized_load,
        arrival_count=len(vehicle_requests),
        seed_partition=seed_partition,
        soft_information_truncation_count=truncations,
    )
