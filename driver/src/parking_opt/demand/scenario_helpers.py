"""Synthetic-demand helpers and arrival-event generation."""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any, cast


def load_experiment_protocol(path: Path) -> dict[str, Any]:
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
    partition,
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


def generate_arrival_events(
    *,
    seed: int,
    arrival_window_s: int,
    poisson_rate_per_s: float,
    dwell_values: tuple[int, ...],
    dwell_probabilities: tuple[float, ...],
    entrances: tuple[str, ...],
    departure_information_source: str,
    error_values_s: tuple[int, ...],
    error_probabilities: tuple[float, ...],
    cancellation_probability: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], int, int]:
    """Generate homogeneous-Poisson vehicle requests, truth, and soft information."""

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
    return (
        vehicle_requests,
        truth_events,
        information_updates,
        realized_effective_dwell_s,
        soft_information_truncation_count,
    )
