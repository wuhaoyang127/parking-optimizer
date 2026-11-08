"""Sandbox initial-state population and template loading."""

from __future__ import annotations

from dataclasses import replace

from parking_opt.application.sandbox_layout import build_compact_sandbox_layout
from parking_opt.application.sandbox_types import SandboxTemplate
from parking_opt.domain.enums import (
    ArrivalStatus,
    DepartureInformationSource,
    DepartureStatus,
    LocationKind,
    ManualStatus,
    ReservationStatus,
)
from parking_opt.domain.invariants import assert_state_invariants
from parking_opt.domain.records import DepartureInformation, LocationState, VehicleState
from parking_opt.domain.state import AuthoritativeState
from parking_opt.layout.factories import build_mixed_depth_layout
from parking_opt.layout.model import Layout
from parking_opt.layout.state_adapter import initial_state_from_layout


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
            initial_state=_populate_layout(layout, occupied, scenario_id="synthetic-compact-crowded"),
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
            initial_state=_populate_layout(layout, occupied, scenario_id="synthetic-full-crowded"),
        )
    raise ValueError("unknown sandbox template")
