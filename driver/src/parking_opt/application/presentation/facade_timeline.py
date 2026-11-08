"""Replay timeline and event views for the presentation facade."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from parking_opt.application.presentation.models import (
    ReplayActionView,
    ReplayEventView,
    ReplayTimeline,
    ValidatedDemoBundle,
)

_EVENT_CATEGORIES = {
    "ASSIGN_RECOMMENDED": "recommendation",
    "ACTION_RECOMMENDED": "recommendation",
    "ASSIGNMENT_ACCEPTED": "acceptance",
    "ACTION_ACCEPTED": "acceptance",
    "WAIT_DECIDED": "wait",
    "ACTION_WAITING_FOR_RESOURCES": "resource_wait",
    "ACTION_STARTED": "action_start",
    "ACTION_COMPLETED": "action_complete",
    "ACTION_FAILED_KNOWN_POSITION": "failure",
    "ACTION_FAILED_POSITION_UNKNOWN": "failure",
    "POSITION_RECONCILED": "reconciliation",
    "TRANSACTION_RECONCILED": "reconciliation",
    "RELOCATION_TRANSACTION_CREATED": "transaction",
    "TRANSACTION_STAGE_ADVANCED": "transaction",
    "TRANSACTION_CANCELLED_BEFORE_EXECUTION": "transaction",
    "FALLBACK_USED": "fallback",
    "MANUAL_INTERVENTION_REQUESTED": "manual",
    "MANUAL_STATUS_CHANGED": "manual",
    "REJECT_DECIDED": "failure",
    "ABORTED_BEFORE_START": "failure",
}


def _safe_text(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _event_action(event: Mapping[str, Any]) -> ReplayActionView | None:
    action = cast(Mapping[str, Any] | None, event.get("action"))
    if action is None:
        return None
    return ReplayActionView(
        action_id=cast(str, action["action_id"]),
        transaction_id=cast(str | None, action["transaction_id"]),
        action_type=cast(str, action["action_type"]),
        status=cast(str, action["status"]),
        anonymous_vehicle_id=cast(str, action["anonymous_vehicle_id"]),
        origin_position_id=cast(str | None, action["origin_position_id"]),
        destination_position_id=cast(str | None, action["destination_position_id"]),
        destination_exit_id=cast(str | None, action["destination_exit_id"]),
        distance_m=float(action["distance_m"]),
        modeled_duration_s=int(action["modeled_duration_s"]),
        executor_units=int(action["executor_units"]),
        channel_zone_ids=tuple(cast(Sequence[str], action["channel_zone_ids"])),
        failure_reason=_safe_text(action.get("failure_reason")),
    )


def _event_detail_items(
    event: Mapping[str, Any],
    action: ReplayActionView | None,
) -> tuple[tuple[str, str], ...]:
    items: list[tuple[str, str]] = []
    if action is not None:
        items.extend(
            (
                ("action_id", action.action_id),
                ("action_type", action.action_type),
                ("action_status", action.status),
                ("distance_m", f"{action.distance_m:.3f}"),
                ("modeled_duration_s", str(action.modeled_duration_s)),
            )
        )
        if action.origin_position_id:
            items.append(("origin_position_id", action.origin_position_id))
        if action.destination_position_id:
            items.append(("destination_position_id", action.destination_position_id))
        if action.destination_exit_id:
            items.append(("destination_exit_id", action.destination_exit_id))
        if action.failure_reason:
            items.append(("failure_reason", action.failure_reason))
    transaction = cast(Mapping[str, Any] | None, event.get("transaction"))
    if transaction is not None and _safe_text(transaction.get("status")):
        items.append(("transaction_status", cast(str, transaction["status"])))
    payload = cast(Mapping[str, Any], event.get("payload") or {})
    request_id = _safe_text(payload.get("request_id"))
    if request_id:
        items.append(("request_id", request_id))
    confirmed = cast(Mapping[str, Any] | None, payload.get("confirmed_location_state"))
    if confirmed is not None:
        kind = _safe_text(confirmed.get("kind"))
        position_id = _safe_text(confirmed.get("position_id"))
        if kind:
            items.append(("confirmed_location_kind", kind))
        if position_id:
            items.append(("confirmed_position_id", position_id))
    manual_status = _safe_text(payload.get("manual_status"))
    if manual_status:
        items.append(("manual_status", manual_status))
    fallback = cast(Mapping[str, Any] | None, payload.get("fallback_record"))
    if fallback is not None:
        for key in ("original_method", "original_solver_status", "reason", "used_strategy", "result_validation_status"):
            value = _safe_text(fallback.get(key))
            if value:
                items.append((f"fallback_{key}", value))
        elapsed_s = fallback.get("elapsed_s")
        if isinstance(elapsed_s, int | float):
            items.append(("fallback_elapsed_s", f"{float(elapsed_s):.3f}"))
    return tuple(items)


def _event_summary(event_type: str, action: ReplayActionView | None, transaction_status: str | None) -> str:
    if action is not None:
        return f"{action.action_type} · {action.status} · {action.anonymous_vehicle_id}"
    if transaction_status:
        return f"{event_type} · {transaction_status}"
    return event_type


def build_replay_timeline(bundle: ValidatedDemoBundle) -> ReplayTimeline:
    views: list[ReplayEventView] = []
    for event in bundle._events:
        event_type = cast(str, event["event_type"])
        action = _event_action(event)
        transaction = cast(Mapping[str, Any] | None, event.get("transaction"))
        transaction_status = None if transaction is None else _safe_text(transaction.get("status"))
        category = _EVENT_CATEGORIES.get(event_type, "request_or_signal")
        warnings: list[str] = []
        if event_type == "ACTION_FAILED_POSITION_UNKNOWN":
            warnings.append("POSITION_UNKNOWN")
        if category == "manual":
            warnings.append("MANUAL_INTERVENTION")
        if category == "fallback":
            warnings.append("FALLBACK_USED")
        views.append(
            ReplayEventView(
                sequence_no=int(event["sequence_no"]),
                sim_time_s=int(event["sim_time_s"]),
                event_id=cast(str, event["event_id"]),
                event_type=event_type,
                category=category,
                anonymous_vehicle_id=cast(str | None, event["anonymous_vehicle_id"]),
                transaction_id=cast(str | None, event["transaction_id"]),
                transaction_status=transaction_status,
                action=action,
                summary=_event_summary(event_type, action, transaction_status),
                detail_items=_event_detail_items(event, action),
                warning_codes=tuple(warnings),
            )
        )
    return ReplayTimeline(
        run_id=bundle.run_id,
        scenario_id=bundle.scenario_id,
        events=tuple(views),
        event_types=tuple(sorted({item.event_type for item in views})),
        transaction_ids=tuple(sorted({item.transaction_id for item in views if item.transaction_id is not None})),
    )
