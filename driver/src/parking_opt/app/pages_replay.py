# ruff: noqa: RUF001
"""D3 saved-event replay page."""
from __future__ import annotations
import time
from pathlib import Path
import streamlit as st
from parking_opt.app.pages import _ReplayWorkspace, _replay_workspace
from parking_opt.app.static_layout import build_layout_figure, build_replay_view
from parking_opt.application.presentation import ImportRejectedError, ReplayNavigator
def _initial_replay_sequence(last_sequence_no: int) -> int:
    raw = st.query_params.get("seq", "16")
    if not isinstance(raw, str):
        return 0
    try:
        return min(max(int(raw), 0), last_sequence_no)
    except ValueError:
        st.warning("未知回放序号已拒绝，回退到初始帧。")
        return 0
def _set_replay_sequence(sequence_no: int) -> None:
    st.session_state["d3_sequence"] = sequence_no
    st.query_params["seq"] = str(sequence_no)
def _sync_replay_sequence_from_slider() -> None:
    _set_replay_sequence(int(st.session_state["d3_sequence_slider"]))
def _render_replay_transport(navigator: ReplayNavigator) -> tuple[tuple[str, ...], str | None]:
    timeline = navigator.timeline
    first, second = st.columns((2, 1))
    with first:
        selected_types = tuple(st.multiselect("事件类型过滤（仅影响步进/播放，不删除事件）", timeline.event_types, key="d3_event_types"))
    with second:
        transaction_options = ("全部事务", *timeline.transaction_ids)
        selected_transaction = st.selectbox("事务过滤", transaction_options, key="d3_transaction_filter")
    transaction_id = None if selected_transaction == "全部事务" else selected_transaction
    current = int(st.session_state["d3_sequence"])
    matching = navigator.matching_sequences(event_types=selected_types, transaction_id=transaction_id)
    if not matching:
        st.warning("当前过滤组合没有事件；位置保持不变。")
    play_col, previous_col, next_col, speed_col, position_col = st.columns((1, 1, 1, 1.2, 3.8))
    playing = bool(st.session_state.get("d3_playing", False))
    if play_col.button("暂停" if playing else "播放", icon=":material/pause:" if playing else ":material/play_arrow:", width="stretch"):
        st.session_state["d3_playing"] = not playing
        playing = not playing
    if previous_col.button("上一步", icon=":material/skip_previous:", width="stretch"):
        _set_replay_sequence(navigator.step(current, -1, event_types=selected_types, transaction_id=transaction_id))
    if next_col.button("下一步", icon=":material/skip_next:", width="stretch"):
        _set_replay_sequence(navigator.step(current, 1, event_types=selected_types, transaction_id=transaction_id))
    speed = float(speed_col.selectbox("播放速度", (0.5, 1.0, 2.0, 5.0, 10.0), index=1, format_func=lambda value: f"{value:g}×", key="d3_playback_speed"))
    slider_sequence = int(st.session_state["d3_sequence"])
    if st.session_state.get("d3_sequence_slider") != slider_sequence:
        st.session_state["d3_sequence_slider"] = slider_sequence
    position_col.slider("事件序号", navigator.index.first_sequence_no, navigator.index.last_sequence_no, key="d3_sequence_slider", on_change=_sync_replay_sequence_from_slider)
    st.query_params["seq"] = str(st.session_state["d3_sequence"])
    mode = st.radio("定位方式", ("事件序号", "仿真秒", "移位事务"), horizontal=True, key="d3_position_mode")
    if mode == "事件序号":
        jump = st.number_input("跳转到序号", min_value=navigator.index.first_sequence_no, max_value=navigator.index.last_sequence_no, value=int(st.session_state["d3_sequence"]), step=1, key="d3_jump_sequence")
        if st.button("执行序号跳转", icon=":material/arrow_forward:"):
            _set_replay_sequence(int(jump))
    elif mode == "仿真秒":
        second_value = st.number_input("跳转到仿真秒（取不晚于该时刻的最后确认事件）", min_value=0, value=navigator.frame(current).sim_time_s, step=1, key="d3_jump_time")
        if st.button("执行时间跳转", icon=":material/schedule:"):
            _set_replay_sequence(navigator.at_or_before_time(int(second_value)))
    else:
        if not timeline.transaction_ids:
            st.info("该日志没有移位事务。")
        else:
            transaction_jump = st.selectbox("选择事务", timeline.transaction_ids, key="d3_transaction_jump")
            beginning, ending = navigator.transaction_bounds(transaction_jump)
            left, right = st.columns(2)
            if left.button("跳到事务开始", width="stretch"):
                _set_replay_sequence(beginning)
            if right.button("跳到事务结束", width="stretch"):
                _set_replay_sequence(ending)
    if playing:
        next_sequence = navigator.step(int(st.session_state["d3_sequence"]), 1, event_types=selected_types, transaction_id=transaction_id)
        if next_sequence == int(st.session_state["d3_sequence"]):
            st.session_state["d3_playing"] = False
        else:
            _set_replay_sequence(next_sequence)
            time.sleep(1.0 / speed)
            st.rerun()
    return selected_types, transaction_id
def _render_resource_state(frame) -> None:  # type: ignore[no-untyped-def]
    st.subheader("资源与事务状态")
    executor, reservations, actions, transactions, pending = st.columns(5)
    executor.metric("移位执行器", f"{frame.executor_used}/{frame.executor_capacity}", border=True)
    reservations.metric("位置预留", frame.reservation_count, border=True)
    actions.metric("活动动作", frame.active_action_count, border=True)
    transactions.metric("累计事务", frame.transaction_count, border=True)
    pending.metric("待服务请求", frame.pending_request_count, border=True)
    if frame.channel_zone_usage:
        st.dataframe([{"通道区": zone, "占用": used, "容量": capacity} for zone, used, capacity in frame.channel_zone_usage], width="stretch", hide_index=True)
def _render_saved_event_audit(repository_root: Path) -> None:
    """Render the approved D3 replay without invoking simulation or optimization."""
    st.title("事件回放与移位事务")
    st.caption("保存日志前缀 → 确定性帧｜仅显示已确认状态｜不插值车辆轨迹")
    try:
        workspace = _replay_workspace(str(repository_root))
    except (ImportRejectedError, OSError, TypeError, ValueError) as exc:
        st.error("D3 合成回放包未通过 D1 只读校验，页面已失败关闭。")
        st.stop()
        raise AssertionError("st.stop() must interrupt execution") from exc
    navigator = workspace.navigator
    if "d3_sequence" not in st.session_state:
        st.session_state["d3_sequence"] = _initial_replay_sequence(navigator.index.last_sequence_no)
    st.badge("SYNTHETIC", color="blue", icon=":material/science:")
    st.badge("DETERMINISTIC PREFIX REPLAY", color="green", icon=":material/replay:")
    st.warning("该页面是仿真验证演示，不代表真实停车场效果，也不产生调度控制指令。")
    visual_mode = st.query_params.get("visual") == "1"
    if visual_mode:
        st.info("视觉核验模式：控制区暂时折叠；状态仍来自相同日志前缀。")
    else:
        _render_replay_transport(navigator)
    sequence_no = int(st.session_state["d3_sequence"])
    frame = navigator.frame(sequence_no)
    event = navigator.event_at(sequence_no)
    state_one, state_two, state_three = st.columns(3)
    state_one.metric("事件序号", f"{sequence_no}/{navigator.index.last_sequence_no}", border=True)
    state_two.metric("仿真时间", f"{frame.sim_time_s} s", border=True)
    state_three.metric("当前事件", frame.event_type or "INITIAL_STATE", border=True)
    view = build_replay_view(workspace.bundle.layout, frame, event)
    st.plotly_chart(
        build_layout_figure(view),
        width="stretch",
        theme=None,
        config={"displaylogo": False, "responsive": True, "scrollZoom": True, "modeBarButtonsToRemove": ["lasso2d", "select2d"]},
        key=f"d3-replay-{sequence_no}",
    )
    if view.warnings:
        st.error("状态警告：" + "、".join(view.warnings))
    _render_resource_state(frame)
    _render_replay_details(workspace, sequence_no)
    info = navigator.cache.info
    st.caption(f"受控帧缓存 {info.size}/{info.max_entries}｜命中 {info.hits}｜未命中 {info.misses}｜失效 {info.invalidations}")
def render_replay_page(repository_root: Path) -> None:
    """Render three plain-language algorithm stories plus the saved audit."""
    st.title("算法过程回放")
    st.caption("看见车辆、候选筛选、选择理由与管理层路径；默认使用可复现合成场景")
    st.badge("SYNTHETIC｜教学场景", color="blue", icon=":material/science:")
    st.badge("真实在线规则", color="green", icon=":material/route:")
    scenario = st.selectbox("选择一个完整故事", ("新车入场分配", "纵深阻挡移位", "无可行车位与等待"), key="story_scenario")
    if st.session_state.get("story_loaded_scenario") != scenario:
        st.session_state["story_loaded_scenario"] = scenario
        st.session_state["story_step"] = 0
        st.session_state["story_progress"] = 0.0
        st.session_state["story_playing"] = False
    try:
        template, decision = _story_workspace(str(repository_root), scenario)
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        st.error("固定讲解场景未通过校验，页面已失败关闭。")
        st.stop()
        raise AssertionError("st.stop() must interrupt execution") from exc
    step, speed = _render_story_controls(decision)
    st.info(decision.story_steps[step])
    figure, summary = build_sandbox_figure(template.layout, decision.input_state, decision=decision, story_step=step, route_progress=float(st.session_state.get("story_progress", 0.0)))
    st.plotly_chart(figure, width="stretch", theme=None, config={"displaylogo": False, "responsive": True, "scrollZoom": True, "modeBarButtonsToRemove": ["lasso2d", "select2d"]}, key=f"story-figure-{scenario}-{step}")
    occupied, feasible, excluded, primary = st.columns(4)
    occupied.metric("已停车车辆", summary.occupied_count, border=True)
    feasible.metric("可行候选", summary.feasible_candidate_count, border=True)
    excluded.metric("排除位置", summary.excluded_candidate_count, border=True)
    primary.metric("当前主决定", _primary_decision_label(decision.result.primary_decision), border=True)
    if decision.decision_kind == "ARRIVAL" and decision.candidates:
        _render_arrival_explanation(decision)
    elif decision.result.recommended_actions:
        st.markdown("**移位事务按以下顺序整体执行**")
        st.dataframe(_action_rows(decision), width="stretch", hide_index=True)
        st.caption("缓冲位不是普通停车位，只在移位事务中临时占用；事务结束后恢复。")
    else:
        st.warning("没有可行停车动作。系统保留等待、拒绝或人工处理状态，不会静默把车辆放进不可达、已占用或关闭的车位。")
        if decision.result.explanation_codes:
            st.caption("机器解释码：" + "、".join(decision.result.explanation_codes))
    st.warning("黄色车辆与蓝色路线是管理层面的路径演示，不是自动驾驶轨迹；本页不控制真实车辆，也不证明算法优于随机或就近停放。")
    with st.expander("高级事件审计｜原始 36 事件确定性回放", expanded=False):
        if st.checkbox("加载高级审计工具", key="load_saved_event_audit"):
            _render_saved_event_audit(repository_root)
        else:
            st.caption("按需加载保存日志、事务时线、资源状态和哈希证据。")
    if st.session_state.get("story_playing", False):
        progress = float(st.session_state.get("story_progress", 0.0))
        last_step = len(decision.story_steps) - 1
        if progress < 1.0:
            st.session_state["story_progress"] = min(progress + 0.25, 1.0)
        elif step < last_step:
            st.session_state["story_step"] = step + 1
            st.session_state["story_progress"] = 0.0
        else:
            st.session_state["story_playing"] = False
        time.sleep(0.22 / speed)
        st.rerun()
from parking_opt.app.pages import _story_workspace  # noqa: E402
from parking_opt.app.pages_replay_details import _render_replay_details  # noqa: E402
from parking_opt.app.pages_story import (  # noqa: E402
    _action_rows,
    _primary_decision_label,
    _render_arrival_explanation,
    _render_story_controls,
)
from parking_opt.app.sandbox_view import build_sandbox_figure  # noqa: E402
