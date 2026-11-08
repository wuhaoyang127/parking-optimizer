"""Sandbox arrival preview."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from parking_opt.application.sandbox_preview import _candidate_projection, _decision_request
from parking_opt.application.sandbox_types import SandboxDecision
from parking_opt.contracts.schema_validation import SchemaCatalog
from parking_opt.domain.enums import (
    ArrivalStatus,
    DepartureInformationSource,
    DepartureStatus,
    LocationKind,
    ManualStatus,
    ReservationStatus,
)
from parking_opt.domain.invariants import assert_state_invariants
from parking_opt.domain.records import DepartureInformation, LocationState, PendingRequest, VehicleState
from parking_opt.domain.state import AuthoritativeState
from parking_opt.layout.model import Layout
from parking_opt.strategies.online_rule import OnlineRulePolicy


def preview_arrival(
    repository_root: Path,
    state: AuthoritativeState,
    layout: Layout,
    *,
    anonymous_vehicle_id: str,
    entrance_node_id: str,
    decision_time_s: int,
    has_reservation: bool,
    expected_departure_time_s: int | None,
) -> SandboxDecision:
    """Run the real online rule for one synthetic arrival without mutating state."""

    vehicle_id = anonymous_vehicle_id.strip()
    if not vehicle_id or len(vehicle_id) > 32:
        raise ValueError("anonymous vehicle label must contain 1 to 32 characters")
    if any(item.anonymous_vehicle_id == vehicle_id for item in state.vehicles):
        raise ValueError("anonymous vehicle label already exists in the sandbox")
    entrances = {item.road_node_id for item in layout.road_nodes if item.node_kind == "entrance"}
    if entrance_node_id not in entrances:
        raise ValueError("selected entrance is not defined by the sandbox layout")
    if decision_time_s < state.sim_time_s:
        raise ValueError("arrival time cannot move backwards")
    if expected_departure_time_s is not None and expected_departure_time_s <= decision_time_s:
        raise ValueError("expected departure must be later than arrival")
    source = (
        DepartureInformationSource.RESERVATION
        if has_reservation and expected_departure_time_s is not None
        else DepartureInformationSource.USER_ESTIMATE
        if expected_departure_time_s is not None
        else DepartureInformationSource.UNKNOWN
    )
    target = PendingRequest(
        request_id=f"arrival-{vehicle_id}-{state.sequence_no + 1}",
        anonymous_vehicle_id=vehicle_id,
        request_type="ARRIVAL",
        requested_at_s=decision_time_s,
        event_sequence_no=state.sequence_no + 1,
        entrance_node_id=entrance_node_id,
    )
    vehicle = VehicleState(
        anonymous_vehicle_id=vehicle_id,
        location_state=LocationState(LocationKind.ENTRY_QUEUE),
        arrival_status=ArrivalStatus.PENDING,
        departure_status=DepartureStatus.NONE,
        manual_status=ManualStatus.NONE,
        ever_admitted=False,
        admitted_at_s=None,
        waiting_since_s=decision_time_s,
        action_context_id=None,
        active_transaction_id=None,
        reservation_status=(ReservationStatus.CONFIRMED if has_reservation else ReservationStatus.NONE),
        departure_information=DepartureInformation(
            expected_departure_time_s=expected_departure_time_s,
            source=source,
            known_at_time_s=decision_time_s,
            source_record_id=(f"sandbox-{vehicle_id}-departure" if expected_departure_time_s is not None else None),
        ),
    )
    input_state = replace(
        state,
        sequence_no=state.sequence_no + 1,
        sim_time_s=decision_time_s,
        vehicles=tuple(sorted((*state.vehicles, vehicle), key=lambda item: item.anonymous_vehicle_id)),
        pending_requests=(*state.pending_requests, target),
    )
    assert_state_invariants(input_state)
    request = _decision_request(input_state, layout, trigger_event_type="ARRIVAL_REQUESTED", target=target)
    policy = OnlineRulePolicy(
        schema_catalog=SchemaCatalog(repository_root / "schemas" / "v1"),
        clock=lambda: 0.0,
    )
    result = policy.decide(request)
    candidates = _candidate_projection(policy.explain_arrival_candidates(request))
    feasible = tuple(item for item in candidates if item.feasible)
    selected = next(
        (action.destination_position_id for action in result.recommended_actions if action.destination_position_id is not None),
        None,
    )
    nearest = min(
        feasible,
        key=lambda item: (item.distance_m if item.distance_m is not None else float("inf"), item.position_id),
        default=None,
    )
    if selected is not None and (not feasible or feasible[0].position_id != selected):
        raise RuntimeError("candidate explanation diverged from the online-rule result")
    story = (
        f"{vehicle_id} 到达入口，系统读取当前可见停车状态。",
        f"在线规则检查 {len(candidates)} 个正常车位并排除不可行位置。",
        "候选按安全、阻挡、剩余容量、距离、纵深和稳定编号逐层排序。",
        (
            f"推荐 {selected}，等待用户在沙盒中确认停车。"
            if selected is not None
            else f"当前主决定为 {result.primary_decision.value}，没有生成停车动作。"
        ),
    )
    return SandboxDecision(
        decision_kind="ARRIVAL",
        input_state=input_state,
        request=request,
        result=result,
        candidates=candidates,
        selected_position_id=selected,
        nearest_feasible_position_id=None if nearest is None else nearest.position_id,
        story_steps=story,
    )
