# ruff: noqa: RUF001
"""Synthetic in-memory sandbox for explaining the approved online rule."""

from __future__ import annotations

import csv
import html
import io
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from parking_opt.contracts.canonical import canonical_sha256
from parking_opt.contracts.schema_validation import SchemaCatalog
from parking_opt.contracts.snapshot_projection import (
    observed_snapshot_to_mapping,
    project_observed_snapshot,
)
from parking_opt.domain.conversion import decision_result_to_mapping
from parking_opt.domain.enums import (
    ArrivalStatus,
    DepartureInformationSource,
    DepartureStatus,
    LocationKind,
    ManualStatus,
    PositionKind,
    PrimaryDecision,
    ReservationStatus,
)
from parking_opt.domain.invariants import assert_state_invariants
from parking_opt.domain.records import (
    Action,
    DecisionRequest,
    DecisionResult,
    DepartureInformation,
    LocationState,
    PendingRequest,
    VehicleState,
)
from parking_opt.domain.state import AuthoritativeState
from parking_opt.layout.factories import build_mixed_depth_layout
from parking_opt.layout.model import (
    BufferSlot,
    ChannelZone,
    Layout,
    RoadEdge,
    RoadNode,
    Slot,
    layout_to_mapping,
)
from parking_opt.layout.networkx_adapter import materialize_path_costs
from parking_opt.layout.state_adapter import initial_state_from_layout
from parking_opt.strategies.online_rule import (
    ArrivalCandidateAssessment,
    OnlineRulePolicy,
)

_SCHEMA_VERSION = "1.0.0"
_ALGORITHM_ID = "online-rule-v1"
_ALGORITHM_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class SandboxTemplate:
    """One validated synthetic layout and its crowded initial state."""

    template_id: str
    label: str
    note: str
    layout: Layout
    initial_state: AuthoritativeState


@dataclass(frozen=True, slots=True)
class CandidateExplanation:
    """Safe presentation projection of one online-rule arrival candidate."""

    rank: int | None
    position_id: str
    stack_group_id: str
    depth: int
    feasible: bool
    reason_codes: tuple[str, ...]
    distance_m: float | None
    incremental_unrecoverable_exposure: int | None
    incremental_blocked_vehicle_count: int | None
    remaining_one_step_assignable_capacity: int | None
    departure_order_mismatch_count: int | None
    score: tuple[object, ...] | None


@dataclass(frozen=True, slots=True)
class SandboxDecision:
    """One real online-rule decision plus its safe explanatory projection."""

    decision_kind: str
    input_state: AuthoritativeState
    request: DecisionRequest
    result: DecisionResult
    candidates: tuple[CandidateExplanation, ...]
    selected_position_id: str | None
    nearest_feasible_position_id: str | None
    story_steps: tuple[str, ...]


def _sandbox_config(layout: Layout) -> dict[str, Any]:
    return {
        "recoverability_policy": "risk_accepting",
        "rolling_enabled": False,
        "arrival_wait_capacity": 3,
        "max_arrival_wait_s": 120,
        "max_departure_wait_s": 300,
        "use_soft_departure_information": True,
        "rolling_window_s": 900,
        "optimization_budget_s": 1.0,
        "fallback_target_s": 0.1,
        "minimum_logging_reserve_s": 0.02,
        "max_requests_per_solve": 12,
        "max_positions_per_arrival": 8,
        "max_buffer_matchings_per_departure": 4,
        "max_action_plans_total": 64,
        "max_soft_future_records": 20,
        "buffer_count": len(layout.buffer_slots),
        "relocation_executor_capacity": 1,
        "executor_type": "simulation_only",
        "relocation_setup_s": 5.0,
        "relocation_speed_mps": 1.0,
        "active_buffer_position_ids": [item.position_id for item in layout.buffer_slots],
    }


def build_compact_sandbox_layout() -> Layout:
    """Build a readable 24-normal-position mixed-depth teaching layout."""

    nodes = (
        RoadNode("entry-main", 0.0, 0.0, "entrance"),
        *(
            RoadNode(f"access-{index:02d}", float(index * 10), 0.0, "position_access")
            for index in range(1, 7)
        ),
        RoadNode("exit-main", 70.0, 0.0, "exit"),
    )
    edges = tuple(
        RoadEdge(
            road_edge_id=f"road-{index:02d}",
            from_node_id=nodes[index - 1].road_node_id,
            to_node_id=nodes[index].road_node_id,
            distance_m=10.0,
            travel_time_s=10,
            directed=False,
            channel_zone_ids=("zone-main",),
        )
        for index in range(1, len(nodes))
    )
    independent = tuple(
        Slot(
            position_id=f"demo-i{index:02d}",
            x_m=float(index * 10),
            y_m=4.0,
            access_node_id=f"access-{index:02d}",
            stack_group_id=f"demo-ig{index:02d}",
            depth=1,
            channel_zone_ids=("zone-main",),
        )
        for index in range(1, 7)
    )
    tandem: list[Slot] = []
    for group_index in range(1, 10):
        access_index = ((group_index - 1) % 6) + 1
        row_index = (group_index - 1) // 6
        for depth in (1, 2):
            tandem.append(
                Slot(
                    position_id=f"demo-g{group_index:02d}-d{depth}",
                    x_m=float(access_index * 10),
                    y_m=float(10 + row_index * 7 + depth * 2),
                    access_node_id=f"access-{access_index:02d}",
                    stack_group_id=f"demo-g{group_index:02d}",
                    depth=depth,
                    channel_zone_ids=("zone-main",),
                )
            )
    layout = Layout(
        schema_version=_SCHEMA_VERSION,
        layout_id="synthetic-compact-crowded-v1",
        coordinate_origin_note="synthetic teaching layout in local metres; not surveyed",
        road_nodes=nodes,
        road_edges=edges,
        path_costs=(),
        slots=(*independent, *tandem),
        buffer_slots=(
            BufferSlot(
                position_id="demo-buffer-01",
                x_m=0.0,
                y_m=-7.0,
                access_node_id="entry-main",
                channel_zone_ids=("zone-main",),
            ),
        ),
        channel_zones=(ChannelZone("zone-main", 1),),
    )
    return materialize_path_costs(layout)


def _parked_vehicle(vehicle_id: str, position_id: str, *, admitted_at_s: int) -> VehicleState:
    return VehicleState(
        anonymous_vehicle_id=vehicle_id,
        location_state=LocationState(LocationKind.AT_POSITION, position_id),
        arrival_status=ArrivalStatus.ENTRY_COMPLETED,
        departure_status=DepartureStatus.NONE,
        manual_status=ManualStatus.NONE,
        ever_admitted=True,
        admitted_at_s=admitted_at_s,
        waiting_since_s=None,
        action_context_id=None,
        active_transaction_id=None,
        reservation_status=ReservationStatus.NONE,
        departure_information=DepartureInformation(
            expected_departure_time_s=None,
            source=DepartureInformationSource.UNKNOWN,
            known_at_time_s=admitted_at_s,
        ),
    )


def _populate_layout(
    layout: Layout,
    occupied_position_ids: tuple[str, ...],
    *,
    scenario_id: str,
) -> AuthoritativeState:
    state = initial_state_from_layout(
        layout,
        run_id=f"sandbox-{scenario_id}",
        scenario_id=scenario_id,
        active_buffer_position_ids=tuple(item.position_id for item in layout.buffer_slots),
        relocation_executor_capacity=1,
        arrival_wait_capacity=3,
        max_arrival_wait_s=120,
    )
    known_normal = {item.position_id for item in layout.slots}
    if not set(occupied_position_ids) <= known_normal:
        raise ValueError("sandbox occupied positions must be normal positions in the layout")
    vehicles = tuple(
        _parked_vehicle(f"车辆{chr(65 + index)}", position_id, admitted_at_s=index)
        for index, position_id in enumerate(occupied_position_ids)
    )
    vehicle_by_position = {
        position_id: vehicle.anonymous_vehicle_id
        for position_id, vehicle in zip(occupied_position_ids, vehicles, strict=True)
    }
    result = replace(
        state,
        sim_time_s=len(vehicles),
        vehicles=vehicles,
        positions=tuple(
            replace(item, occupant_vehicle_id=vehicle_by_position.get(item.position_id))
            for item in state.positions
        ),
    )
    assert_state_invariants(result)
    return result


def load_sandbox_template(template_id: str) -> SandboxTemplate:
    """Return a deterministic compact or full-size synthetic sandbox."""

    if template_id == "compact":
        layout = build_compact_sandbox_layout()
        occupied: tuple[str, ...] = (
            "demo-i01",
            "demo-i02",
            "demo-i03",
            "demo-g01-d2",
            "demo-g02-d1",
            "demo-g02-d2",
            "demo-g04-d2",
            "demo-g05-d1",
            "demo-g05-d2",
            "demo-g06-d2",
            "demo-g07-d1",
            "demo-g07-d2",
            "demo-g08-d2",
        )
        return SandboxTemplate(
            template_id="compact",
            label="紧凑拥挤场景｜24 个正常位",
            note="用于看清候选筛选、路径和纵深阻挡；全部数据为 synthetic。",
            layout=layout,
            initial_state=_populate_layout(
                layout,
                occupied,
                scenario_id="synthetic-compact-crowded",
            ),
        )
    if template_id == "full":
        layout = build_mixed_depth_layout(buffer_count=1)
        occupied = tuple(
            item.position_id
            for index, item in enumerate(sorted(layout.slots, key=lambda value: value.position_id))
            if index % 4 != 0
        )[:68]
        return SandboxTemplate(
            template_id="full",
            label="完整混合布局｜99 个正常位",
            note="用于缩放核对完整规模；默认讲解优先使用紧凑模板。",
            layout=layout,
            initial_state=_populate_layout(
                layout,
                occupied,
                scenario_id="synthetic-full-crowded",
            ),
        )
    raise ValueError("unknown sandbox template")


def _decision_request(
    state: AuthoritativeState,
    layout: Layout,
    *,
    trigger_event_type: str,
    target: PendingRequest,
) -> DecisionRequest:
    snapshot = project_observed_snapshot(
        state,
        snapshot_id=f"snapshot-{state.sequence_no}-{target.request_id}",
        decision_time_s=state.sim_time_s,
    )
    layout_mapping = layout_to_mapping(layout)
    config = _sandbox_config(layout)
    return DecisionRequest(
        request_id=f"decision-{target.request_id}",
        algorithm_id=_ALGORITHM_ID,
        algorithm_version=_ALGORITHM_VERSION,
        trigger_event_id=f"sandbox-event-{state.sequence_no}",
        trigger_event_type=trigger_event_type,
        trigger_request_id=target.request_id,
        trigger_anonymous_vehicle_id=target.anonymous_vehicle_id,
        decision_time_s=state.sim_time_s,
        layout=layout_mapping,
        approved_config=config,
        observed_snapshot=snapshot,
        config_sha256=canonical_sha256(config),
        layout_sha256=canonical_sha256(layout_mapping),
        visible_snapshot_sha256=snapshot.snapshot_content_sha256,
        decision_target_s=1.0,
        decision_deadline_s=3.0,
    )


def _candidate_projection(
    assessments: tuple[ArrivalCandidateAssessment, ...],
) -> tuple[CandidateExplanation, ...]:
    feasible = sorted(
        (item for item in assessments if item.feasible),
        key=lambda item: item.score or (),
    )
    rank_by_id = {item.position_id: rank for rank, item in enumerate(feasible, start=1)}
    return tuple(
        CandidateExplanation(
            rank=rank_by_id.get(item.position_id),
            position_id=item.position_id,
            stack_group_id=item.stack_group_id,
            depth=item.depth,
            feasible=item.feasible,
            reason_codes=item.reason_codes,
            distance_m=item.distance_m,
            incremental_unrecoverable_exposure=item.incremental_unrecoverable_exposure,
            incremental_blocked_vehicle_count=item.incremental_blocked_vehicle_count,
            remaining_one_step_assignable_capacity=item.remaining_one_step_assignable_capacity,
            departure_order_mismatch_count=item.departure_order_mismatch_count,
            score=item.score,
        )
        for item in sorted(
            assessments,
            key=lambda item: (
                0 if item.feasible else 1,
                item.score or (),
                item.position_id,
            ),
        )
    )


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
        reservation_status=(
            ReservationStatus.CONFIRMED if has_reservation else ReservationStatus.NONE
        ),
        departure_information=DepartureInformation(
            expected_departure_time_s=expected_departure_time_s,
            source=source,
            known_at_time_s=decision_time_s,
            source_record_id=(
                f"sandbox-{vehicle_id}-departure" if expected_departure_time_s is not None else None
            ),
        ),
    )
    input_state = replace(
        state,
        sequence_no=state.sequence_no + 1,
        sim_time_s=decision_time_s,
        vehicles=tuple(
            sorted((*state.vehicles, vehicle), key=lambda item: item.anonymous_vehicle_id)
        ),
        pending_requests=(*state.pending_requests, target),
    )
    assert_state_invariants(input_state)
    request = _decision_request(
        input_state,
        layout,
        trigger_event_type="ARRIVAL_REQUESTED",
        target=target,
    )
    policy = OnlineRulePolicy(
        schema_catalog=SchemaCatalog(repository_root / "schemas" / "v1"),
        clock=lambda: 0.0,
    )
    result = policy.decide(request)
    candidates = _candidate_projection(policy.explain_arrival_candidates(request))
    feasible = tuple(item for item in candidates if item.feasible)
    selected = next(
        (
            action.destination_position_id
            for action in result.recommended_actions
            if action.destination_position_id is not None
        ),
        None,
    )
    nearest = min(
        feasible,
        key=lambda item: (
            item.distance_m if item.distance_m is not None else float("inf"),
            item.position_id,
        ),
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
    request = _decision_request(
        input_state,
        layout,
        trigger_event_type="DEPARTURE_REQUESTED",
        target=target,
    )
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


def confirm_sandbox_decision(decision: SandboxDecision) -> AuthoritativeState:
    """Apply a successful sandbox recommendation as one confirmed final state."""

    result = decision.result
    state = decision.input_state
    target_id = result.target_anonymous_vehicle_id
    if result.primary_decision is not PrimaryDecision.RECOMMEND_ACTIONS:
        raise ValueError("only a recommended sandbox action can be confirmed")
    if decision.decision_kind == "ARRIVAL":
        destination = decision.selected_position_id
        if destination is None:
            raise ValueError("arrival decision has no selected destination")
        confirmed = replace(
            state,
            sequence_no=state.sequence_no + 1,
            vehicles=tuple(
                replace(
                    item,
                    location_state=LocationState(LocationKind.AT_POSITION, destination),
                    arrival_status=ArrivalStatus.ENTRY_COMPLETED,
                    ever_admitted=True,
                    admitted_at_s=state.sim_time_s,
                    waiting_since_s=None,
                )
                if item.anonymous_vehicle_id == target_id
                else item
                for item in state.vehicles
            ),
            positions=tuple(
                replace(item, occupant_vehicle_id=target_id)
                if item.position_id == destination
                else item
                for item in state.positions
            ),
            pending_requests=tuple(
                item
                for item in state.pending_requests
                if item.request_id != result.target_request_id
            ),
        )
    elif decision.decision_kind == "DEPARTURE":
        origin = next(
            item.location_state.position_id
            for item in state.vehicles
            if item.anonymous_vehicle_id == target_id
        )
        confirmed = replace(
            state,
            sequence_no=state.sequence_no + 1,
            vehicles=tuple(
                replace(
                    item,
                    location_state=LocationState(LocationKind.EXITED),
                    departure_status=DepartureStatus.COMPLETED,
                    waiting_since_s=None,
                )
                if item.anonymous_vehicle_id == target_id
                else item
                for item in state.vehicles
            ),
            positions=tuple(
                replace(item, occupant_vehicle_id=None) if item.position_id == origin else item
                for item in state.positions
            ),
            pending_requests=tuple(
                item
                for item in state.pending_requests
                if item.request_id != result.target_request_id
            ),
        )
    else:
        raise ValueError("unsupported sandbox decision kind")
    assert_state_invariants(confirmed)
    return confirmed


def set_position_closed(
    state: AuthoritativeState,
    position_id: str,
    *,
    closed: bool,
) -> AuthoritativeState:
    """Close or reopen an unoccupied normal sandbox position."""

    target = next((item for item in state.positions if item.position_id == position_id), None)
    if target is None or target.position_kind is not PositionKind.NORMAL:
        raise ValueError("only a known normal position can be edited")
    if closed and target.occupant_vehicle_id is not None:
        raise ValueError("an occupied position cannot be closed")
    result = replace(
        state,
        sequence_no=state.sequence_no + 1,
        positions=tuple(
            replace(
                item,
                physically_available=not closed,
                assignable=not closed,
                planned_closure=closed,
            )
            if item.position_id == position_id
            else item
            for item in state.positions
        ),
    )
    assert_state_invariants(result)
    return result


def remove_parked_vehicle(
    state: AuthoritativeState, anonymous_vehicle_id: str
) -> AuthoritativeState:
    """Remove one parked synthetic vehicle from the editable sandbox."""

    vehicle = next(
        (
            item
            for item in state.vehicles
            if item.anonymous_vehicle_id == anonymous_vehicle_id
            and item.location_state.kind is LocationKind.AT_POSITION
        ),
        None,
    )
    if vehicle is None or vehicle.location_state.position_id is None:
        raise ValueError("only a parked sandbox vehicle can be removed")
    position_id = vehicle.location_state.position_id
    result = replace(
        state,
        sequence_no=state.sequence_no + 1,
        vehicles=tuple(
            item for item in state.vehicles if item.anonymous_vehicle_id != anonymous_vehicle_id
        ),
        positions=tuple(
            replace(item, occupant_vehicle_id=None) if item.position_id == position_id else item
            for item in state.positions
        ),
        pending_requests=tuple(
            item
            for item in state.pending_requests
            if item.anonymous_vehicle_id != anonymous_vehicle_id
        ),
    )
    assert_state_invariants(result)
    return result


def decision_downloads(decision: SandboxDecision, layout: Layout) -> dict[str, bytes]:
    """Build browser-download artifacts without writing to the repository."""

    scenario = {
        "schema_version": _SCHEMA_VERSION,
        "data_source": "synthetic",
        "purpose": "interactive_demo",
        "layout": layout_to_mapping(layout),
        "observed_snapshot": observed_snapshot_to_mapping(decision.request.observed_snapshot),
    }
    decision_mapping = decision_result_to_mapping(decision.result)
    csv_buffer = io.StringIO(newline="")
    writer = csv.writer(csv_buffer)
    writer.writerow(
        (
            "rank",
            "position_id",
            "feasible",
            "reason_codes",
            "distance_m",
            "incremental_blocked_vehicle_count",
            "remaining_one_step_assignable_capacity",
        )
    )
    for item in decision.candidates:
        writer.writerow(
            (
                item.rank or "",
                item.position_id,
                item.feasible,
                "|".join(item.reason_codes),
                "" if item.distance_m is None else item.distance_m,
                ""
                if item.incremental_blocked_vehicle_count is None
                else item.incremental_blocked_vehicle_count,
                ""
                if item.remaining_one_step_assignable_capacity is None
                else item.remaining_one_step_assignable_capacity,
            )
        )
    selected = decision.selected_position_id or "未选择车位"
    summary = f"""<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><title>智能停车沙盒决策摘要</title>
<style>body{{font-family:system-ui,sans-serif;max-width:860px;margin:40px auto;line-height:1.7}}
table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #cbd5e1;padding:8px;text-align:left}}
.note{{background:#eff6ff;padding:12px;border-radius:8px}}</style>
<h1>智能停车沙盒决策摘要</h1>
<p class="note">SYNTHETIC｜仅用于算法流程演示，不构成真实停车场效果或性能优越性结论。</p>
<p><strong>匿名车辆：</strong>{html.escape(decision.result.target_anonymous_vehicle_id)}</p>
<p><strong>主决定：</strong>{html.escape(decision.result.primary_decision.value)}</p>
<p><strong>选择位置：</strong>{html.escape(selected)}</p>
<h2>过程说明</h2>
<ol>{"".join(f"<li>{html.escape(step)}</li>" for step in decision.story_steps)}</ol>
</html>"""
    return {
        "scenario.json": json.dumps(scenario, ensure_ascii=False, indent=2).encode("utf-8"),
        "decision-result.json": json.dumps(
            decision_mapping,
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8"),
        "candidate-comparison.csv": ("\ufeff" + csv_buffer.getvalue()).encode("utf-8"),
        "decision-summary.html": summary.encode("utf-8"),
    }


def action_route_coordinates(layout: Layout, action: Action) -> tuple[tuple[float, float], ...]:
    """Return management-level route coordinates from saved path edge IDs."""

    normal = {item.position_id: item for item in layout.slots}
    buffers = {item.position_id: item for item in layout.buffer_slots}
    nodes = {item.road_node_id: item for item in layout.road_nodes}
    edges = {item.road_edge_id: item for item in layout.road_edges}
    trailing: tuple[tuple[float, float], ...]
    if action.origin_position_id is None:
        start_node_id = next(
            item.road_node_id for item in layout.road_nodes if item.node_kind == "entrance"
        )
        leading: tuple[tuple[float, float], ...] = ()
    else:
        origin = normal.get(action.origin_position_id) or buffers.get(action.origin_position_id)
        if origin is None:
            return ()
        start_node_id = origin.access_node_id
        leading = ((origin.x_m, origin.y_m),)
    if action.destination_position_id is not None:
        destination = normal.get(action.destination_position_id) or buffers.get(
            action.destination_position_id
        )
        if destination is None:
            return ()
        end_node_id = destination.access_node_id
        trailing = ((destination.x_m, destination.y_m),)
    elif action.destination_exit_id is not None:
        end_node_id = action.destination_exit_id
        trailing = ()
    else:
        return ()
    path = next(
        (
            item
            for item in layout.path_costs
            if item.from_node_id == start_node_id and item.to_node_id == end_node_id
        ),
        None,
    )
    if path is None:
        return ()
    current = start_node_id
    ordered_nodes = [current]
    for edge_id in path.road_edge_ids:
        edge = edges[edge_id]
        if edge.from_node_id == current:
            current = edge.to_node_id
        elif not edge.directed and edge.to_node_id == current:
            current = edge.from_node_id
        else:
            return ()
        ordered_nodes.append(current)
    road_points = tuple((nodes[node_id].x_m, nodes[node_id].y_m) for node_id in ordered_nodes)
    return (*leading, *road_points, *trailing)


__all__ = [
    "CandidateExplanation",
    "SandboxDecision",
    "SandboxTemplate",
    "action_route_coordinates",
    "build_compact_sandbox_layout",
    "confirm_sandbox_decision",
    "decision_downloads",
    "load_sandbox_template",
    "preview_arrival",
    "preview_departure",
    "remove_parked_vehicle",
    "set_position_closed",
]
