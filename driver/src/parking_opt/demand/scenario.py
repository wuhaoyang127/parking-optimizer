"""Frozen stage B synthetic demand generation with explicit seed partitions."""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

from parking_opt.contracts.canonical import canonical_sha256
from parking_opt.layout.model import Layout


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


def load_experiment_protocol(path: Path) -> dict[str, Any]:
    """Read the approved machine protocol without accepting a different status."""

    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if value.get("protocol_version") != "1.0.0" or value.get("status") != "approved_g3":
        raise ValueError("synthetic generation requires approved protocol_version 1.0.0")
    if value.get("data_source") != "synthetic":
        raise ValueError("stage B protocol is not marked synthetic")
    return cast(dict[str, Any], value)


def validate_seed_partition(
    protocol: dict[str, Any],
    seed: int,
    partition: SeedPartition,
) -> None:
    """Reject cross-partition seed use before random generation starts."""

    approved = protocol["seed_sets"][partition.value]
    if seed not in approved:
        raise ValueError(f"seed {seed} is not registered for {partition.value}")
    development = set(protocol["seed_sets"]["development"])
    tuning = set(protocol["seed_sets"]["tuning"])
    formal = set(protocol["seed_sets"]["formal_core"])
    if development & tuning or development & formal or tuning & formal:
        raise ValueError("development, tuning, and formal core seed sets must be disjoint")


def _unknown_departure_information() -> dict[str, Any]:
    return {
        "expected_departure_time_s": None,
        "source": "unknown",
        "known_at_time_s": 0,
        "source_record_id": None,
        "model_id": None,
        "generated_at_time_s": None,
        "training_data_cutoff_s": None,
        "feature_window_end_s": None,
    }


def _substream_seed(seed: int, purpose: str) -> int:
    """Derive a stable independent RNG seed without relying on process hash state."""

    digest = hashlib.sha256(f"parking-opt-v1:{seed}:{purpose}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


def _departure_information(
    *,
    source: str,
    vehicle_id: str,
    arrival_time_s: int,
    true_departure_time_s: int,
    information_rng: random.Random,
    error_values_s: tuple[int, ...],
    error_probabilities: tuple[float, ...],
) -> tuple[dict[str, Any], bool]:
    """Build one arrival-visible synthetic soft-information record."""

    if source == "reservation":
        expected_time_s = true_departure_time_s
    else:
        error_s = information_rng.choices(
            error_values_s,
            weights=error_probabilities,
            k=1,
        )[0]
        expected_time_s = true_departure_time_s + error_s
    was_truncated = expected_time_s < 0
    expected_time_s = max(0, expected_time_s)
    is_model = source == "model_prediction"
    return (
        {
            "expected_departure_time_s": expected_time_s,
            "source": source,
            "known_at_time_s": arrival_time_s,
            "source_record_id": f"{vehicle_id}-{source}-arrival",
            "model_id": "synthetic-interface-stress-v1" if is_model else None,
            "generated_at_time_s": arrival_time_s if is_model else None,
            "training_data_cutoff_s": 0 if is_model else None,
            "feature_window_end_s": arrival_time_s if is_model else None,
        },
        was_truncated,
    )


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

    demand_rng = random.Random(seed)
    cancellation_rng = random.Random(_substream_seed(seed, "cancellation"))
    information_rng = random.Random(_substream_seed(seed, "soft-information"))
    vehicle_requests: list[dict[str, Any]] = []
    truth_events: list[dict[str, Any]] = []
    information_updates: list[dict[str, Any]] = []
    arrival_clock = 0.0
    realized_effective_dwell_s = 0
    soft_information_truncation_count = 0
    index = 0
    while True:
        arrival_clock += demand_rng.expovariate(poisson_rate_per_s)
        arrival_time_s = int(arrival_clock)
        if arrival_time_s >= arrival_window_s:
            break
        index += 1
        vehicle_id = f"syn-{seed}-v{index:05d}"
        request_id = f"syn-{seed}-arr-{index:05d}"
        dwell_s = demand_rng.choices(dwell_values, weights=dwell_probabilities, k=1)[0]
        entrance_node_id = entrances[demand_rng.randrange(len(entrances))]
        true_departure_time_s = arrival_time_s + dwell_s
        vehicle_requests.append(
            {
                "request_id": request_id,
                "anonymous_vehicle_id": vehicle_id,
                "arrival_time_s": arrival_time_s,
                "entrance_node_id": entrance_node_id,
                "reservation_status": "NONE",
                "departure_information": _unknown_departure_information(),
            }
        )
        realized_effective_dwell_s += min(dwell_s, arrival_window_s - arrival_time_s)
        if departure_information_source in {
            "reservation",
            "user_estimate",
            "model_prediction",
        }:
            departure_information, was_truncated = _departure_information(
                source=departure_information_source,
                vehicle_id=vehicle_id,
                arrival_time_s=arrival_time_s,
                true_departure_time_s=true_departure_time_s,
                information_rng=information_rng,
                error_values_s=error_values_s,
                error_probabilities=error_probabilities,
            )
            soft_information_truncation_count += int(was_truncated)
            information_updates.append(
                {
                    "information_update_id": f"syn-{seed}-info-{index:05d}",
                    "anonymous_vehicle_id": vehicle_id,
                    "reservation_status": (
                        "CONFIRMED" if departure_information_source == "reservation" else "NONE"
                    ),
                    "departure_information": departure_information,
                }
            )
        truth_events.append(
            {
                "truth_event_id": f"syn-{seed}-truth-{index:05d}",
                "anonymous_vehicle_id": vehicle_id,
                "event_kind": "DEPARTURE_REQUEST",
                "event_time_s": true_departure_time_s,
            }
        )
        if cancellation_probability and cancellation_rng.random() < cancellation_probability:
            # Immediate, pre-decision cancellation is intentional for the controlled
            # sensitivity slice: ARRIVAL_REQUESTED sorts before USER_CANCELLED.
            truth_events.append(
                {
                    "truth_event_id": f"syn-{seed}-cancel-{index:05d}",
                    "anonymous_vehicle_id": vehicle_id,
                    "event_kind": "USER_CANCELLED",
                    "event_time_s": arrival_time_s,
                }
            )

    truth_events.sort(
        key=lambda item: (
            item["event_time_s"],
            item["truth_event_id"],
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
        # Soft information is observable input rather than physical event truth.
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
        soft_information_truncation_count=soft_information_truncation_count,
    )
