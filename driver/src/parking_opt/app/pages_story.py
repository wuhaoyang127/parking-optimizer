# ruff: noqa: RUF001
"""Shared story and decision rendering helpers."""

from __future__ import annotations

import streamlit as st

from parking_opt.app.sandbox_view import candidate_rows
from parking_opt.application.sandbox import SandboxDecision
from parking_opt.domain.enums import PrimaryDecision


def _primary_decision_label(decision: PrimaryDecision) -> str:
    return {
        PrimaryDecision.RECOMMEND_ACTIONS: "推荐动作",
        PrimaryDecision.WAIT: "等待",
        PrimaryDecision.REJECT: "拒绝",
        PrimaryDecision.REQUEST_MANUAL_INTERVENTION: "请求人工",
    }.get(decision, decision.value)


def _action_rows(decision: SandboxDecision) -> list[dict[str, object]]:
    return [
        {
            "顺序": index,
            "车辆": action.anonymous_vehicle_id,
            "动作": {"PARK": "驶入车位", "RELOCATE_TO_BUFFER": "移至缓冲位", "DEPART": "驶向出口", "RESTORE_FROM_BUFFER": "从缓冲位恢复"}.get(action.action_type.value, action.action_type.value),
            "起点": action.origin_position_id or "入口",
            "终点": action.destination_position_id or action.destination_exit_id or "—",
            "距离": f"{action.distance_m:.1f} m",
            "预计用时": f"{action.modeled_duration_s} s",
        }
        for index, action in enumerate(decision.result.recommended_actions, start=1)
    ]


def _render_arrival_explanation(decision: SandboxDecision) -> None:
    chosen = next((item for item in decision.candidates if item.position_id == decision.selected_position_id), None)
    nearest = next((item for item in decision.candidates if item.position_id == decision.nearest_feasible_position_id), None)
    selected_col, nearest_col, meaning_col = st.columns(3)
    selected_col.metric("在线规则选择", decision.selected_position_id or "无", border=True)
    nearest_col.metric("最近可行车位", decision.nearest_feasible_position_id or "无", border=True)
    if chosen is not None and nearest is not None:
        meaning_col.metric("本次选择是否仅看距离", "否" if chosen.position_id != nearest.position_id else "本例相同", border=True)
        if chosen.position_id != nearest.position_id:
            st.info(
                f"本次最近可行位 `{nearest.position_id}` 距离 {nearest.distance_m:.1f} m，但会新增 {nearest.incremental_blocked_vehicle_count} 个阻挡；"
                f"规则选择 `{chosen.position_id}`，距离 {chosen.distance_m:.1f} m，新增阻挡为 {chosen.incremental_blocked_vehicle_count}。"
                "这只解释当前单次决定，不是正式算法对照实验。"
            )
    top_rows = [row for row in candidate_rows(decision, feasible_limit=5) if row["结果"] != "已排除"]
    st.markdown("**前 5 个可行候选（真实词典序，不是加权总分）**")
    st.dataframe(top_rows, width="stretch", hide_index=True)
    with st.expander("查看被排除的车位及原因", expanded=False):
        excluded = [row for row in candidate_rows(decision) if row["结果"] == "已排除"]
        st.dataframe(excluded, width="stretch", hide_index=True)


def _render_story_controls(decision: SandboxDecision) -> tuple[int, float]:
    last_step = len(decision.story_steps) - 1
    step = min(int(st.session_state.get("story_step", 0)), last_step)
    progress = float(st.session_state.get("story_progress", 0.0))
    playing = bool(st.session_state.get("story_playing", False))
    play_col, previous_col, next_col, replay_col, speed_col = st.columns((1.1, 1, 1, 1, 1.3))
    if play_col.button("暂停" if playing else "开始演示", icon=":material/pause:" if playing else ":material/play_arrow:", width="stretch", key="story_play_toggle"):
        st.session_state["story_playing"] = not playing
        st.rerun()
    if previous_col.button("上一步", icon=":material/skip_previous:", width="stretch", key="story_previous"):
        st.session_state["story_step"] = max(step - 1, 0)
        st.session_state["story_progress"] = 0.0
        st.session_state["story_playing"] = False
        st.rerun()
    if next_col.button("下一步", icon=":material/skip_next:", width="stretch", key="story_next"):
        st.session_state["story_step"] = min(step + 1, last_step)
        st.session_state["story_progress"] = 0.0
        st.session_state["story_playing"] = False
        st.rerun()
    if replay_col.button("重新播放", icon=":material/replay:", width="stretch", key="story_replay"):
        st.session_state["story_step"] = 0
        st.session_state["story_progress"] = 0.0
        st.session_state["story_playing"] = True
        st.rerun()
    speed = float(speed_col.selectbox("演示速度", (0.5, 1.0, 2.0), index=1, format_func=lambda value: f"{value:g}×", key="story_speed"))
    st.progress(min((step + progress) / max(len(decision.story_steps), 1), 1.0), text=f"第 {step + 1}/{len(decision.story_steps)} 步")
    return step, speed
