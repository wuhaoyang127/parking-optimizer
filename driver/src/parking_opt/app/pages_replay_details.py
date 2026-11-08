# ruff: noqa: RUF001
"""D3 replay details tabs."""

from __future__ import annotations

import streamlit as st

from parking_opt.app.pages import _ReplayWorkspace


def _render_replay_details(workspace: _ReplayWorkspace, sequence_no: int) -> None:
    navigator = workspace.navigator
    frame = navigator.frame(sequence_no)
    event = navigator.event_at(sequence_no)
    st.subheader("事件、车辆与位置检查")
    event_tab, vehicle_tab, position_tab, transaction_tab = st.tabs(("事件详情", "车辆详情", "位置详情", "事务时线"))
    with event_tab:
        if event is None:
            st.info("序号 0 是初始帧，没有已确认事件。")
        else:
            st.dataframe(
                [
                    {"字段": "event_id", "值": event.event_id},
                    {"字段": "event_type", "值": event.event_type},
                    {"字段": "category", "值": event.category},
                    {"字段": "summary", "值": event.summary},
                    *({"字段": key, "值": value} for key, value in event.detail_items),
                ],
                width="stretch",
                hide_index=True,
            )
    with vehicle_tab:
        if not frame.vehicles:
            st.info("当前前缀尚无车辆状态。")
        else:
            vehicle_id = st.selectbox("匿名车辆", tuple(item.anonymous_vehicle_id for item in frame.vehicles), key="d3_vehicle_detail")
            vehicle = next(item for item in frame.vehicles if item.anonymous_vehicle_id == vehicle_id)
            st.dataframe([{"匿名车辆": vehicle.anonymous_vehicle_id, "位置状态": vehicle.location_kind, "位置": vehicle.position_id or "—", "到达服务": vehicle.arrival_status, "离场服务": vehicle.departure_status, "人工状态": vehicle.manual_status}], width="stretch", hide_index=True)
    with position_tab:
        position_id = st.selectbox("位置", tuple(item.position_id for item in frame.positions), key="d3_position_detail")
        position = next(item for item in frame.positions if item.position_id == position_id)
        st.dataframe([{"位置": position.position_id, "类型": position.position_kind, "纵深组": position.stack_group_id or "—", "depth": position.depth or "—", "匿名车辆": position.occupant_vehicle_id or "—", "物理可用": position.physically_available, "可分配": position.assignable, "阻挡车辆": "、".join(position.blocker_vehicle_ids) or "—"}], width="stretch", hide_index=True)
    with transaction_tab:
        transaction_id = (
            event.transaction_id
            if event is not None and event.transaction_id is not None
            else next((item.transaction_id for item in reversed(navigator.timeline.events[:sequence_no]) if item.transaction_id is not None), None)
        )
        if transaction_id is None:
            st.info("当前前缀尚未关联移位事务。")
        else:
            rows = [
                {"序号": item.sequence_no, "仿真秒": item.sim_time_s, "事件": item.event_type, "动作": "—" if item.action is None else item.action.action_type, "动作状态": "—" if item.action is None else item.action.status, "事务阶段": item.transaction_status or "—"}
                for item in navigator.timeline.events
                if item.transaction_id == transaction_id
            ]
            st.caption(f"事务 `{transaction_id}`｜按保存事件序号离散回放")
            st.dataframe(rows, width="stretch", hide_index=True)
