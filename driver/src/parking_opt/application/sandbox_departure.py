"""Sandbox departure preview."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from parking_opt.application.sandbox_preview import _decision_request
from parking_opt.application.sandbox_types import SandboxDecision
from parking_opt.contracts.schema_validation import SchemaCatalog
from parking_opt.domain.enums import DepartureStatus, LocationKind
from parking_opt.domain.invariants import assert_state_invariants
from parking_opt.domain.records import PendingRequest
from parking_opt.domain.state import AuthoritativeState
from parking_opt.layout.model import Layout
from parking_opt.strategies.online_rule import OnlineRulePolicy


def preview_departure(
    repository_root: Path,
    state: AuthoritativeState,
    layout: Layout,
    *,
    anonymous_vehicle_id: str,
    decision_time_s: int,
) -> SandboxDecision:
    """Run the real online rule for one parked vehicle departure request."""

    vehicle = next(
        (
            item
            for item in state.vehicles
            if item.anonymous_vehicle_id == anonymous_vehicle_id
            and item.location_state.kind is LocationKind.AT_POSITION
        ),
        None,
    )
    if vehicle is None:
        raise ValueError("departure target must be a parked sandbox vehicle")
    if decision_time_s < state.sim_time_s:
        raise ValueError("departure time cannot move backwards")
    target = PendingRequest(
        request_id=f"departure-{anonymous_vehicle_id}-{state.sequence_no + 1}",
        anonymous_vehicle_id=anonymous_vehicle_id,
        request_type="DEPARTURE",
        requested_at_s=decision_time_s,
        event_sequence_no=state.sequence_no + 1,
        entrance_node_id=None,
    )
    input_state = replace(
        state,
        sequence_no=state.sequence_no + 1,
        sim_time_s=decision_time_s,
        vehicles=tuple(
            replace(item, departure_status=DepartureStatus.PENDING)
            if item.anonymous_vehicle_id == anonymous_vehicle_id
            else item
            for item in state.vehicles
        ),
        pending_requests=(*state.pending_requests, target),
    )
    assert_state_invariants(input_state)
    request = _decision_request(input_state, layout, trigger_event_type="DEPARTURE_REQUESTED", target=target)
    result = OnlineRulePolicy(
        schema_catalog=SchemaCatalog(repository_root / "schemas" / "v1"),
        clock=lambda: 0.0,
    ).decide(request)
    story: tuple[str, ...]
    if result.candidate_transaction is not None:
        story = (
            f"{anonymous_vehicle_id} 请求离场，系统发现纵深阻挡。",
            "在线规则为每辆阻挡车匹配专用缓冲位。",
            "阻挡车先移至缓冲位，目标车辆随后离场。",
            "阻挡车恢复原位，事务才算完成。",
        )
    elif result.recommended_actions:
        story = (
            f"{anonymous_vehicle_id} 请求离场。",
            "当前位置到出口没有阻挡，在线规则推荐直接离场。",
        )
    else:
        story = (
            f"{anonymous_vehicle_id} 请求离场。",
            f"系统返回 {result.primary_decision.value}，没有生成自动移动动作。",
        )
    return SandboxDecision(
        decision_kind="DEPARTURE",
        input_state=input_state,
        request=request,
        result=result,
        candidates=(),
        selected_position_id=None,
        nearest_feasible_position_id=None,
        story_steps=story,
    )
