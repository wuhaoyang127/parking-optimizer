"""Frozen metrics computed only from layout, config, and standard event replay."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from parking_opt.contracts.canonical import canonical_json_bytes
from parking_opt.contracts.schema_validation import SchemaCatalog
from parking_opt.domain.enums import PositionKind
from parking_opt.domain.state import AuthoritativeState
from parking_opt.evaluation.censoring import RequestObservation


@dataclass(frozen=True, slots=True)
class MetricContext:
    """Run labels and the frozen observation window."""

    run_id: str
    scenario_id: str
    algorithm_id: str
    algorithm_version: str
    window_start_s: int
    window_end_s: int
    drain_deadline_s: int
    load_level: str
    layout_class: str
    buffer_count: int
    relocation_executor_capacity: int
    recoverability_policy: str
    facility_comparison_mode: str
    max_departure_wait_s: int


def _dimensions(context: MetricContext) -> dict[str, Any]:
    return {
        "load_level": context.load_level,
        "layout_class": context.layout_class,
        "buffer_count": context.buffer_count,
        "relocation_executor_capacity": context.relocation_executor_capacity,
        "recoverability_policy": context.recoverability_policy,
        "facility_comparison_mode": context.facility_comparison_mode,
    }


def _record(
    context: MetricContext,
    *,
    metric_name: str,
    value: float | int | None,
    unit: str,
    record_level: str = "run_aggregate",
    subject_vehicle_id: str | None = None,
    subject_request_id: str | None = None,
    measured_at_s: int | None = None,
    numerator: float | int | None = None,
    denominator: float | int | None = None,
    not_applicable_reason: str | None = None,
    observation: RequestObservation | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "run_id": context.run_id,
        "scenario_id": context.scenario_id,
        "algorithm_id": context.algorithm_id,
        "algorithm_version": context.algorithm_version,
        "record_level": record_level,
        "subject_vehicle_id": subject_vehicle_id,
        "subject_request_id": subject_request_id,
        "window_start_s": context.window_start_s,
        "window_end_s": context.window_end_s,
        "measured_at_s": measured_at_s,
        "metric_name": metric_name,
        "value": value,
        "unit": unit,
        "numerator": numerator,
        "denominator": denominator,
        "not_applicable_reason": not_applicable_reason,
        "event_observed": observation.event_observed if observation else None,
        "pending_at_horizon": observation.pending_at_horizon if observation else None,
        "observed_wait_lower_bound_s": (
            observation.observed_wait_lower_bound_s if observation else None
        ),
        "dimensions": _dimensions(context),
    }


def _ratio(
    context: MetricContext,
    *,
    metric_name: str,
    numerator: float,
    denominator: float,
    record_level: str = "run_aggregate",
    measured_at_s: int | None = None,
) -> dict[str, Any]:
    if denominator == 0:
        return _record(
            context,
            metric_name=metric_name,
            value=None,
            unit="ratio",
            record_level=record_level,
            measured_at_s=measured_at_s,
            numerator=numerator,
            denominator=denominator,
            not_applicable_reason="denominator is zero",
        )
    return _record(
        context,
        metric_name=metric_name,
        value=numerator / denominator,
        unit="ratio",
        record_level=record_level,
        measured_at_s=measured_at_s,
        numerator=numerator,
        denominator=denominator,
    )


def _integrate_interval(
    state: AuthoritativeState,
    *,
    left_s: int,
    right_s: int,
    context: MetricContext,
    totals: dict[str, float],
) -> None:
    left = max(left_s, context.window_start_s)
    right = min(right_s, context.window_end_s)
    duration = max(0, right - left)
    if duration == 0:
        return
    normal = [item for item in state.positions if item.position_kind is PositionKind.NORMAL]
    buffers = [
        item
        for item in state.positions
        if item.position_kind is PositionKind.BUFFER
        and item.position_id in state.active_buffer_position_ids
    ]
    occupied_normal = sum(item.occupant_vehicle_id is not None for item in normal)
    available_normal = sum(item.physically_available for item in normal)
    occupied_buffer = sum(item.occupant_vehicle_id is not None for item in buffers)
    available_buffer = sum(item.physically_available for item in buffers)
    totals["normal_occ_s"] += occupied_normal * duration
    totals["normal_available_s"] += available_normal * duration
    totals["buffer_occ_s"] += occupied_buffer * duration
    totals["buffer_available_s"] += available_buffer * duration
    totals["executor_used_s"] += state.executor_resource.used * duration
    totals["executor_capacity_s"] += state.executor_resource.capacity * duration
    totals["zones_used_s"] += sum(item.used for item in state.channel_zone_resources) * duration
    totals["zones_capacity_s"] += (
        sum(item.capacity for item in state.channel_zone_resources) * duration
    )


def write_metric_jsonl(
    path: Path,
    records: Sequence[Mapping[str, Any]],
    *,
    schema_catalog: SchemaCatalog,
) -> None:
    """Validate and write canonical MetricRecord JSON Lines."""

    payload = bytearray()
    for record in records:
        schema_catalog.validate("metric.schema.json", record)
        payload.extend(canonical_json_bytes(record))
        payload.extend(b"\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(payload))


from parking_opt.evaluation.metrics_compute import compute_metrics  # noqa: E402
