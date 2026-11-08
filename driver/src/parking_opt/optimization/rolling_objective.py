"""Request ordering, selection compatibility, and objective for rolling plans."""

from __future__ import annotations

from parking_opt.domain.enums import ActionType, ArrivalStatus, PrimaryDecision
from parking_opt.domain.records import DecisionRequest, PendingRequest
from parking_opt.optimization.rolling_types import RollingObjective
from parking_opt.strategies._selection import Selection, deterministic_target


def _service_key(request: DecisionRequest, item: PendingRequest) -> tuple[object, ...]:
    vehicle = next(
        value
        for value in request.observed_snapshot.vehicles
        if value.anonymous_vehicle_id == item.anonymous_vehicle_id
    )
    sla_violated = (
        item.request_type == "DEPARTURE"
        and request.decision_time_s - item.requested_at_s
        >= int(request.approved_config["max_departure_wait_s"])
    )
    immediately_executable = (
        item.request_type == "DEPARTURE" and vehicle.location_state.kind.value == "AT_POSITION"
    )
    return (
        2 if item.request_type == "DEPARTURE" else 4,
        0 if sla_violated else 1,
        item.requested_at_s,
        0 if immediately_executable else 1,
        item.event_sequence_no,
        item.anonymous_vehicle_id,
    )


def _bounded_requests(request: DecisionRequest) -> tuple[tuple[PendingRequest, ...], int]:
    pending = sorted(
        request.observed_snapshot.pending_requests,
        key=lambda item: _service_key(request, item),
    )
    mandatory = deterministic_target(request)
    if mandatory is not None:
        pending = [mandatory, *(item for item in pending if item != mandatory)]
    limit = int(request.approved_config["max_requests_per_solve"])
    return tuple(pending[:limit]), len(pending)


def _safe_deferred_selection(request: DecisionRequest, target: PendingRequest) -> Selection:
    if target.request_type == "ARRIVAL":
        waited = request.decision_time_s - target.requested_at_s
        if waited >= int(request.approved_config["max_arrival_wait_s"]):
            return Selection(
                target=target,
                primary_decision=PrimaryDecision.REJECT,
                explanation_codes=("ROLLING_WINDOW_WAIT_LIMIT_REACHED",),
            )
        return Selection(
            target=target,
            primary_decision=PrimaryDecision.WAIT,
            explanation_codes=("ROLLING_WINDOW_DEFERRED",),
        )
    waited = request.decision_time_s - target.requested_at_s
    if waited >= int(request.approved_config["max_departure_wait_s"]):
        return Selection(
            target=target,
            primary_decision=PrimaryDecision.REQUEST_MANUAL_INTERVENTION,
            explanation_codes=("ROLLING_WINDOW_DEPARTURE_SLA_VIOLATED",),
        )
    return Selection(
        target=target,
        primary_decision=PrimaryDecision.WAIT,
        explanation_codes=("ROLLING_WINDOW_DEFERRED",),
    )


def _assigned_position(selection: Selection) -> str | None:
    for action in selection.actions:
        if action.action_type is ActionType.ASSIGN:
            return action.destination_position_id
    return None


def _compatible_prefix(selections: tuple[Selection, ...]) -> bool:
    action_ids: set[str] = set()
    assigned_positions: set[str] = set()
    target_ids: set[str] = set()
    for selection in selections:
        if selection.target.request_id in target_ids:
            return False
        target_ids.add(selection.target.request_id)
        destination = _assigned_position(selection)
        if destination is not None:
            if destination in assigned_positions:
                return False
            assigned_positions.add(destination)
        current_ids = {item.action_id for item in selection.actions}
        if len(current_ids) != len(selection.actions) or action_ids & current_ids:
            return False
        action_ids.update(current_ids)
        if selection.transaction is not None and set(selection.transaction.action_ids) != current_ids:
            return False
    return True


def _objective(request: DecisionRequest, selections: tuple[Selection, ...]) -> RollingObjective:
    completed_departures: set[str] = set()
    completed_arrivals: set[str] = set()
    waiting_s = 0
    relocation_legs = 0
    relocation_distance_m = 0.0
    non_relocation_distance_m = 0.0
    blocked_exposure = 0
    reservation_s = 0
    slots = {item["position_id"]: item for item in request.layout["slots"]}
    occupied = {
        item.position_id for item in request.observed_snapshot.positions if item.occupant_vehicle_id
    }
    for selection in selections:
        target = selection.target
        if selection.primary_decision is PrimaryDecision.WAIT:
            waiting_s += max(0, request.decision_time_s - target.requested_at_s)
            waiting_s += int(request.approved_config["rolling_window_s"])
        if selection.primary_decision is PrimaryDecision.RECOMMEND_ACTIONS:
            if target.request_type == "DEPARTURE":
                completed_departures.add(target.request_id)
            else:
                completed_arrivals.add(target.request_id)
        for action in selection.actions:
            if action.action_type in {ActionType.RELOCATE_TO_BUFFER, ActionType.RESTORE_ORIGINAL}:
                relocation_legs += 1
                relocation_distance_m += action.distance_m
            else:
                non_relocation_distance_m += action.distance_m
            if action.action_type is ActionType.ASSIGN:
                reservation_s += action.modeled_duration_s
                destination = action.destination_position_id
                if destination is not None:
                    slot = slots[destination]
                    blocked_exposure += sum(
                        other["stack_group_id"] == slot["stack_group_id"]
                        and int(other["depth"]) > int(slot["depth"])
                        and other["position_id"] in occupied
                        for other in slots.values()
                    ) * int(request.approved_config["rolling_window_s"])
    departures = tuple(
        selection.target for selection in selections if selection.target.request_type == "DEPARTURE"
    )
    unfinished_departures = tuple(item for item in departures if item.request_id not in completed_departures)
    overdue = sum(
        request.decision_time_s - item.requested_at_s >= int(request.approved_config["max_departure_wait_s"])
        for item in unfinished_departures
    )
    active_transactions = sum(
        item.status.value not in {"COMPLETED", "CANCELLED", "FAILED_RESOLVED"}
        for item in request.observed_snapshot.transactions
    )
    selected_vehicle_ids = {selection.target.anonymous_vehicle_id for selection in selections}
    completed_arrival_vehicle_ids = {
        selection.target.anonymous_vehicle_id
        for selection in selections
        if selection.target.request_id in completed_arrivals
    }
    admitted_incomplete = sum(
        item.anonymous_vehicle_id in selected_vehicle_ids
        and item.ever_admitted
        and item.arrival_status is not ArrivalStatus.ENTRY_COMPLETED
        and item.anonymous_vehicle_id not in completed_arrival_vehicle_ids
        for item in request.observed_snapshot.vehicles
    )
    return RollingObjective(
        overdue_departures_unfinished=overdue,
        departures_unfinished=len(unfinished_departures),
        active_transactions_unfinished=active_transactions,
        admitted_arrivals_unfinished=admitted_incomplete,
        arrivals_completed=len(completed_arrivals),
        waiting_s=waiting_s,
        relocation_legs=relocation_legs,
        relocation_distance_m=relocation_distance_m,
        non_relocation_distance_m=non_relocation_distance_m,
        blocked_exposure_vehicle_s=blocked_exposure,
        reservation_position_s=reservation_s,
    )
