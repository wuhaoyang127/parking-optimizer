# ruff: noqa: RUF001
"""Interactive sandbox rendering."""
from __future__ import annotations
from pathlib import Path
import streamlit as st
from parking_opt.app.pages import _sandbox_template
from parking_opt.app.pages_story import _action_rows, _primary_decision_label, _render_arrival_explanation
from parking_opt.app.sandbox_view import build_sandbox_figure
from parking_opt.application.sandbox import (
    SandboxDecision,
    SandboxTemplate,
    confirm_sandbox_decision,
    decision_downloads,
    preview_arrival,
    preview_departure,
    remove_parked_vehicle,
    set_position_closed,
)
from parking_opt.domain.enums import LocationKind, PrimaryDecision
def _sandbox_state_for(template: SandboxTemplate):  # type: ignore[no-untyped-def]
    if st.session_state.get("sandbox_active_template_id") != template.template_id:
        st.session_state["sandbox_active_template_id"] = template.template_id
        st.session_state["sandbox_state"] = template.initial_state
        st.session_state["sandbox_decision"] = None
    return st.session_state["sandbox_state"]
def _render_sandbox_decision(
    repository_root: Path,
    template: SandboxTemplate,
    decision: SandboxDecision,
) -> None:
    primary = decision.result.primary_decision
    st.subheader("本次真实规则结果")
    result_col, vehicle_col, destination_col = st.columns(3)
    result_col.metric("主决定", _primary_decision_label(primary), border=True)
    vehicle_col.metric("匿名车辆", decision.result.target_anonymous_vehicle_id, border=True)
    destination_col.metric("推荐车位", decision.selected_position_id or "无", border=True)
    if decision.decision_kind == "ARRIVAL" and decision.candidates:
        _render_arrival_explanation(decision)
    elif decision.result.recommended_actions:
        st.dataframe(_action_rows(decision), width="stretch", hide_index=True)
    else:
        st.warning("本次没有可确认的自动动作，状态将保持等待、拒绝或人工处理。")
        if decision.result.explanation_codes:
            st.caption("机器解释码：" + "、".join(decision.result.explanation_codes))
    confirm_col, reset_col = st.columns(2)
    if confirm_col.button("确认并更新当前场景", type="primary", width="stretch", disabled=primary is not PrimaryDecision.RECOMMEND_ACTIONS, key="sandbox_confirm_decision"):
        try:
            st.session_state["sandbox_state"] = confirm_sandbox_decision(decision)
            st.session_state["sandbox_decision"] = None
            st.success("决定已在当前浏览器会话中确认；可以继续提交下一辆车。")
            st.rerun()
        except ValueError:
            st.error("当前结果不能确认，场景状态未改变。")
    if reset_col.button("放弃本次预览", width="stretch", key="sandbox_discard_decision"):
        st.session_state["sandbox_decision"] = None
        st.rerun()
    downloads = decision_downloads(decision, template.layout)
    st.markdown("**下载本次演示证据**")
    download_columns = st.columns(4)
    download_specs = (("场景 JSON", "scenario.json", "application/json"), ("决策 JSON", "decision-result.json", "application/json"), ("候选 CSV", "candidate-comparison.csv", "text/csv"), ("中文 HTML 摘要", "decision-summary.html", "text/html"))
    for column, (label, filename, mime) in zip(download_columns, download_specs, strict=True):
        column.download_button(label, downloads[filename], file_name=filename, mime=mime, width="stretch", key=f"sandbox-download-{filename}")
    st.caption("HTML 摘要可在浏览器中打开并使用“打印 → 另存为 PDF”。")
def render_sandbox_page(repository_root: Path) -> None:
    """Render a bounded, session-only synthetic online-rule sandbox."""
    st.title("交互式车位分配")
    st.caption("自己提交匿名车辆的入场或离场请求，查看在线规则如何筛选和分配")
    st.badge("SYNTHETIC｜仅当前会话", color="blue", icon=":material/science:")
    st.badge("不写入正式输出", color="gray", icon=":material/memory:")
    st.warning("请勿输入车牌、姓名、手机号等个人信息。这里运行的是合成内存沙盒；刷新或重置后可恢复模板，不会向真实停车场发送控制指令。")
    template_id = st.radio("场景规模", ("compact", "full"), format_func=lambda value: ("紧凑拥挤场景｜24 个正常位" if value == "compact" else "完整混合布局｜99 个正常位"), horizontal=True, key="sandbox_template_choice")
    template = _sandbox_template(template_id)
    state = _sandbox_state_for(template)
    header, reset = st.columns((4, 1))
    header.info(template.note)
    if reset.button("重置模板", icon=":material/restart_alt:", width="stretch", key="sandbox_reset_template"):
        st.session_state["sandbox_state"] = template.initial_state
        st.session_state["sandbox_decision"] = None
        st.rerun()
    occupied_count = sum(item.occupant_vehicle_id is not None for item in state.positions)
    closed_count = sum(not item.physically_available or item.planned_closure for item in state.positions)
    first, second, third, fourth = st.columns(4)
    first.metric("场景时间", f"{state.sim_time_s} s", border=True)
    second.metric("已停车车辆", occupied_count, border=True)
    third.metric("关闭位置", closed_count, border=True)
    fourth.metric("状态版本", state.sequence_no, border=True)
    arrival_tab, departure_tab, edit_tab = st.tabs(("新车入场", "车辆离场", "场景编辑"))
    with arrival_tab:
        with st.form("sandbox_arrival_form"):
            vehicle_col, entrance_col, time_col = st.columns(3)
            vehicle_id = vehicle_col.text_input("匿名车辆标签", value=f"新车{state.sequence_no + 1}", max_chars=32, help="只使用 A、B、C 或“新车N”等匿名标签。")
            entrances = tuple(item.road_node_id for item in template.layout.road_nodes if item.node_kind == "entrance")
            entrance_id = entrance_col.selectbox("入口", entrances)
            decision_time = int(time_col.number_input("到达时间（秒）", min_value=int(state.sim_time_s), value=int(state.sim_time_s + 10), step=1))
            reservation_col, known_departure_col = st.columns(2)
            has_reservation = reservation_col.checkbox("有合法预约")
            known_departure = known_departure_col.checkbox("提供预计离场时间")
            expected_departure = None
            if known_departure:
                expected_departure = int(st.number_input("预计离场时间（秒）", min_value=decision_time + 1, value=decision_time + 600, step=1))
            arrival_preview = st.form_submit_button("运行在线规则并预览", type="primary", width="stretch")
        if arrival_preview:
            try:
                st.session_state["sandbox_decision"] = preview_arrival(repository_root, state, template.layout, anonymous_vehicle_id=vehicle_id, entrance_node_id=entrance_id, decision_time_s=decision_time, has_reservation=has_reservation, expected_departure_time_s=expected_departure)
            except (TypeError, ValueError, RuntimeError):
                st.error("入场输入未通过校验或规则无法安全运行；场景状态没有改变。")
    with departure_tab:
        parked = tuple(item.anonymous_vehicle_id for item in state.vehicles if item.location_state.kind is LocationKind.AT_POSITION)
        if not parked:
            st.info("当前没有可提交离场请求的车辆。")
        else:
            with st.form("sandbox_departure_form"):
                departure_vehicle = st.selectbox("选择已停车车辆", parked)
                departure_time = int(st.number_input("离场请求时间（秒）", min_value=int(state.sim_time_s), value=int(state.sim_time_s + 10), step=1, key="sandbox_departure_time"))
                departure_preview = st.form_submit_button("运行在线规则并预览", type="primary", width="stretch")
            if departure_preview:
                try:
                    st.session_state["sandbox_decision"] = preview_departure(repository_root, state, template.layout, anonymous_vehicle_id=departure_vehicle, decision_time_s=departure_time)
                except (TypeError, ValueError, RuntimeError):
                    st.error("离场输入未通过校验或规则无法安全运行；场景状态没有改变。")
    with edit_tab:
        st.caption("编辑范围受限：只能关闭/开放空闲普通位，或移除一辆已停车的合成车辆。")
        normal_positions = tuple(item for item in state.positions if item.position_id in {slot.position_id for slot in template.layout.slots})
        position_id = st.selectbox("普通车位", tuple(item.position_id for item in normal_positions), key="sandbox_edit_position")
        position_state = next(item for item in normal_positions if item.position_id == position_id)
        close_col, open_col = st.columns(2)
        if close_col.button("关闭所选空位", width="stretch", disabled=position_state.occupant_vehicle_id is not None, key="sandbox_close_position"):
            try:
                st.session_state["sandbox_state"] = set_position_closed(state, position_id, closed=True)
                st.session_state["sandbox_decision"] = None
                st.rerun()
            except ValueError:
                st.error("该位置不能关闭，场景状态没有改变。")
        if open_col.button("重新开放所选位", width="stretch", key="sandbox_open_position"):
            try:
                st.session_state["sandbox_state"] = set_position_closed(state, position_id, closed=False)
                st.session_state["sandbox_decision"] = None
                st.rerun()
            except ValueError:
                st.error("该位置不能开放，场景状态没有改变。")
        if parked:
            remove_vehicle = st.selectbox("移除一辆合成车辆", parked, key="sandbox_remove_vehicle")
            if st.button("移除并释放车位", width="stretch", key="sandbox_remove_vehicle_button"):
                try:
                    st.session_state["sandbox_state"] = remove_parked_vehicle(state, remove_vehicle)
                    st.session_state["sandbox_decision"] = None
                    st.rerun()
                except ValueError:
                    st.error("该车辆不能移除，场景状态没有改变。")
    decision = st.session_state.get("sandbox_decision")
    display_state = state if decision is None else decision.input_state
    figure, summary = build_sandbox_figure(template.layout, display_state, decision=decision, story_step=999, route_progress=1.0)
    st.plotly_chart(figure, width="stretch", theme=None, config={"displaylogo": False, "responsive": True, "scrollZoom": True, "modeBarButtonsToRemove": ["lasso2d", "select2d"]}, key=f"sandbox-figure-{template.template_id}-{state.sequence_no}")
    st.caption(f"图中已占用 {summary.occupied_count}｜空闲 {summary.free_count}｜关闭 {summary.closed_count}；车辆标签均为合成匿名标签。")
    if isinstance(decision, SandboxDecision):
        _render_sandbox_decision(repository_root, template, decision)
