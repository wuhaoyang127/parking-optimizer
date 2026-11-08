from __future__ import annotations
from collections.abc import Mapping, Sequence
from typing import Any
from parking_opt.domain.enums import PositionKind
from parking_opt.evaluation.censoring import observe_duration
from parking_opt.evaluation.metrics import MetricContext, _ratio, _record
def build_metric_records(context: MetricContext, replay: dict[str, Any], events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    state_at_window_end = replay["state_at_window_end"]
    totals = replay["totals"]
    arrivals = replay["arrivals"]
    arrival_terminals = replay["arrival_terminals"]
    departures = replay["departures"]
    departure_first_service = replay["departure_first_service"]
    departure_completions = replay["departure_completions"]
    relocation_count = replay["relocation_count"]
    relocation_distance_m = replay["relocation_distance_m"]
    fallback_count = replay["fallback_count"]
    manual_count = replay["manual_count"]
    failed_count = replay["failed_count"]
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
    return records
