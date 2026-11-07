# ruff: noqa: RUF001
"""Streamlit pages for the D2 shell and static layout."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import streamlit as st

from parking_opt.app.data import (
    DemoCatalog,
    load_builtin_adaptation_report,
    load_builtin_catalog,
    load_builtin_evidence,
    load_builtin_replay,
)
from parking_opt.app.design import (
    POSITION_STATUS_SPECS,
    SCREENSHOT_STATE_SPECS,
    ScreenshotState,
)
from parking_opt.app.metrics_view import (
    METRIC_LABELS,
    UNIT_LABELS,
    build_ratio_comparison_figure,
)
from parking_opt.app.sandbox_view import (
    build_sandbox_figure,
    candidate_rows,
)
from parking_opt.app.static_layout import (
    build_layout_figure,
    build_replay_view,
    build_static_view,
    parse_screenshot_state,
)
from parking_opt.application.presentation import (
    ComparisonEvidenceError,
    ComparisonEvidenceView,
    ImportRejectedError,
    ReplayNavigator,
    ValidatedDemoBundle,
    build_replay_index,
    build_replay_timeline,
    decision_audit,
)
from parking_opt.application.sandbox import (
    SandboxDecision,
    SandboxTemplate,
    confirm_sandbox_decision,
    decision_downloads,
    load_sandbox_template,
    preview_arrival,
    preview_departure,
    remove_parked_vehicle,
    set_position_closed,
)
from parking_opt.domain.enums import LocationKind, PrimaryDecision


@st.cache_resource(show_spinner=False)
def _catalog(repository_root: str) -> DemoCatalog:
    return load_builtin_catalog(Path(repository_root))


@dataclass(frozen=True, slots=True)
class _ReplayWorkspace:
    bundle: ValidatedDemoBundle
    navigator: ReplayNavigator


@st.cache_resource(show_spinner=False)
def _replay_workspace(repository_root: str) -> _ReplayWorkspace:
    bundle = load_builtin_replay(Path(repository_root))
    return _ReplayWorkspace(
        bundle=bundle,
        navigator=ReplayNavigator(
            build_replay_index(bundle, checkpoint_interval=32),
            build_replay_timeline(bundle),
            cache_entries=128,
        ),
    )


@st.cache_resource(show_spinner=False)
def _comparison_evidence(repository_root: str) -> ComparisonEvidenceView:
    return load_builtin_evidence(Path(repository_root))


@st.cache_resource(show_spinner=False)
def _sandbox_template(template_id: str) -> SandboxTemplate:
    return load_sandbox_template(template_id)


@st.cache_resource(show_spinner=False)
def _story_workspace(
    repository_root: str,
    scenario: str,
) -> tuple[SandboxTemplate, SandboxDecision]:
    template = load_sandbox_template("compact")
    decision_time_s = template.initial_state.sim_time_s + 7
    if scenario == "新车入场分配":
        decision = preview_arrival(
            Path(repository_root),
            template.initial_state,
            template.layout,
            anonymous_vehicle_id="新车N",
            entrance_node_id="entry-main",
            decision_time_s=decision_time_s,
            has_reservation=False,
            expected_departure_time_s=None,
        )
    elif scenario == "纵深阻挡移位":
        decision = preview_departure(
            Path(repository_root),
            template.initial_state,
            template.layout,
            anonymous_vehicle_id="车辆F",
            decision_time_s=decision_time_s,
        )
    elif scenario == "无可行车位与等待":
        closed = template.initial_state
        for position in closed.positions:
            if position.position_kind.value == "normal" and position.occupant_vehicle_id is None:
                closed = set_position_closed(closed, position.position_id, closed=True)
        decision = preview_arrival(
            Path(repository_root),
            closed,
            template.layout,
            anonymous_vehicle_id="新车N",
            entrance_node_id="entry-main",
            decision_time_s=max(decision_time_s, closed.sim_time_s),
            has_reservation=False,
            expected_departure_time_s=None,
        )
    else:
        raise ValueError("unsupported story scenario")
    return template, decision


def _load_catalog_or_stop(repository_root: Path) -> DemoCatalog:
    try:
        return _catalog(str(repository_root))
    except (ImportRejectedError, OSError, TypeError, ValueError):
        st.error(
            "内置演示数据未通过只读校验，页面已失败关闭。"
            "请运行 D1 校验探针并修复 synthetic fixture。"
        )
        st.stop()
    raise AssertionError("st.stop() must interrupt execution")


def _load_evidence_or_stop(repository_root: Path) -> ComparisonEvidenceView:
    try:
        return _comparison_evidence(str(repository_root))
    except (ComparisonEvidenceError, OSError, TypeError, ValueError):
        st.error("D4 保存证据未通过完整性或公平配对校验，页面已失败关闭。")
        st.stop()
    raise AssertionError("st.stop() must interrupt execution")


def render_sidebar() -> None:
    st.sidebar.title("智能停车优化与调度")
    st.sidebar.caption("完整项目演示系统")
    st.sidebar.badge("SYNTHETIC", color="blue", icon=":material/science:")
    st.sidebar.badge("可解释在线规则", color="green", icon=":material/route:")
    st.sidebar.divider()
    st.sidebar.caption("固定回放可复现｜交互沙盒仅在当前会话运行")
    st.sidebar.caption("不读取 PII｜不覆盖原始文件｜不连接真实控制系统")


def _render_evidence_badges(state: ScreenshotState, catalog: DemoCatalog) -> None:
    bundle = catalog.for_state(state)
    spec = SCREENSHOT_STATE_SPECS[state]
    left, middle, right = st.columns(3)
    with left:
        st.badge(
            bundle.source_kind.upper(),
            color="blue" if bundle.source_kind == "synthetic" else "green",
            icon=":material/dataset:",
        )
        st.caption("数据来源｜非真实采集")
    with middle:
        st.badge(spec.algorithm_status, color="orange", icon=":material/memory:")
        st.caption(f"算法：{bundle.algorithm_id} {bundle.algorithm_version}")
    with right:
        evidence_color: Literal["red", "gray"] = (
            "red" if state is ScreenshotState.INSUFFICIENT_EVIDENCE else "gray"
        )
        st.badge(spec.evidence_status, color=evidence_color, icon=":material/experiment:")
        st.caption("边界：仅用于功能与视觉核验")


def render_overview_page(repository_root: Path) -> None:
    st.title("智能停车优化与调度系统")
    st.caption("面向普通车位与纵深车位的动态分配、阻挡处理和移位调度演示")
    catalog = _load_catalog_or_stop(repository_root)
    bundle = catalog.mixed_depth
    source, method, evidence = st.columns(3)
    with source:
        st.badge("SYNTHETIC｜合成演示", color="blue", icon=":material/science:")
        st.caption("当前演示不代表真实停车场采集数据")
    with method:
        st.badge("在线规则｜当前主线", color="green", icon=":material/route:")
        st.caption("只使用决策时刻已经可见的信息")
    with evidence:
        st.badge("正式对照｜尚未完成", color="orange", icon=":material/experiment:")
        st.caption("当前不形成算法性能优越性结论")

    st.subheader("算法框架")
    framework = (
        ("① 数据与布局校验", "拒绝缺字段、不可达、隐私或不一致输入"),
        ("② 路网成本计算", "预先计算入口、车位、缓冲位与出口的距离和时间"),
        ("③ 当前状态快照", "只读取当前车辆、车位、资源和合法预约信息"),
        ("④ 在线筛选与分配", "先保证可行，再按阻挡、容量、距离和纵深排序"),
        ("⑤ 阻挡与缓冲移位", "离场受阻时显式安排移出、离场和恢复顺序"),
        ("⑥ 失败关闭与降级", "无解、超时或资源不足时等待、拒绝或请求人工"),
        ("⑦ 指标与证据", "分别记录服务、利用、移位、距离和延误"),
    )
    for start in (0, 4):
        columns = st.columns(4)
        for column, (title, note) in zip(
            columns,
            framework[start : start + 4],
            strict=False,
        ):
            with column:
                with st.container(border=True):
                    st.markdown(f"**{title}**")
                    st.caption(note)

    st.subheader("当前已经验证的设计优势")
    advantages = st.columns(4)
    advantages[0].success("**可解释**\n\n每个车位都有筛选和排序依据。")
    advantages[1].success("**可复现**\n\n相同快照得到相同决定。")
    advantages[2].success("**约束一致**\n\n分配、移位和降级共用校验语义。")
    advantages[3].success("**安全降级**\n\n失败不会被伪装成自动成功。")

    st.subheader("系统规模与边界")
    first, second, third, fourth = st.columns(4)
    first.metric("正常位置", len(bundle.layout.slots), border=True)
    second.metric("专用缓冲位", len(bundle.layout.buffer_slots), border=True)
    third.metric("通道资源区", len(bundle.layout.channel_zones), border=True)
    fourth.metric("默认在线算法", "online-rule-v1", border=True)
    st.info("滚动候选优化保留为待验证扩展，当前默认关闭，不作为本轮演示的核心优势。")
    st.warning(
        "正式随机停放、就近停放及其他对照实验尚未完成。"
        "当前展示用于说明算法流程与系统能力，不构成性能优越性或真实场地效果结论。"
    )


def _initial_state_from_query() -> ScreenshotState:
    raw = st.query_params.get("state", ScreenshotState.MIXED_BLOCKED.value)
    if not isinstance(raw, str):
        return ScreenshotState.MIXED_BLOCKED
    try:
        return parse_screenshot_state(raw)
    except ValueError:
        st.warning("未知规范状态已拒绝，回退到“混合纵深｜阻挡成立”。")
        return ScreenshotState.MIXED_BLOCKED


def render_layout_page(repository_root: Path) -> None:
    st.title("停车场与路网")
    st.caption("坐标单位：米｜depth=1 靠近通道｜展示车位结构、缓冲位和管理层通道路网")
    catalog = _load_catalog_or_stop(repository_root)
    initial_state = _initial_state_from_query()
    states = list(ScreenshotState)
    state = st.selectbox(
        "规范截图状态",
        options=states,
        index=states.index(initial_state),
        format_func=lambda item: SCREENSHOT_STATE_SPECS[item].label,
        key="d2_screenshot_state",
    )
    st.query_params["state"] = state.value
    _render_evidence_badges(state, catalog)

    bundle = catalog.for_state(state)
    view = build_static_view(bundle.layout, state)
    status_legend = "　".join(
        f"{spec.glyph} {spec.label}" for spec in POSITION_STATUS_SPECS.values()
    )
    st.caption(f"状态图例: {status_legend}")
    st.plotly_chart(
        build_layout_figure(view),
        width="stretch",
        theme=None,
        config={
            "displaylogo": False,
            "responsive": True,
            "scrollZoom": True,
            "modeBarButtonsToRemove": ["lasso2d", "select2d"],
        },
        key=f"d2-layout-{state.value}",
    )
    if view.warnings:
        st.warning(" ".join(view.warnings))
    with st.expander("状态图例与读图规则", expanded=False):
        for status, spec in POSITION_STATUS_SPECS.items():
            count = dict(view.status_counts)[status]
            st.markdown(f"{spec.glyph} **{spec.label}**｜当前 {count} 个｜编码 `{spec.symbol}`")
        st.caption("缓冲位使用更大标记；颜色、符号、文字三重编码，不只依赖颜色。")


def _render_locked_page(title: str, milestone: str, scope: str) -> None:
    st.title(title)
    st.warning(f"{milestone} 尚未获批，本页在 D2 中仅保留导航位置。")
    st.caption(scope)
    st.info("没有运行仿真、生成动画、重算指标或读取真实数据。")


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
        selected_types = tuple(
            st.multiselect(
                "事件类型过滤（仅影响步进/播放，不删除事件）",
                timeline.event_types,
                key="d3_event_types",
            )
        )
    with second:
        transaction_options = ("全部事务", *timeline.transaction_ids)
        selected_transaction = st.selectbox(
            "事务过滤",
            transaction_options,
            key="d3_transaction_filter",
        )
    transaction_id = None if selected_transaction == "全部事务" else selected_transaction
    current = int(st.session_state["d3_sequence"])
    matching = navigator.matching_sequences(
        event_types=selected_types,
        transaction_id=transaction_id,
    )
    if not matching:
        st.warning("当前过滤组合没有事件；位置保持不变。")

    play_col, previous_col, next_col, speed_col, position_col = st.columns((1, 1, 1, 1.2, 3.8))
    playing = bool(st.session_state.get("d3_playing", False))
    if play_col.button(
        "暂停" if playing else "播放",
        icon=":material/pause:" if playing else ":material/play_arrow:",
        width="stretch",
    ):
        st.session_state["d3_playing"] = not playing
        playing = not playing
    if previous_col.button("上一步", icon=":material/skip_previous:", width="stretch"):
        _set_replay_sequence(
            navigator.step(
                current,
                -1,
                event_types=selected_types,
                transaction_id=transaction_id,
            )
        )
    if next_col.button("下一步", icon=":material/skip_next:", width="stretch"):
        _set_replay_sequence(
            navigator.step(
                current,
                1,
                event_types=selected_types,
                transaction_id=transaction_id,
            )
        )
    speed = float(
        speed_col.selectbox(
            "播放速度",
            (0.5, 1.0, 2.0, 5.0, 10.0),
            index=1,
            format_func=lambda value: f"{value:g}×",
            key="d3_playback_speed",
        )
    )
    slider_sequence = int(st.session_state["d3_sequence"])
    if st.session_state.get("d3_sequence_slider") != slider_sequence:
        st.session_state["d3_sequence_slider"] = slider_sequence
    position_col.slider(
        "事件序号",
        navigator.index.first_sequence_no,
        navigator.index.last_sequence_no,
        key="d3_sequence_slider",
        on_change=_sync_replay_sequence_from_slider,
    )
    st.query_params["seq"] = str(st.session_state["d3_sequence"])

    mode = st.radio(
        "定位方式",
        ("事件序号", "仿真秒", "移位事务"),
        horizontal=True,
        key="d3_position_mode",
    )
    if mode == "事件序号":
        jump = st.number_input(
            "跳转到序号",
            min_value=navigator.index.first_sequence_no,
            max_value=navigator.index.last_sequence_no,
            value=int(st.session_state["d3_sequence"]),
            step=1,
            key="d3_jump_sequence",
        )
        if st.button("执行序号跳转", icon=":material/arrow_forward:"):
            _set_replay_sequence(int(jump))
    elif mode == "仿真秒":
        second_value = st.number_input(
            "跳转到仿真秒（取不晚于该时刻的最后确认事件）",
            min_value=0,
            value=navigator.frame(current).sim_time_s,
            step=1,
            key="d3_jump_time",
        )
        if st.button("执行时间跳转", icon=":material/schedule:"):
            _set_replay_sequence(navigator.at_or_before_time(int(second_value)))
    else:
        if not timeline.transaction_ids:
            st.info("该日志没有移位事务。")
        else:
            transaction_jump = st.selectbox(
                "选择事务",
                timeline.transaction_ids,
                key="d3_transaction_jump",
            )
            beginning, ending = navigator.transaction_bounds(transaction_jump)
            left, right = st.columns(2)
            if left.button("跳到事务开始", width="stretch"):
                _set_replay_sequence(beginning)
            if right.button("跳到事务结束", width="stretch"):
                _set_replay_sequence(ending)

    if playing:
        next_sequence = navigator.step(
            int(st.session_state["d3_sequence"]),
            1,
            event_types=selected_types,
            transaction_id=transaction_id,
        )
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
        st.dataframe(
            [
                {"通道区": zone, "占用": used, "容量": capacity}
                for zone, used, capacity in frame.channel_zone_usage
            ],
            width="stretch",
            hide_index=True,
        )


def _render_replay_details(workspace: _ReplayWorkspace, sequence_no: int) -> None:
    navigator = workspace.navigator
    frame = navigator.frame(sequence_no)
    event = navigator.event_at(sequence_no)
    st.subheader("事件、车辆与位置检查")
    event_tab, vehicle_tab, position_tab, transaction_tab = st.tabs(
        ("事件详情", "车辆详情", "位置详情", "事务时线")
    )
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
            vehicle_id = st.selectbox(
                "匿名车辆",
                tuple(item.anonymous_vehicle_id for item in frame.vehicles),
                key="d3_vehicle_detail",
            )
            vehicle = next(
                item for item in frame.vehicles if item.anonymous_vehicle_id == vehicle_id
            )
            st.dataframe(
                [
                    {
                        "匿名车辆": vehicle.anonymous_vehicle_id,
                        "位置状态": vehicle.location_kind,
                        "位置": vehicle.position_id or "—",
                        "到达服务": vehicle.arrival_status,
                        "离场服务": vehicle.departure_status,
                        "人工状态": vehicle.manual_status,
                    }
                ],
                width="stretch",
                hide_index=True,
            )
    with position_tab:
        position_id = st.selectbox(
            "位置",
            tuple(item.position_id for item in frame.positions),
            key="d3_position_detail",
        )
        position = next(item for item in frame.positions if item.position_id == position_id)
        st.dataframe(
            [
                {
                    "位置": position.position_id,
                    "类型": position.position_kind,
                    "纵深组": position.stack_group_id or "—",
                    "depth": position.depth or "—",
                    "匿名车辆": position.occupant_vehicle_id or "—",
                    "物理可用": position.physically_available,
                    "可分配": position.assignable,
                    "阻挡车辆": "、".join(position.blocker_vehicle_ids) or "—",
                }
            ],
            width="stretch",
            hide_index=True,
        )
    with transaction_tab:
        transaction_id = (
            event.transaction_id
            if event is not None and event.transaction_id is not None
            else next(
                (
                    item.transaction_id
                    for item in reversed(navigator.timeline.events[:sequence_no])
                    if item.transaction_id is not None
                ),
                None,
            )
        )
        if transaction_id is None:
            st.info("当前前缀尚未关联移位事务。")
        else:
            rows = [
                {
                    "序号": item.sequence_no,
                    "仿真秒": item.sim_time_s,
                    "事件": item.event_type,
                    "动作": "—" if item.action is None else item.action.action_type,
                    "动作状态": "—" if item.action is None else item.action.status,
                    "事务阶段": item.transaction_status or "—",
                }
                for item in navigator.timeline.events
                if item.transaction_id == transaction_id
            ]
            st.caption(f"事务 `{transaction_id}`｜按保存事件序号离散回放")
            st.dataframe(rows, width="stretch", hide_index=True)


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
        config={
            "displaylogo": False,
            "responsive": True,
            "scrollZoom": True,
            "modeBarButtonsToRemove": ["lasso2d", "select2d"],
        },
        key=f"d3-replay-{sequence_no}",
    )
    if view.warnings:
        st.error("状态警告：" + "、".join(view.warnings))
    _render_resource_state(frame)
    _render_replay_details(workspace, sequence_no)
    info = navigator.cache.info
    st.caption(
        f"受控帧缓存 {info.size}/{info.max_entries}｜命中 {info.hits}｜"
        f"未命中 {info.misses}｜失效 {info.invalidations}"
    )


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
            "动作": {
                "PARK": "驶入车位",
                "RELOCATE_TO_BUFFER": "移至缓冲位",
                "DEPART": "驶向出口",
                "RESTORE_FROM_BUFFER": "从缓冲位恢复",
            }.get(action.action_type.value, action.action_type.value),
            "起点": action.origin_position_id or "入口",
            "终点": action.destination_position_id or action.destination_exit_id or "—",
            "距离": f"{action.distance_m:.1f} m",
            "预计用时": f"{action.modeled_duration_s} s",
        }
        for index, action in enumerate(decision.result.recommended_actions, start=1)
    ]


def _render_arrival_explanation(decision: SandboxDecision) -> None:
    chosen = next(
        (item for item in decision.candidates if item.position_id == decision.selected_position_id),
        None,
    )
    nearest = next(
        (
            item
            for item in decision.candidates
            if item.position_id == decision.nearest_feasible_position_id
        ),
        None,
    )
    selected_col, nearest_col, meaning_col = st.columns(3)
    selected_col.metric("在线规则选择", decision.selected_position_id or "无", border=True)
    nearest_col.metric(
        "最近可行车位",
        decision.nearest_feasible_position_id or "无",
        border=True,
    )
    if chosen is not None and nearest is not None:
        meaning_col.metric(
            "本次选择是否仅看距离",
            "否" if chosen.position_id != nearest.position_id else "本例相同",
            border=True,
        )
        if chosen.position_id != nearest.position_id:
            st.info(
                f"本次最近可行位 `{nearest.position_id}` 距离 "
                f"{nearest.distance_m:.1f} m，但会新增 "
                f"{nearest.incremental_blocked_vehicle_count} 个阻挡；"
                f"规则选择 `{chosen.position_id}`，距离 {chosen.distance_m:.1f} m，"
                f"新增阻挡为 {chosen.incremental_blocked_vehicle_count}。"
                "这只解释当前单次决定，不是正式算法对照实验。"
            )
    top_rows = [
        row for row in candidate_rows(decision, feasible_limit=5) if row["结果"] != "已排除"
    ]
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
    if play_col.button(
        "暂停" if playing else "开始演示",
        icon=":material/pause:" if playing else ":material/play_arrow:",
        width="stretch",
        key="story_play_toggle",
    ):
        st.session_state["story_playing"] = not playing
        st.rerun()
    if previous_col.button(
        "上一步",
        icon=":material/skip_previous:",
        width="stretch",
        key="story_previous",
    ):
        st.session_state["story_step"] = max(step - 1, 0)
        st.session_state["story_progress"] = 0.0
        st.session_state["story_playing"] = False
        st.rerun()
    if next_col.button(
        "下一步",
        icon=":material/skip_next:",
        width="stretch",
        key="story_next",
    ):
        st.session_state["story_step"] = min(step + 1, last_step)
        st.session_state["story_progress"] = 0.0
        st.session_state["story_playing"] = False
        st.rerun()
    if replay_col.button(
        "重新播放",
        icon=":material/replay:",
        width="stretch",
        key="story_replay",
    ):
        st.session_state["story_step"] = 0
        st.session_state["story_progress"] = 0.0
        st.session_state["story_playing"] = True
        st.rerun()
    speed = float(
        speed_col.selectbox(
            "演示速度",
            (0.5, 1.0, 2.0),
            index=1,
            format_func=lambda value: f"{value:g}×",
            key="story_speed",
        )
    )
    st.progress(
        min((step + progress) / max(len(decision.story_steps), 1), 1.0),
        text=f"第 {step + 1}/{len(decision.story_steps)} 步",
    )
    return step, speed


def render_replay_page(repository_root: Path) -> None:
    """Render three plain-language algorithm stories plus the saved audit."""

    st.title("算法过程回放")
    st.caption("看见车辆、候选筛选、选择理由与管理层路径；默认使用可复现合成场景")
    st.badge("SYNTHETIC｜教学场景", color="blue", icon=":material/science:")
    st.badge("真实在线规则", color="green", icon=":material/route:")
    scenario = st.selectbox(
        "选择一个完整故事",
        ("新车入场分配", "纵深阻挡移位", "无可行车位与等待"),
        key="story_scenario",
    )
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
    figure, summary = build_sandbox_figure(
        template.layout,
        decision.input_state,
        decision=decision,
        story_step=step,
        route_progress=float(st.session_state.get("story_progress", 0.0)),
    )
    st.plotly_chart(
        figure,
        width="stretch",
        theme=None,
        config={
            "displaylogo": False,
            "responsive": True,
            "scrollZoom": True,
            "modeBarButtonsToRemove": ["lasso2d", "select2d"],
        },
        key=f"story-figure-{scenario}-{step}",
    )
    occupied, feasible, excluded, primary = st.columns(4)
    occupied.metric("已停车车辆", summary.occupied_count, border=True)
    feasible.metric("可行候选", summary.feasible_candidate_count, border=True)
    excluded.metric("排除位置", summary.excluded_candidate_count, border=True)
    primary.metric(
        "当前主决定",
        _primary_decision_label(decision.result.primary_decision),
        border=True,
    )

    if decision.decision_kind == "ARRIVAL" and decision.candidates:
        _render_arrival_explanation(decision)
    elif decision.result.recommended_actions:
        st.markdown("**移位事务按以下顺序整体执行**")
        st.dataframe(_action_rows(decision), width="stretch", hide_index=True)
        st.caption("缓冲位不是普通停车位，只在移位事务中临时占用；事务结束后恢复。")
    else:
        st.warning(
            "没有可行停车动作。系统保留等待、拒绝或人工处理状态，"
            "不会静默把车辆放进不可达、已占用或关闭的车位。"
        )
        if decision.result.explanation_codes:
            st.caption("机器解释码：" + "、".join(decision.result.explanation_codes))

    st.warning(
        "黄色车辆与蓝色路线是管理层面的路径演示，不是自动驾驶轨迹；"
        "本页不控制真实车辆，也不证明算法优于随机或就近停放。"
    )
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
    vehicle_col.metric(
        "匿名车辆",
        decision.result.target_anonymous_vehicle_id,
        border=True,
    )
    destination_col.metric(
        "推荐车位",
        decision.selected_position_id or "无",
        border=True,
    )
    if decision.decision_kind == "ARRIVAL" and decision.candidates:
        _render_arrival_explanation(decision)
    elif decision.result.recommended_actions:
        st.dataframe(_action_rows(decision), width="stretch", hide_index=True)
    else:
        st.warning("本次没有可确认的自动动作，状态将保持等待、拒绝或人工处理。")
        if decision.result.explanation_codes:
            st.caption("机器解释码：" + "、".join(decision.result.explanation_codes))

    confirm_col, reset_col = st.columns(2)
    if confirm_col.button(
        "确认并更新当前场景",
        type="primary",
        width="stretch",
        disabled=primary is not PrimaryDecision.RECOMMEND_ACTIONS,
        key="sandbox_confirm_decision",
    ):
        try:
            st.session_state["sandbox_state"] = confirm_sandbox_decision(decision)
            st.session_state["sandbox_decision"] = None
            st.success("决定已在当前浏览器会话中确认；可以继续提交下一辆车。")
            st.rerun()
        except ValueError:
            st.error("当前结果不能确认，场景状态未改变。")
    if reset_col.button(
        "放弃本次预览",
        width="stretch",
        key="sandbox_discard_decision",
    ):
        st.session_state["sandbox_decision"] = None
        st.rerun()

    downloads = decision_downloads(decision, template.layout)
    st.markdown("**下载本次演示证据**")
    download_columns = st.columns(4)
    download_specs = (
        ("场景 JSON", "scenario.json", "application/json"),
        ("决策 JSON", "decision-result.json", "application/json"),
        ("候选 CSV", "candidate-comparison.csv", "text/csv"),
        ("中文 HTML 摘要", "decision-summary.html", "text/html"),
    )
    for column, (label, filename, mime) in zip(
        download_columns,
        download_specs,
        strict=True,
    ):
        column.download_button(
            label,
            downloads[filename],
            file_name=filename,
            mime=mime,
            width="stretch",
            key=f"sandbox-download-{filename}",
        )
    st.caption("HTML 摘要可在浏览器中打开并使用“打印 → 另存为 PDF”。")


def render_sandbox_page(repository_root: Path) -> None:
    """Render a bounded, session-only synthetic online-rule sandbox."""

    st.title("交互式车位分配")
    st.caption("自己提交匿名车辆的入场或离场请求，查看在线规则如何筛选和分配")
    st.badge("SYNTHETIC｜仅当前会话", color="blue", icon=":material/science:")
    st.badge("不写入正式输出", color="gray", icon=":material/memory:")
    st.warning(
        "请勿输入车牌、姓名、手机号等个人信息。这里运行的是合成内存沙盒；"
        "刷新或重置后可恢复模板，不会向真实停车场发送控制指令。"
    )
    template_id = st.radio(
        "场景规模",
        ("compact", "full"),
        format_func=lambda value: (
            "紧凑拥挤场景｜24 个正常位" if value == "compact" else "完整混合布局｜99 个正常位"
        ),
        horizontal=True,
        key="sandbox_template_choice",
    )
    template = _sandbox_template(template_id)
    state = _sandbox_state_for(template)
    header, reset = st.columns((4, 1))
    header.info(template.note)
    if reset.button(
        "重置模板",
        icon=":material/restart_alt:",
        width="stretch",
        key="sandbox_reset_template",
    ):
        st.session_state["sandbox_state"] = template.initial_state
        st.session_state["sandbox_decision"] = None
        st.rerun()

    occupied_count = sum(item.occupant_vehicle_id is not None for item in state.positions)
    closed_count = sum(
        not item.physically_available or item.planned_closure for item in state.positions
    )
    first, second, third, fourth = st.columns(4)
    first.metric("场景时间", f"{state.sim_time_s} s", border=True)
    second.metric("已停车车辆", occupied_count, border=True)
    third.metric("关闭位置", closed_count, border=True)
    fourth.metric("状态版本", state.sequence_no, border=True)

    arrival_tab, departure_tab, edit_tab = st.tabs(("新车入场", "车辆离场", "场景编辑"))
    with arrival_tab:
        with st.form("sandbox_arrival_form"):
            vehicle_col, entrance_col, time_col = st.columns(3)
            vehicle_id = vehicle_col.text_input(
                "匿名车辆标签",
                value=f"新车{state.sequence_no + 1}",
                max_chars=32,
                help="只使用 A、B、C 或“新车N”等匿名标签。",
            )
            entrances = tuple(
                item.road_node_id
                for item in template.layout.road_nodes
                if item.node_kind == "entrance"
            )
            entrance_id = entrance_col.selectbox("入口", entrances)
            decision_time = int(
                time_col.number_input(
                    "到达时间（秒）",
                    min_value=int(state.sim_time_s),
                    value=int(state.sim_time_s + 10),
                    step=1,
                )
            )
            reservation_col, known_departure_col = st.columns(2)
            has_reservation = reservation_col.checkbox("有合法预约")
            known_departure = known_departure_col.checkbox("提供预计离场时间")
            expected_departure = None
            if known_departure:
                expected_departure = int(
                    st.number_input(
                        "预计离场时间（秒）",
                        min_value=decision_time + 1,
                        value=decision_time + 600,
                        step=1,
                    )
                )
            arrival_preview = st.form_submit_button(
                "运行在线规则并预览",
                type="primary",
                width="stretch",
            )
        if arrival_preview:
            try:
                st.session_state["sandbox_decision"] = preview_arrival(
                    repository_root,
                    state,
                    template.layout,
                    anonymous_vehicle_id=vehicle_id,
                    entrance_node_id=entrance_id,
                    decision_time_s=decision_time,
                    has_reservation=has_reservation,
                    expected_departure_time_s=expected_departure,
                )
            except (TypeError, ValueError, RuntimeError):
                st.error("入场输入未通过校验或规则无法安全运行；场景状态没有改变。")
    with departure_tab:
        parked = tuple(
            item.anonymous_vehicle_id
            for item in state.vehicles
            if item.location_state.kind is LocationKind.AT_POSITION
        )
        if not parked:
            st.info("当前没有可提交离场请求的车辆。")
        else:
            with st.form("sandbox_departure_form"):
                departure_vehicle = st.selectbox("选择已停车车辆", parked)
                departure_time = int(
                    st.number_input(
                        "离场请求时间（秒）",
                        min_value=int(state.sim_time_s),
                        value=int(state.sim_time_s + 10),
                        step=1,
                        key="sandbox_departure_time",
                    )
                )
                departure_preview = st.form_submit_button(
                    "运行在线规则并预览",
                    type="primary",
                    width="stretch",
                )
            if departure_preview:
                try:
                    st.session_state["sandbox_decision"] = preview_departure(
                        repository_root,
                        state,
                        template.layout,
                        anonymous_vehicle_id=departure_vehicle,
                        decision_time_s=departure_time,
                    )
                except (TypeError, ValueError, RuntimeError):
                    st.error("离场输入未通过校验或规则无法安全运行；场景状态没有改变。")
    with edit_tab:
        st.caption("编辑范围受限：只能关闭/开放空闲普通位，或移除一辆已停车的合成车辆。")
        normal_positions = tuple(
            item
            for item in state.positions
            if item.position_id in {slot.position_id for slot in template.layout.slots}
        )
        position_id = st.selectbox(
            "普通车位",
            tuple(item.position_id for item in normal_positions),
            key="sandbox_edit_position",
        )
        position_state = next(item for item in normal_positions if item.position_id == position_id)
        close_col, open_col = st.columns(2)
        if close_col.button(
            "关闭所选空位",
            width="stretch",
            disabled=position_state.occupant_vehicle_id is not None,
            key="sandbox_close_position",
        ):
            try:
                st.session_state["sandbox_state"] = set_position_closed(
                    state,
                    position_id,
                    closed=True,
                )
                st.session_state["sandbox_decision"] = None
                st.rerun()
            except ValueError:
                st.error("该位置不能关闭，场景状态没有改变。")
        if open_col.button(
            "重新开放所选位",
            width="stretch",
            key="sandbox_open_position",
        ):
            try:
                st.session_state["sandbox_state"] = set_position_closed(
                    state,
                    position_id,
                    closed=False,
                )
                st.session_state["sandbox_decision"] = None
                st.rerun()
            except ValueError:
                st.error("该位置不能开放，场景状态没有改变。")
        if parked:
            remove_vehicle = st.selectbox(
                "移除一辆合成车辆",
                parked,
                key="sandbox_remove_vehicle",
            )
            if st.button(
                "移除并释放车位",
                width="stretch",
                key="sandbox_remove_vehicle_button",
            ):
                try:
                    st.session_state["sandbox_state"] = remove_parked_vehicle(
                        state,
                        remove_vehicle,
                    )
                    st.session_state["sandbox_decision"] = None
                    st.rerun()
                except ValueError:
                    st.error("该车辆不能移除，场景状态没有改变。")

    decision = st.session_state.get("sandbox_decision")
    display_state = state if decision is None else decision.input_state
    figure, summary = build_sandbox_figure(
        template.layout,
        display_state,
        decision=decision,
        story_step=999,
        route_progress=1.0,
    )
    st.plotly_chart(
        figure,
        width="stretch",
        theme=None,
        config={
            "displaylogo": False,
            "responsive": True,
            "scrollZoom": True,
            "modeBarButtonsToRemove": ["lasso2d", "select2d"],
        },
        key=f"sandbox-figure-{template.template_id}-{state.sequence_no}",
    )
    st.caption(
        f"图中已占用 {summary.occupied_count}｜空闲 {summary.free_count}｜"
        f"关闭 {summary.closed_count}；车辆标签均为合成匿名标签。"
    )
    if isinstance(decision, SandboxDecision):
        _render_sandbox_decision(repository_root, template, decision)


def _format_metric_value(value: float, unit: str) -> str:
    if unit == "ratio":
        return f"{value * 100:.2f}%"
    if unit == "count":
        return f"{value:,.0f}"
    if unit == "meter":
        return f"{value:,.2f} m"
    if unit == "second":
        return f"{value:,.2f} s"
    if unit == "per_hour":
        return f"{value:,.3f} 辆/小时"
    return f"{value:,.4f}"


def _format_difference(value: float, unit: str) -> str:
    if unit == "ratio":
        return f"{value * 100:+.3f} 百分点"
    return f"{value:+,.3f} {UNIT_LABELS[unit]}"


def _short_hash(value: str) -> str:
    return f"{value[:12]}…{value[-8:]}"


def _render_d4_boundary(evidence: ComparisonEvidenceView) -> None:
    st.error(
        f"研究门：{evidence.research_gate_status}｜核心配对 "
        f"{evidence.formal_pair_count}/{evidence.required_formal_pair_count}｜"
        f"正式 seed {evidence.formal_seed_count}/{evidence.required_formal_seed_count}"
    )
    first, second, third = st.columns(3)
    with first:
        st.badge("SYNTHETIC｜非实测", color="blue", icon=":material/science:")
        st.caption("SYNTHETIC：只说明仿真产物，不代表真实停车场效果。")
    with second:
        st.badge("ROLLING 默认关闭", color="gray", icon=":material/toggle_off:")
        st.caption("ROLLING 默认关闭：滚动候选仍是未证实扩展，不是默认策略。")
    with third:
        st.badge("10 s ≠ 在线 SLA", color="orange", icon=":material/timer:")
        st.caption("10 s 仅为离线质量上界，不是在线 SLA；在线目标/硬截止另行冻结。")
    st.caption(
        "信息条件：online 仅使用 ObservedSnapshot；rolling 使用相同可见信息做有界窗口候选；"
        "oracle 是离线全信息基准，三者不可混写为同一信息条件。"
    )


def _render_decision_audit(bundle: ValidatedDemoBundle) -> None:
    decision_id = st.selectbox(
        "保存决策",
        bundle.decision_ids,
        key="d4_decision_id",
    )
    audit = decision_audit(bundle, decision_id)
    st.caption(
        f"决策 `{audit.decision_id}`｜目标请求 `{audit.target_request_id}`｜"
        f"匿名车辆 `{audit.target_anonymous_vehicle_id}`"
    )
    primary, solver, validation, incumbent = st.columns(4)
    primary.metric(
        "即时主决定",
        {
            "WAIT": "等待",
            "REJECT": "拒绝",
            "RECOMMEND_ACTIONS": "推荐动作",
            "REQUEST_MANUAL_INTERVENTION": "请求人工",
        }.get(audit.primary_decision, audit.primary_decision),
        border=True,
    )
    solver.metric(
        "原求解状态",
        {
            "TIME_LIMIT_NO_FEASIBLE": "限时无解",
            "TIME_LIMIT_FEASIBLE": "限时可行",
            "OPTIMAL": "已证最优",
            "NOT_RUN": "未运行求解器",
        }.get(audit.solver_status, audit.solver_status),
        border=True,
    )
    validation.metric(
        "结果校验",
        {"VALID": "有效", "INVALID": "无效"}.get(audit.validation_status, audit.validation_status),
        border=True,
    )
    incumbent.metric(
        "incumbent 证据",
        {
            "NO_FEASIBLE_INCUMBENT": "无可行值",
            "SAVED_VALIDATED_INCUMBENT": "已保存并校验",
            "NOT_APPLICABLE_OPTIMAL": "最优解，无需区分",
            "NOT_REPORTED_BY_SAVED_RESULT": "保存结果未报告",
        }.get(audit.incumbent_status, audit.incumbent_status),
        border=True,
    )
    st.caption(
        f"机器状态：primary={audit.primary_decision}｜solver={audit.solver_status}｜"
        f"validation={audit.validation_status}｜incumbent={audit.incumbent_status}"
    )

    st.subheader("触发事件与可见信息证据")
    trigger_rows = [
        {"字段": "trigger_event_id", "保存值": audit.trigger_event_id or "未关联"},
        {"字段": "trigger_event_type", "保存值": audit.trigger_event_type or "未关联"},
        {
            "字段": "trigger_sim_time_s",
            "保存值": "未关联"
            if audit.trigger_sim_time_s is None
            else f"{audit.trigger_sim_time_s} s",
        },
        {"字段": "visible_snapshot_sha256", "保存值": audit.visible_snapshot_sha256},
        {"字段": "snapshot_content_status", "保存值": audit.snapshot_content_status},
    ]
    st.dataframe(trigger_rows, width="stretch", hide_index=True)
    st.warning(
        "阶段 C 运行包保存了可见快照 SHA-256，但未持久化完整 ObservedSnapshot 内容。"
        "D4 只展示可核验哈希与触发事件，不重建或推测快照字段。"
    )

    result_tab, timing_tab, evidence_tab = st.tabs(("结果与降级链", "预算与用时", "完整性证据"))
    with result_tab:
        if audit.actions:
            st.dataframe(
                [
                    {
                        "动作": item.action_type,
                        "匿名车辆": item.anonymous_vehicle_id,
                        "起点": item.origin_position_id or "入口/当前状态",
                        "终点": item.destination_position_id or item.destination_exit_id or "—",
                        "距离": f"{item.distance_m:.2f} m",
                        "建模时长": f"{item.modeled_duration_s} s",
                    }
                    for item in audit.actions
                ],
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("该保存结果没有推荐动作；即时主决定本身仍保留。")
        st.caption("解释码：" + ("、".join(audit.explanation_codes) or "无"))
        if audit.used_fallback:
            st.warning(
                f"已记录 fallback：{audit.fallback_original_method} / "
                f"{audit.fallback_original_solver_status} → {audit.fallback_strategy}；"
                f"原因：{audit.fallback_reason}；耗时 {audit.fallback_elapsed_s:.3f} s。"
            )
        else:
            st.success("该保存决策没有 fallback 记录。")
        if audit.candidate_generation:
            st.dataframe(
                [{"候选计数": key, "保存值": value} for key, value in audit.candidate_generation],
                width="stretch",
                hide_index=True,
            )
        if audit.candidate_truncation_reasons:
            st.caption("候选截断原因：" + "、".join(audit.candidate_truncation_reasons))
    with timing_tab:
        st.dataframe(
            [
                {"阶段": "校验与建模", "保存用时（秒）": audit.validation_and_modeling_s},
                {"阶段": "求解", "保存用时（秒）": audit.solver_s},
                {"阶段": "后验校验", "保存用时（秒）": audit.postsolve_validation_s},
                {"阶段": "最小日志预留", "保存用时（秒）": audit.minimum_logging_s},
                {"阶段": "求解器时间上限", "保存用时（秒）": audit.solver_time_limit_s},
                {"阶段": "端到端", "保存用时（秒）": audit.end_to_end_s},
            ],
            width="stretch",
            hide_index=True,
        )
        st.caption("这些是该决策的保存值，不是生产环境实时 SLA 测量。")
    with evidence_tab:
        st.dataframe(
            [
                {"证据": "config_sha256", "SHA-256": audit.config_sha256},
                {"证据": "layout_sha256", "SHA-256": audit.layout_sha256},
                {"证据": "visible_snapshot_sha256", "SHA-256": audit.visible_snapshot_sha256},
                {
                    "证据": "input_model_sha256",
                    "SHA-256": audit.input_model_sha256 or "NOT_APPLICABLE",
                },
            ],
            width="stretch",
            hide_index=True,
        )


def _metric_by_name(evidence: ComparisonEvidenceView, name: str):  # type: ignore[no-untyped-def]
    return next(item for item in evidence.metrics if item.metric_name == name)


def _render_key_metric_card(container, evidence: ComparisonEvidenceView, name: str) -> None:  # type: ignore[no-untyped-def]
    item = _metric_by_name(evidence, name)
    with container:
        st.metric(
            METRIC_LABELS[name],
            _format_metric_value(item.baseline_value, item.unit),
            border=True,
            help="主值为保存的在线规则基线绝对值；下方另列滚动候选，不使用排名箭头。",
        )
        st.caption(
            f"滚动候选：{_format_metric_value(item.candidate_value, item.unit)}｜"
            f"候选减基线：{_format_difference(item.paired_difference, item.unit)}｜"
            f"n={item.sample_n}"
        )


def _render_metric_comparison(evidence: ComparisonEvidenceView) -> None:
    st.subheader("保存指标明细｜开发审计")
    first_row = st.columns(3)
    for container, name in zip(
        first_row,
        (
            "occupancy_rate",
            "normal_space_time_utilization",
            "facility_position_space_time_utilization",
        ),
        strict=True,
    ):
        _render_key_metric_card(container, evidence, name)
    second_row = st.columns(2)
    for container, name in zip(
        second_row,
        ("demand_satisfaction_rate", "throughput_per_hour"),
        strict=True,
    ):
        _render_key_metric_card(container, evidence, name)

    st.plotly_chart(
        build_ratio_comparison_figure(evidence),
        width="stretch",
        theme=None,
        config={
            "displaylogo": False,
            "responsive": True,
            "modeBarButtonsToRemove": ["lasso2d", "select2d"],
        },
        key="d4-ratio-comparison",
    )
    st.caption(
        "图中只绘制绝对比例并使用文字/纹理区分算法；不按优劣排序，不用箭头或颜色暗示研究门通过。"
    )

    st.subheader("完整保存指标")
    st.dataframe(
        [
            {
                "指标": METRIC_LABELS[item.metric_name],
                "机器名": item.metric_name,
                "口径": (
                    "仅完成样本"
                    if item.completed_only
                    else "右删失率"
                    if item.censoring_rate
                    else "标准聚合"
                ),
                "单位": UNIT_LABELS[item.unit],
                "在线基线": _format_metric_value(item.baseline_value, item.unit),
                "滚动候选": _format_metric_value(item.candidate_value, item.unit),
                "候选减基线": _format_difference(item.paired_difference, item.unit),
                "配对 n": item.sample_n,
            }
            for item in evidence.metrics
        ],
        width="stretch",
        hide_index=True,
    )

    st.subheader("失败、回退与右删失｜不得隐藏")
    baseline = evidence.baseline
    candidate = evidence.candidate
    st.warning(
        f"滚动候选保存了 {candidate.fallback_count} 次回退，回退率 "
        f"{candidate.fallback_rate * 100:.2f}%；在线基线为 "
        f"{baseline.fallback_count} 次 / {baseline.fallback_rate * 100:.2f}%。"
    )
    st.dataframe(
        [
            {
                "算法": "在线规则基线",
                "pending@horizon": baseline.pending_request_count_at_horizon,
                "fallback": baseline.fallback_count,
                "fallback rate": f"{baseline.fallback_rate * 100:.2f}%",
                "硬截止违反": baseline.hard_deadline_violation_count,
                "状态不变量违反": baseline.state_invariant_violation_count,
            },
            {
                "算法": "滚动候选",
                "pending@horizon": candidate.pending_request_count_at_horizon,
                "fallback": candidate.fallback_count,
                "fallback rate": f"{candidate.fallback_rate * 100:.2f}%",
                "硬截止违反": candidate.hard_deadline_violation_count,
                "状态不变量违反": candidate.state_invariant_violation_count,
            },
        ],
        width="stretch",
        hide_index=True,
    )

    with st.expander("RunManifest、配对键与产物哈希", expanded=False):
        st.dataframe(
            [
                {
                    "角色": "baseline",
                    "run_id": baseline.run_id,
                    "algorithm": f"{baseline.algorithm_id} {baseline.algorithm_version}",
                    "Git": baseline.git_commit,
                    "input SHA-256": baseline.input_data_sha256,
                    "config SHA-256": baseline.config_sha256,
                    "状态": baseline.run_status,
                },
                {
                    "角色": "candidate",
                    "run_id": candidate.run_id,
                    "algorithm": f"{candidate.algorithm_id} {candidate.algorithm_version}",
                    "Git": candidate.git_commit,
                    "input SHA-256": candidate.input_data_sha256,
                    "config SHA-256": candidate.config_sha256,
                    "状态": candidate.run_status,
                },
            ],
            width="stretch",
            hide_index=True,
        )
        st.caption(
            "公平配对键："
            + "｜".join(f"{key}={value}" for key, value in evidence.pair_key)
            + f"｜状态={evidence.pair_key_status}"
        )
        st.dataframe(
            [
                {"产物": artifact, "SHA-256": digest}
                for artifact, digest in evidence.artifact_sha256
            ],
            width="stretch",
            hide_index=True,
        )


_RESEARCH_METRICS = (
    (
        "demand_satisfaction_rate",
        "需求满足率",
        "成功获得服务的到达需求占全部到达需求的比例。",
    ),
    (
        "facility_position_space_time_utilization",
        "车位时空利用率",
        "观察期内，全部可用位置被有效占用的“位置×时间”比例。",
    ),
    (
        "throughput_per_hour",
        "单位时间吞吐量",
        "每小时完成服务的车辆数，反映停车场处理需求的速度。",
    ),
    (
        "relocation_count",
        "移位次数",
        "为让被阻挡车辆离场而执行的临时移车次数。",
    ),
    (
        "relocation_distance_m",
        "移位距离",
        "所有移位车辆在管理层路径上的累计移动距离。",
    ),
    (
        "departure_delay_s_completed_only_mean",
        "出库延误",
        "已完成离场车辆从提出请求到实际离场的平均额外时间。",
    ),
)


def _render_research_conclusion(evidence: ComparisonEvidenceView) -> None:
    st.subheader("这项研究目前说明了什么")
    verified, observed, pending = st.columns(3)
    verified.success(
        "**已经验证**\n\n"
        "在线规则只使用当时可见信息；候选可行性、纵深阻挡、缓冲移位、"
        "失败关闭和固定种子复现均有代码与测试。"
    )
    observed.info(
        "**合成案例可以观察**\n\n"
        "系统能在拥挤布局中逐层筛选车位，并在最近车位可能增加阻挡时选择"
        "另一可行位置；这只是单案例机制说明。"
    )
    pending.warning(
        "**仍待正式验证**\n\n"
        "与可行随机停放、最近可行停放的公平实验，以及真实停车场校准尚未完成；"
        "因此不能声称当前算法性能更优。"
    )

    st.subheader("六个默认研究指标")
    for start in (0, 3):
        columns = st.columns(3)
        for column, (machine_name, label, explanation) in zip(
            columns,
            _RESEARCH_METRICS[start : start + 3],
            strict=True,
        ):
            item = _metric_by_name(evidence, machine_name)
            with column:
                st.metric(
                    label,
                    _format_metric_value(item.baseline_value, item.unit),
                    border=True,
                )
                st.caption(explanation)
    st.caption(
        "以上数值来自一个已保存的 synthetic 开发案例，用于核对指标口径；"
        "不是多场景统计结论。占用率另作为辅助状态指标，不与利用率或满足率混用。"
    )
    st.info(
        "后续正式实验将让在线规则、可行随机停放和最近可行停放使用完全相同的"
        "布局、车辆事件、约束、可见信息、随机种子与指标计算方式，再报告均值、"
        "波动和失败案例。"
    )


def _render_single_decision_explanation(repository_root: Path) -> None:
    template, decision = _story_workspace(str(repository_root), "新车入场分配")
    st.subheader("一个决策怎样体现研究思路")
    st.caption(
        "目标不是机械地挑最近车位，而是在保证可行之后，依次考虑无法恢复的阻挡、"
        "新增阻挡、剩余容量、距离、纵深和稳定编号。"
    )
    figure, _ = build_sandbox_figure(
        template.layout,
        decision.input_state,
        decision=decision,
        story_step=len(decision.story_steps) - 1,
        route_progress=1.0,
    )
    st.plotly_chart(
        figure,
        width="stretch",
        theme=None,
        config={
            "displaylogo": False,
            "responsive": True,
            "scrollZoom": True,
            "modeBarButtonsToRemove": ["lasso2d", "select2d"],
        },
        key="metrics-single-decision",
    )
    _render_arrival_explanation(decision)
    st.warning(
        "这里比较的是同一时刻的两个候选车位，不是“在线规则 vs 就近算法”的"
        "正式性能实验；它只能解释为什么本次没有选择最近可行位。"
    )


def _render_complete_audit(
    catalog: DemoCatalog,
    evidence: ComparisonEvidenceView,
) -> None:
    st.warning(
        "以下为技术审计区。滚动候选仅是待验证扩展，保存的开发配对不足以形成"
        "优越性结论；正式随机/就近对照尚未运行。"
    )
    decision_tab, metric_tab = st.tabs(("保存决策审计", "完整保存指标"))
    with decision_tab:
        _render_decision_audit(catalog.mixed_depth)
    with metric_tab:
        _render_metric_comparison(evidence)


def render_metrics_page(repository_root: Path) -> None:
    """Explain the research status before exposing complete saved audit evidence."""

    st.title("研究结论与指标")
    st.caption("先回答研究说明了什么，再提供单次决策解释与完整技术审计")
    st.badge("SYNTHETIC｜非真实采集", color="blue", icon=":material/science:")
    st.badge("正式算法对照未完成", color="orange", icon=":material/experiment:")
    st.caption("SYNTHETIC：当前数值来自合成开发案例，不代表真实停车场效果；滚动候选扩展默认关闭。")
    try:
        catalog = _catalog(str(repository_root))
    except (ImportRejectedError, OSError, TypeError, ValueError) as exc:
        st.error("D4 决策演示包未通过只读校验，页面已失败关闭。")
        st.stop()
        raise AssertionError("st.stop() must interrupt execution") from exc
    evidence = _load_evidence_or_stop(repository_root)
    conclusion_tab, decision_tab, audit_tab = st.tabs(
        ("研究结论", "单次决策解释", "完整指标与审计")
    )
    with conclusion_tab:
        _render_research_conclusion(evidence)
    with decision_tab:
        _render_single_decision_explanation(repository_root)
    with audit_tab:
        _render_complete_audit(catalog, evidence)


def render_data_page(repository_root: Path) -> None:
    """Render the D5 sanitized quality report for the committed synthetic example."""

    st.title("数据导入与校验")
    st.caption("外部字段 → 显式映射 → 冻结 v1 Schema → 语义/可达性 → 新迁移副本")
    try:
        report = load_builtin_adaptation_report(repository_root)
    except (OSError, TypeError, ValueError) as exc:
        st.error("D5 示例包无法读取；页面已失败关闭，且不会回显输入内容或绝对路径。")
        st.stop()
        raise AssertionError("st.stop() must interrupt execution") from exc

    source_col, privacy_col, status_col = st.columns(3)
    with source_col:
        st.badge("SYNTHETIC｜非实测", color="blue", icon=":material/science:")
        st.caption(f"机器标签：{report.source_kind}")
    with privacy_col:
        st.badge("ANONYMOUS", color="green", icon=":material/shield:")
        st.caption(f"隐私标签：{report.privacy_classification}")
    with status_col:
        if report.accepted:
            st.badge("接口校验通过", color="green", icon=":material/verified:")
        else:
            st.badge("失败关闭", color="red", icon=":material/block:")
        st.caption(f"目标契约：v{report.target_schema_version}")

    st.warning(
        "当前只验证适配接口和 synthetic 示例，现实校准尚未完成；"
        "不得把本页描述为真实停车场验证。脱敏映射必须在仓库外完成。"
    )
    if not report.accepted:
        st.error(
            "导入被安全拒绝。错误仅显示稳定代码："
            + "、".join(item.code for item in report.failures)
        )

    st.subheader("导入摘要")
    file_col, event_col, mapping_col, warning_col = st.columns(4)
    file_col.metric("来源文件", report.file_count, border=True)
    event_col.metric("匿名事件", report.event_count, border=True)
    mapping_col.metric(
        "显式映射字段",
        report.mapped_layout_field_count + report.mapped_event_field_count,
        border=True,
    )
    warning_col.metric("数据缺口/警告", len(report.warnings), border=True)
    st.caption(
        f"模式：{report.mode}｜总字节：{report.total_bytes:,}｜"
        "原始输入只读；需要迁移时写入新的独立目录。"
    )

    report_tab, provenance_tab, gap_tab = st.tabs(
        ("分层质量报告", "来源 SHA-256", "未识别与未校准")
    )
    with report_tab:
        st.dataframe(
            [
                {
                    "阶段": item.stage,
                    "状态": {"passed": "通过", "warning": "警告", "failed": "拒绝"}.get(
                        item.status, item.status
                    ),
                    "代码": item.code,
                    "文件": item.artifact or "包级",
                    "说明": item.message,
                    "定位": item.json_pointer or "—",
                    "修复建议": item.fix_hint or "—",
                }
                for item in report.checks
            ],
            width="stretch",
            hide_index=True,
        )
        st.caption(
            "检查包含路径、大小、UTF-8/JSON、PII、单位、时区、字段映射、v1 Schema、"
            "重复 ID、引用、纵深连续性和入口—位置—出口可达性。"
        )
    with provenance_tab:
        st.dataframe(
            [
                {
                    "来源文件": item.artifact,
                    "字节": item.size_bytes,
                    "SHA-256": item.sha256,
                }
                for item in report.source_digests
            ],
            width="stretch",
            hide_index=True,
        )
        st.info("迁移副本会保存这些来源哈希；不会保存仓库外的脱敏映射表。")
    with gap_tab:
        if report.unrecognized_fields:
            st.dataframe(
                [{"未映射字段名": item} for item in report.unrecognized_fields],
                width="stretch",
                hide_index=True,
            )
        else:
            st.success("示例包没有未映射的顶层字段。")
        st.dataframe(
            [
                {
                    "参数": item.parameter,
                    "状态": item.status,
                    "原因": item.reason,
                }
                for item in report.calibration_gaps
            ],
            width="stretch",
            hide_index=True,
        )
        st.caption("参数值即使提供，也只标记“已提供、未验证”，不会自动生成校准结论。")

    with st.expander("实际匿名数据接入步骤", expanded=False):
        st.markdown(
            "1. 在仓库外删除车牌、姓名、电话、邮箱、证件号和可逆映射；\n"
            "2. 复制 D5 模板并填写局部米制布局、匿名事件和显式字段映射；\n"
            "3. 先运行只读检查，再将通过的数据写入新的 `data/interim/` 目录；\n"
            "4. 保留来源 SHA-256 和质量报告，原始文件始终不覆盖。"
        )
