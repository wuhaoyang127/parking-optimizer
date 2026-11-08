"""Non-action selection, departure selection, and top-level decision."""
from __future__ import annotations
from collections.abc import Callable, Mapping
from itertools import pairwise
from parking_opt.domain.enums import ActionStatus, ActionType, LocationKind, ManualStatus, PrimaryDecision, TransactionStatus
from parking_opt.domain.records import (
    Action,
    DecisionRequest,
    PendingRequest,
    PrecedenceEdge,
    RelocationTransaction,
)
from parking_opt.strategies._selection import Selection, _path, deterministic_target
from parking_opt.strategies.selection_action import _action
from parking_opt.strategies.selection_arrival import _bounded_arrival_candidates
from parking_opt.strategies.selection_context import _busy_stack_groups
from parking_opt.strategies.selection_matching import _feasible_matching
def _arrival_non_action_selection(request: DecisionRequest, target: PendingRequest) -> Selection:
    vehicle = next(item for item in request.observed_snapshot.vehicles if item.anonymous_vehicle_id == target.anonymous_vehicle_id)
    waiting = sum(
        item.waiting_since_s is not None and item.location_state.kind is LocationKind.ENTRY_QUEUE
        for item in request.observed_snapshot.vehicles
    )
    already_waiting = vehicle.waiting_since_s is not None
    within_time = request.decision_time_s - target.requested_at_s < int(request.approved_config["max_arrival_wait_s"])
    capacity = already_waiting or waiting < int(request.approved_config["arrival_wait_capacity"])
    if within_time and capacity:
        return Selection(target=target, primary_decision=PrimaryDecision.WAIT, explanation_codes=("NO_FEASIBLE_POSITION",))
    return Selection(target=target, primary_decision=PrimaryDecision.REJECT, explanation_codes=("NO_FEASIBLE_POSITION_OR_WAIT_CAPACITY",))
def _arrival_selection_from_candidate(
    request: DecisionRequest,
    target: PendingRequest,
    candidate: tuple[tuple[object, ...], Mapping[str, object], Mapping[str, object]],
) -> Selection:
    _, slot, path = candidate
    action = _action(
        request=request,
        action_id=f"{request.request_id}-assign",
        vehicle_id=target.anonymous_vehicle_id,
        action_type=ActionType.ASSIGN,
        path=path,
        origin_position_id=None,
        destination_position_id=str(slot["position_id"]),
        destination_exit_id=None,
    )
    return Selection(
        target=target,
        primary_decision=PrimaryDecision.RECOMMEND_ACTIONS,
        actions=(action,),
        explanation_codes=("ONLINE_ASSIGN_FEASIBLE",),
    )
def _arrival_selection(
    request: DecisionRequest,
    target: PendingRequest,
    *,
    first_fit: bool,
    deadline: float,
    clock: Callable[[], float],
) -> Selection:
    candidates, _, _ = _bounded_arrival_candidates(request, target, limit=1, first_fit=first_fit, deadline=deadline, clock=clock)
    if candidates:
        return _arrival_selection_from_candidate(request, target, candidates[0])
    return _arrival_non_action_selection(request, target)
def _departure_selection(
    request: DecisionRequest,
    target: PendingRequest,
    *,
    first_fit: bool,
    deadline: float,
    clock: Callable[[], float],
) -> Selection:
    vehicles = {item.anonymous_vehicle_id: item for item in request.observed_snapshot.vehicles}
    vehicle = vehicles[target.anonymous_vehicle_id]
    if vehicle.location_state.kind is LocationKind.POSITION_UNCERTAIN:
        return Selection(target=target, primary_decision=PrimaryDecision.REQUEST_MANUAL_INTERVENTION, explanation_codes=("POSITION_RECONCILIATION_REQUIRED",))
    if vehicle.manual_status not in {ManualStatus.NONE, ManualStatus.FAILED}:
        return Selection(target=target, primary_decision=PrimaryDecision.WAIT, explanation_codes=("MANUAL_INTERVENTION_ALREADY_ACTIVE",))
    if vehicle.active_transaction_id is not None:
        return Selection(target=target, primary_decision=PrimaryDecision.WAIT, explanation_codes=("ACTIVE_TRANSACTION_CONFIRMATION_PENDING",))
    if any(
        item.anonymous_vehicle_id == target.anonymous_vehicle_id
        and item.status in {ActionStatus.RECOMMENDED, ActionStatus.ACCEPTED, ActionStatus.WAITING_FOR_RESOURCES, ActionStatus.STARTED}
        for item in request.observed_snapshot.actions
    ):
        return Selection(target=target, primary_decision=PrimaryDecision.WAIT, explanation_codes=("ACTION_CONFIRMATION_PENDING",))
    if vehicle.location_state.kind is not LocationKind.AT_POSITION:
        return Selection(target=target, primary_decision=PrimaryDecision.WAIT, explanation_codes=("DEPARTURE_POSITION_NOT_READY",))
    origin_id = vehicle.location_state.position_id
    assert origin_id is not None
    slot_by_id = {item["position_id"]: item for item in request.layout["slots"]}
    origin = slot_by_id[origin_id]
    if origin["stack_group_id"] in _busy_stack_groups(request):
        return Selection(target=target, primary_decision=PrimaryDecision.WAIT, explanation_codes=("STACK_GROUP_MOVEMENT_PENDING",))
    occupants = {
        item.position_id: item.occupant_vehicle_id
        for item in request.observed_snapshot.positions
        if item.occupant_vehicle_id is not None
    }
    blockers = tuple((occupants[item["position_id"]], item) for item in request.layout["slots"] if item["stack_group_id"] == origin["stack_group_id"] and int(item["depth"]) < int(origin["depth"]) and item["position_id"] in occupants)
    blockers = tuple(sorted(blockers, key=lambda item: int(item[1]["depth"])))
    exits = sorted(item["road_node_id"] for item in request.layout["road_nodes"] if item["node_kind"] == "exit")
    if not blockers:
        paths = [path for exit_id in exits if (path := _path(request.layout, origin["access_node_id"], exit_id)) is not None]
        if not paths:
            return Selection(target=target, primary_decision=PrimaryDecision.REQUEST_MANUAL_INTERVENTION, explanation_codes=("EXIT_PATH_UNREACHABLE",))
        path = min(paths, key=lambda item: (float(item["distance_m"]), int(item["travel_time_s"]), item["to_node_id"]))
        action = _action(request=request, action_id=f"{request.request_id}-exit", vehicle_id=target.anonymous_vehicle_id, action_type=ActionType.DIRECT_EXIT, path=path, origin_position_id=origin_id, destination_position_id=None, destination_exit_id=path["to_node_id"])
        return Selection(target=target, primary_decision=PrimaryDecision.RECOMMEND_ACTIONS, actions=(action,), explanation_codes=("ONLINE_DIRECT_EXIT",))
    current = _feasible_matching(request, blockers, require_currently_free=True, first_fit=first_fit, deadline=deadline, clock=clock)
    structural = _feasible_matching(request, blockers, require_currently_free=False, first_fit=True, deadline=deadline, clock=clock)
    if current is None:
        if structural is None:
            return Selection(target=target, primary_decision=PrimaryDecision.REQUEST_MANUAL_INTERVENTION, explanation_codes=("BUFFER_MATCHING_OR_REACHABILITY_INFEASIBLE",))
        if request.decision_time_s - target.requested_at_s >= int(request.approved_config["max_departure_wait_s"]):
            return Selection(target=target, primary_decision=PrimaryDecision.REQUEST_MANUAL_INTERVENTION, explanation_codes=("DEPARTURE_SLA_VIOLATED",))
        return Selection(target=target, primary_decision=PrimaryDecision.WAIT, explanation_codes=("TRANSIENT_BUFFER_CONFLICT",))
    assignments, _, _ = current
    transaction_id = f"{request.request_id}-txn"
    actions: list[Action] = []
    for index, assignment in enumerate(assignments, start=1):
        blocker_slot = slot_by_id[assignment.original_position_id]
        buffer = next(item for item in request.layout["buffer_slots"] if item["position_id"] == assignment.buffer_position_id)
        path = _path(request.layout, blocker_slot["access_node_id"], buffer["access_node_id"])
        assert path is not None
        actions.append(_action(request=request, action_id=f"{request.request_id}-txn-a{index:02d}", vehicle_id=assignment.blocker_vehicle_id, action_type=ActionType.RELOCATE_TO_BUFFER, path=path, origin_position_id=assignment.original_position_id, destination_position_id=assignment.buffer_position_id, destination_exit_id=None, transaction_id=transaction_id))
    exit_paths = [path for exit_id in exits if (path := _path(request.layout, origin["access_node_id"], exit_id)) is not None]
    if not exit_paths:
        return Selection(target=target, primary_decision=PrimaryDecision.REQUEST_MANUAL_INTERVENTION, explanation_codes=("EXIT_PATH_UNREACHABLE",))
    exit_path = min(exit_paths, key=lambda item: (float(item["distance_m"]), int(item["travel_time_s"]), item["to_node_id"]))
    actions.append(_action(request=request, action_id=f"{request.request_id}-txn-a{len(actions) + 1:02d}", vehicle_id=target.anonymous_vehicle_id, action_type=ActionType.DIRECT_EXIT, path=exit_path, origin_position_id=origin_id, destination_position_id=None, destination_exit_id=exit_path["to_node_id"], transaction_id=transaction_id))
    for assignment in reversed(assignments):
        blocker_slot = slot_by_id[assignment.original_position_id]
        buffer = next(item for item in request.layout["buffer_slots"] if item["position_id"] == assignment.buffer_position_id)
        path = _path(request.layout, buffer["access_node_id"], blocker_slot["access_node_id"])
        assert path is not None
        actions.append(_action(request=request, action_id=f"{request.request_id}-txn-a{len(actions) + 1:02d}", vehicle_id=assignment.blocker_vehicle_id, action_type=ActionType.RESTORE_ORIGINAL, path=path, origin_position_id=assignment.buffer_position_id, destination_position_id=assignment.original_position_id, destination_exit_id=None, transaction_id=transaction_id))
    action_ids = tuple(item.action_id for item in actions)
    transaction = RelocationTransaction(
        transaction_id=transaction_id,
        target_vehicle_id=target.anonymous_vehicle_id,
        status=TransactionStatus.PROPOSED,
        blocker_vehicle_ids=tuple(item[0] for item in blockers),
        buffer_assignments=assignments,
        action_ids=action_ids,
        precedence_edges=tuple(PrecedenceEdge(before_action_id=left, after_action_id=right) for left, right in pairwise(action_ids)),
        created_at_s=request.decision_time_s,
        ended_at_s=None,
    )
    return Selection(
        target=target,
        primary_decision=PrimaryDecision.RECOMMEND_ACTIONS,
        actions=tuple(actions),
        transaction=transaction,
        explanation_codes=("ONLINE_PASSIVE_RELOCATION_TRANSACTION",),
    )
def _service_key(request: DecisionRequest, item: PendingRequest) -> tuple[object, ...]:
    vehicle = next(value for value in request.observed_snapshot.vehicles if value.anonymous_vehicle_id == item.anonymous_vehicle_id)
    physical_rank = 2 if item.request_type == "DEPARTURE" else 4
    sla_violated = item.request_type == "DEPARTURE" and request.decision_time_s - item.requested_at_s >= int(request.approved_config["max_departure_wait_s"])
    immediately_executable = item.request_type == "DEPARTURE" and vehicle.location_state.kind is LocationKind.AT_POSITION
    return (physical_rank, 0 if sla_violated else 1, item.requested_at_s, 0 if immediately_executable else 1, item.event_sequence_no, item.anonymous_vehicle_id)
def select_decision(
    request: DecisionRequest,
    *,
    first_fit: bool,
    deadline: float,
    clock: Callable[[], float],
) -> Selection | None:
    mandatory = deterministic_target(request)
    pending = list(request.observed_snapshot.pending_requests)
    pending.sort(key=lambda item: _service_key(request, item))
    max_items = int(request.approved_config["max_requests_per_solve"])
    ordered = [mandatory, *(item for item in pending if item != mandatory)] if mandatory is not None else pending
    ordered = ordered[:max_items]
    first_wait: Selection | None = None
    for target in ordered:
        if clock() >= deadline:
            return None
        if target.request_type == "DEPARTURE":
            result = _departure_selection(request, target, first_fit=first_fit, deadline=deadline, clock=clock)
        else:
            result = _arrival_selection(request, target, first_fit=first_fit, deadline=deadline, clock=clock)
        if mandatory is not None and target == mandatory:
            return result
        if result.primary_decision is PrimaryDecision.WAIT:
            first_wait = first_wait or result
            continue
        return result
    return first_wait
