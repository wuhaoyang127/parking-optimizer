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
from parking_opt.domain.transitions import apply_event
from parking_opt.evaluation.censoring import RequestObservation, observe_duration
from parking_opt.layout.model import Layout


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


def compute_metrics(
    *,
    initial_state: AuthoritativeState,
    events: Sequence[Mapping[str, Any]],
    layout: Layout,
    context: MetricContext,
) -> tuple[dict[str, Any], ...]:
    """Replay one standard log and derive every frozen C3 metric family."""

    if context.window_end_s <= context.window_start_s:
        raise ValueError("metric observation window must have positive duration")
    totals = {
        "normal_occ_s": 0.0,
        "normal_available_s": 0.0,
        "buffer_occ_s": 0.0,
        "buffer_available_s": 0.0,
        "executor_used_s": 0.0,
        "executor_capacity_s": 0.0,
        "zones_used_s": 0.0,
        "zones_capacity_s": 0.0,
    }
    state = initial_state
    cursor = context.window_start_s
    state_at_window_end = initial_state
    arrivals: dict[str, tuple[str, int]] = {}
    arrival_terminals: dict[str, int] = {}
    departures: dict[str, tuple[str, int]] = {}
    departure_first_service: dict[str, int] = {}
    departure_completions: dict[str, int] = {}
    transaction_targets: dict[str, str] = {}
    relocation_count = 0
    relocation_distance_m = 0.0
    fallback_count = 0
    manual_count = 0
    failed_count = 0

    for event in events:
        event_time = int(event["sim_time_s"])
        if cursor < context.window_end_s:
            _integrate_interval(
                state,
                left_s=cursor,
                right_s=event_time,
                context=context,
                totals=totals,
            )
        if event_time <= context.drain_deadline_s:
            state = apply_event(state, event)
        if event_time < context.window_end_s:
            state_at_window_end = state
        cursor = max(cursor, event_time)

        event_type = event["event_type"]
        vehicle_id = event["anonymous_vehicle_id"]
        payload = event["payload"]
        action = event["action"]
        if event_type == "ARRIVAL_REQUESTED":
            pending = payload["pending_request"]
            arrivals[pending["request_id"]] = (
                pending["anonymous_vehicle_id"],
                pending["requested_at_s"],
            )
        elif event_type in {"REJECT_DECIDED", "USER_CANCELLED"}:
            if vehicle_id is not None:
                arrival_terminals[vehicle_id] = event_time
        elif event_type == "DEPARTURE_REQUESTED":
            pending = payload["pending_request"]
            departures[pending["request_id"]] = (
                pending["anonymous_vehicle_id"],
                pending["requested_at_s"],
            )
        elif event_type == "RELOCATION_TRANSACTION_CREATED":
            transaction = event["transaction"]
            transaction_targets[event["transaction_id"]] = transaction["target_vehicle_id"]
        elif event_type == "ACTION_STARTED" and action is not None:
            if action["transaction_id"] is not None:
                served_vehicle = transaction_targets[action["transaction_id"]]
            else:
                served_vehicle = action["anonymous_vehicle_id"]
            if action["action_type"] in {
                "DIRECT_EXIT",
                "RELOCATE_TO_BUFFER",
            }:
                departure_first_service.setdefault(served_vehicle, event_time)
        elif event_type == "ACTION_COMPLETED" and action is not None:
            if action["action_type"] == "ASSIGN":
                arrival_terminals[action["anonymous_vehicle_id"]] = event_time
            elif action["action_type"] == "DIRECT_EXIT":
                departure_completions[action["anonymous_vehicle_id"]] = event_time
            elif action["action_type"] in {
                "RELOCATE_TO_BUFFER",
                "RESTORE_ORIGINAL",
            }:
                relocation_count += 1
                relocation_distance_m += float(action["distance_m"])
        elif event_type == "FALLBACK_USED":
            fallback_count += 1
        elif event_type == "MANUAL_INTERVENTION_REQUESTED":
            manual_count += 1
        elif event_type in {
            "ACTION_FAILED_KNOWN_POSITION",
            "ACTION_FAILED_POSITION_UNKNOWN",
        }:
            failed_count += 1

    _integrate_interval(
        state_at_window_end,
        left_s=min(cursor, context.window_end_s),
        right_s=context.window_end_s,
        context=context,
        totals=totals,
    )
    normal_positions = [
        item for item in state_at_window_end.positions if item.position_kind is PositionKind.NORMAL
    ]
    occupancy_numerator = sum(item.occupant_vehicle_id is not None for item in normal_positions)
    occupancy_denominator = sum(item.physically_available for item in normal_positions)
    records: list[dict[str, Any]] = [
        _ratio(
            context,
            metric_name="occupancy_rate",
            numerator=occupancy_numerator,
            denominator=occupancy_denominator,
            record_level="instantaneous",
            measured_at_s=context.window_end_s,
        ),
        _ratio(
            context,
            metric_name="normal_space_time_utilization",
            numerator=totals["normal_occ_s"],
            denominator=totals["normal_available_s"],
        ),
        _ratio(
            context,
            metric_name="facility_position_space_time_utilization",
            numerator=totals["normal_occ_s"] + totals["buffer_occ_s"],
            denominator=totals["normal_available_s"] + totals["buffer_available_s"],
        ),
        _ratio(
            context,
            metric_name="buffer_utilization",
            numerator=totals["buffer_occ_s"],
            denominator=totals["buffer_available_s"],
        ),
    ]
    completed_arrivals = sum(
        terminal_vehicle in arrival_terminals
        and any(
            event["event_type"] == "ACTION_COMPLETED"
            and event["action"] is not None
            and event["action"]["action_type"] == "ASSIGN"
            and event["action"]["anonymous_vehicle_id"] == terminal_vehicle
            for event in events
        )
        for terminal_vehicle, _ in arrivals.values()
    )
    records.append(
        _ratio(
            context,
            metric_name="demand_satisfaction_rate",
            numerator=completed_arrivals,
            denominator=len(arrivals),
        )
    )
    completed_departures_in_window = sum(
        context.window_start_s <= value < context.window_end_s
        for value in departure_completions.values()
    )
    hours = (context.window_end_s - context.window_start_s) / 3600
    records.extend(
        [
            _record(
                context,
                metric_name="throughput_per_hour",
                value=completed_departures_in_window / hours,
                unit="per_hour",
                numerator=completed_departures_in_window,
                denominator=hours,
            ),
            _record(
                context,
                metric_name="relocation_count",
                value=relocation_count,
                unit="count",
            ),
            _record(
                context,
                metric_name="relocation_distance_m",
                value=relocation_distance_m,
                unit="meter",
            ),
            _ratio(
                context,
                metric_name="executor_utilization",
                numerator=totals["executor_used_s"],
                denominator=totals["executor_capacity_s"],
            ),
            _ratio(
                context,
                metric_name="channel_zone_utilization",
                numerator=totals["zones_used_s"],
                denominator=totals["zones_capacity_s"],
            ),
            _record(
                context,
                metric_name="fallback_count",
                value=fallback_count,
                unit="count",
            ),
            _record(
                context,
                metric_name="manual_intervention_count",
                value=manual_count,
                unit="count",
            ),
            _record(
                context,
                metric_name="failed_action_count",
                value=failed_count,
                unit="count",
            ),
        ]
    )
    sla_violations = sum(
        (departure_completions.get(vehicle_id, context.drain_deadline_s) - requested_at_s)
        >= context.max_departure_wait_s
        for vehicle_id, requested_at_s in departures.values()
    )
    records.append(
        _record(
            context,
            metric_name="sla_violation_count",
            value=sla_violations,
            unit="count",
        )
    )
    for request_id, (vehicle_id, requested_at_s) in arrivals.items():
        observation = observe_duration(
            request_time_s=requested_at_s,
            terminal_time_s=arrival_terminals.get(vehicle_id),
            drain_deadline_s=context.drain_deadline_s,
        )
        records.append(
            _record(
                context,
                metric_name="arrival_wait_s",
                value=observation.value_s,
                unit="second",
                record_level="request_observation",
                subject_vehicle_id=vehicle_id,
                subject_request_id=request_id,
                observation=observation,
            )
        )
    for request_id, (vehicle_id, requested_at_s) in departures.items():
        wait_observation = observe_duration(
            request_time_s=requested_at_s,
            terminal_time_s=departure_first_service.get(vehicle_id),
            drain_deadline_s=context.drain_deadline_s,
        )
        delay_observation = observe_duration(
            request_time_s=requested_at_s,
            terminal_time_s=departure_completions.get(vehicle_id),
            drain_deadline_s=context.drain_deadline_s,
        )
        records.extend(
            [
                _record(
                    context,
                    metric_name="departure_wait_s",
                    value=wait_observation.value_s,
                    unit="second",
                    record_level="request_observation",
                    subject_vehicle_id=vehicle_id,
                    subject_request_id=request_id,
                    observation=wait_observation,
                ),
                _record(
                    context,
                    metric_name="departure_delay_s",
                    value=delay_observation.value_s,
                    unit="second",
                    record_level="request_observation",
                    subject_vehicle_id=vehicle_id,
                    subject_request_id=request_id,
                    observation=delay_observation,
                ),
            ]
        )
    _ = layout  # Layout is an explicit metric input and future availability source.
    return tuple(records)


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
