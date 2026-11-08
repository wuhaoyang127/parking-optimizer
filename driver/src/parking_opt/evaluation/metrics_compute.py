"""Standard-log replay that drives frozen metric computation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from parking_opt.domain.state import AuthoritativeState
from parking_opt.domain.transitions import apply_event
from parking_opt.evaluation.metrics import MetricContext, _integrate_interval
from parking_opt.evaluation.metrics_records import build_metric_records
from parking_opt.layout.model import Layout


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
    replay = {
        "state_at_window_end": state_at_window_end,
        "totals": totals,
        "arrivals": arrivals,
        "arrival_terminals": arrival_terminals,
        "departures": departures,
        "departure_first_service": departure_first_service,
        "departure_completions": departure_completions,
        "relocation_count": relocation_count,
        "relocation_distance_m": relocation_distance_m,
        "fallback_count": fallback_count,
        "manual_count": manual_count,
        "failed_count": failed_count,
    }
    _ = layout  # Layout is an explicit metric input and future availability source.
    return tuple(build_metric_records(context, replay, events))
