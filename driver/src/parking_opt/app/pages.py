# ruff: noqa: RUF001
"""Streamlit pages for the D2 shell and static layout."""
from __future__ import annotations
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
from parking_opt.app.static_layout import build_layout_figure, build_static_view, parse_screenshot_state
from parking_opt.application.presentation import (
    ComparisonEvidenceError,
    ComparisonEvidenceView,
    ImportRejectedError,
    ReplayNavigator,
    ValidatedDemoBundle,
    build_replay_index,
    build_replay_timeline,
)
from parking_opt.application.sandbox import (
    SandboxDecision,
    SandboxTemplate,
    load_sandbox_template,
    preview_arrival,
    preview_departure,
    set_position_closed,
)
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
        navigator=ReplayNavigator(build_replay_index(bundle, checkpoint_interval=32), build_replay_timeline(bundle), cache_entries=128),
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
        decision = preview_arrival(Path(repository_root), template.initial_state, template.layout, anonymous_vehicle_id="新车N", entrance_node_id="entry-main", decision_time_s=decision_time_s, has_reservation=False, expected_departure_time_s=None)
    elif scenario == "纵深阻挡移位":
        decision = preview_departure(Path(repository_root), template.initial_state, template.layout, anonymous_vehicle_id="车辆F", decision_time_s=decision_time_s)
    elif scenario == "无可行车位与等待":
        closed = template.initial_state
        for position in closed.positions:
            if position.position_kind.value == "normal" and position.occupant_vehicle_id is None:
                closed = set_position_closed(closed, position.position_id, closed=True)
        decision = preview_arrival(Path(repository_root), closed, template.layout, anonymous_vehicle_id="新车N", entrance_node_id="entry-main", decision_time_s=max(decision_time_s, closed.sim_time_s), has_reservation=False, expected_departure_time_s=None)
    else:
        raise ValueError("unsupported story scenario")
    return template, decision
def _load_catalog_or_stop(repository_root: Path) -> DemoCatalog:
    try:
        return _catalog(str(repository_root))
    except (ImportRejectedError, OSError, TypeError, ValueError):
        st.error("内置演示数据未通过只读校验，页面已失败关闭。请运行 D1 校验探针并修复 synthetic fixture。")
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
        st.badge(bundle.source_kind.upper(), color="blue" if bundle.source_kind == "synthetic" else "green", icon=":material/dataset:")
        st.caption("数据来源｜非真实采集")
    with middle:
        st.badge(spec.algorithm_status, color="orange", icon=":material/memory:")
        st.caption(f"算法：{bundle.algorithm_id} {bundle.algorithm_version}")
    with right:
        evidence_color: Literal["red", "gray"] = "red" if state is ScreenshotState.INSUFFICIENT_EVIDENCE else "gray"
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
        for column, (title, note) in zip(columns, framework[start : start + 4], strict=False):
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
    st.warning("正式随机停放、就近停放及其他对照实验尚未完成。当前展示用于说明算法流程与系统能力，不构成性能优越性或真实场地效果结论。")
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
    state = st.selectbox("规范截图状态", options=states, index=states.index(initial_state), format_func=lambda item: SCREENSHOT_STATE_SPECS[item].label, key="d2_screenshot_state")
    st.query_params["state"] = state.value
    _render_evidence_badges(state, catalog)
    bundle = catalog.for_state(state)
    view = build_static_view(bundle.layout, state)
    status_legend = "　".join(f"{spec.glyph} {spec.label}" for spec in POSITION_STATUS_SPECS.values())
    st.caption(f"状态图例: {status_legend}")
    st.plotly_chart(build_layout_figure(view), width="stretch", theme=None, config={"displaylogo": False, "responsive": True, "scrollZoom": True, "modeBarButtonsToRemove": ["lasso2d", "select2d"]}, key=f"d2-layout-{state.value}")
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
from parking_opt.app.pages_data import render_data_page  # noqa: E402
from parking_opt.app.pages_replay import render_replay_page  # noqa: E402
from parking_opt.app.pages_sandbox import render_sandbox_page  # noqa: E402
from parking_opt.app.pages_metrics import render_metrics_page  # noqa: E402
