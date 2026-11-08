# ruff: noqa: RUF001
"""D4 research conclusion and metrics page."""
from __future__ import annotations
from pathlib import Path
import streamlit as st
from parking_opt.app.data import DemoCatalog
from parking_opt.app.metrics_view import METRIC_LABELS, UNIT_LABELS, build_ratio_comparison_figure
from parking_opt.app.pages import _catalog, _load_evidence_or_stop, _story_workspace
from parking_opt.app.pages_story import _render_arrival_explanation
from parking_opt.app.sandbox_view import build_sandbox_figure
from parking_opt.application.presentation import ComparisonEvidenceView
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
        f"研究门：{evidence.research_gate_status}｜核心配对 {evidence.formal_pair_count}/{evidence.required_formal_pair_count}｜"
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
    st.caption("信息条件：online 仅使用 ObservedSnapshot；rolling 使用相同可见信息做有界窗口候选；oracle 是离线全信息基准，三者不可混写为同一信息条件。")
def _metric_by_name(evidence: ComparisonEvidenceView, name: str):  # type: ignore[no-untyped-def]
    return next(item for item in evidence.metrics if item.metric_name == name)
def _render_key_metric_card(container, evidence: ComparisonEvidenceView, name: str) -> None:  # type: ignore[no-untyped-def]
    item = _metric_by_name(evidence, name)
    with container:
        st.metric(METRIC_LABELS[name], _format_metric_value(item.baseline_value, item.unit), border=True, help="主值为保存的在线规则基线绝对值；下方另列滚动候选，不使用排名箭头。")
        st.caption(f"滚动候选：{_format_metric_value(item.candidate_value, item.unit)}｜候选减基线：{_format_difference(item.paired_difference, item.unit)}｜n={item.sample_n}")
def _render_metric_comparison(evidence: ComparisonEvidenceView) -> None:
    st.subheader("保存指标明细｜开发审计")
    first_row = st.columns(3)
    for container, name in zip(first_row, ("occupancy_rate", "normal_space_time_utilization", "facility_position_space_time_utilization"), strict=True):
        _render_key_metric_card(container, evidence, name)
    second_row = st.columns(2)
    for container, name in zip(second_row, ("demand_satisfaction_rate", "throughput_per_hour"), strict=True):
        _render_key_metric_card(container, evidence, name)
    st.plotly_chart(
        build_ratio_comparison_figure(evidence),
        width="stretch",
        theme=None,
        config={"displaylogo": False, "responsive": True, "modeBarButtonsToRemove": ["lasso2d", "select2d"]},
        key="d4-ratio-comparison",
    )
    st.caption("图中只绘制绝对比例并使用文字/纹理区分算法；不按优劣排序，不用箭头或颜色暗示研究门通过。")
    st.subheader("完整保存指标")
    st.dataframe(
        [
            {
                "指标": METRIC_LABELS[item.metric_name],
                "机器名": item.metric_name,
                "口径": "仅完成样本" if item.completed_only else "右删失率" if item.censoring_rate else "标准聚合",
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
    st.warning(f"滚动候选保存了 {candidate.fallback_count} 次回退，回退率 {candidate.fallback_rate * 100:.2f}%；在线基线为 {baseline.fallback_count} 次 / {baseline.fallback_rate * 100:.2f}%。")
    st.dataframe(
        [
            {"算法": "在线规则基线", "pending@horizon": baseline.pending_request_count_at_horizon, "fallback": baseline.fallback_count, "fallback rate": f"{baseline.fallback_rate * 100:.2f}%", "硬截止违反": baseline.hard_deadline_violation_count, "状态不变量违反": baseline.state_invariant_violation_count},
            {"算法": "滚动候选", "pending@horizon": candidate.pending_request_count_at_horizon, "fallback": candidate.fallback_count, "fallback rate": f"{candidate.fallback_rate * 100:.2f}%", "硬截止违反": candidate.hard_deadline_violation_count, "状态不变量违反": candidate.state_invariant_violation_count},
        ],
        width="stretch",
        hide_index=True,
    )
    with st.expander("RunManifest、配对键与产物哈希", expanded=False):
        st.dataframe(
            [
                {"角色": "baseline", "run_id": baseline.run_id, "algorithm": f"{baseline.algorithm_id} {baseline.algorithm_version}", "Git": baseline.git_commit, "input SHA-256": baseline.input_data_sha256, "config SHA-256": baseline.config_sha256, "状态": baseline.run_status},
                {"角色": "candidate", "run_id": candidate.run_id, "algorithm": f"{candidate.algorithm_id} {candidate.algorithm_version}", "Git": candidate.git_commit, "input SHA-256": candidate.input_data_sha256, "config SHA-256": candidate.config_sha256, "状态": candidate.run_status},
            ],
            width="stretch",
            hide_index=True,
        )
        st.caption("公平配对键：" + "｜".join(f"{key}={value}" for key, value in evidence.pair_key) + f"｜状态={evidence.pair_key_status}")
        st.dataframe([{"产物": artifact, "SHA-256": digest} for artifact, digest in evidence.artifact_sha256], width="stretch", hide_index=True)
_RESEARCH_METRICS = (
    ("demand_satisfaction_rate", "需求满足率", "成功获得服务的到达需求占全部到达需求的比例。"),
    ("facility_position_space_time_utilization", "车位时空利用率", "观察期内，全部可用位置被有效占用的“位置×时间”比例。"),
    ("throughput_per_hour", "单位时间吞吐量", "每小时完成服务的车辆数，反映停车场处理需求的速度。"),
    ("relocation_count", "移位次数", "为让被阻挡车辆离场而执行的临时移车次数。"),
    ("relocation_distance_m", "移位距离", "所有移位车辆在管理层路径上的累计移动距离。"),
    ("departure_delay_s_completed_only_mean", "出库延误", "已完成离场车辆从提出请求到实际离场的平均额外时间。"),
)
def _render_research_conclusion(evidence: ComparisonEvidenceView) -> None:
    st.subheader("这项研究目前说明了什么")
    verified, observed, pending = st.columns(3)
    verified.success("**已经验证**\n\n在线规则只使用当时可见信息；候选可行性、纵深阻挡、缓冲移位、失败关闭和固定种子复现均有代码与测试。")
    observed.info("**合成案例可以观察**\n\n系统能在拥挤布局中逐层筛选车位，并在最近车位可能增加阻挡时选择另一可行位置；这只是单案例机制说明。")
    pending.warning("**仍待正式验证**\n\n与可行随机停放、最近可行停放的公平实验，以及真实停车场校准尚未完成；因此不能声称当前算法性能更优。")
    st.subheader("六个默认研究指标")
    for start in (0, 3):
        columns = st.columns(3)
        for column, (machine_name, label, explanation) in zip(columns, _RESEARCH_METRICS[start : start + 3], strict=True):
            item = _metric_by_name(evidence, machine_name)
            with column:
                st.metric(label, _format_metric_value(item.baseline_value, item.unit), border=True)
                st.caption(explanation)
    st.caption("以上数值来自一个已保存的 synthetic 开发案例，用于核对指标口径；不是多场景统计结论。占用率另作为辅助状态指标，不与利用率或满足率混用。")
    st.info("后续正式实验将让在线规则、可行随机停放和最近可行停放使用完全相同的布局、车辆事件、约束、可见信息、随机种子与指标计算方式，再报告均值、波动和失败案例。")
def _render_single_decision_explanation(repository_root: Path) -> None:
    template, decision = _story_workspace(str(repository_root), "新车入场分配")
    st.subheader("一个决策怎样体现研究思路")
    st.caption("目标不是机械地挑最近车位，而是在保证可行之后，依次考虑无法恢复的阻挡、新增阻挡、剩余容量、距离、纵深和稳定编号。")
    figure, _ = build_sandbox_figure(template.layout, decision.input_state, decision=decision, story_step=len(decision.story_steps) - 1, route_progress=1.0)
    st.plotly_chart(figure, width="stretch", theme=None, config={"displaylogo": False, "responsive": True, "scrollZoom": True, "modeBarButtonsToRemove": ["lasso2d", "select2d"]}, key="metrics-single-decision")
    _render_arrival_explanation(decision)
    st.warning("这里比较的是同一时刻的两个候选车位，不是“在线规则 vs 就近算法”的正式性能实验；它只能解释为什么本次没有选择最近可行位。")
def _render_complete_audit(
    catalog: DemoCatalog,
    evidence: ComparisonEvidenceView,
) -> None:
    st.warning("以下为技术审计区。滚动候选仅是待验证扩展，保存的开发配对不足以形成优越性结论；正式随机/就近对照尚未运行。")
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
    conclusion_tab, decision_tab, audit_tab = st.tabs(("研究结论", "单次决策解释", "完整指标与审计"))
    with conclusion_tab:
        _render_research_conclusion(evidence)
    with decision_tab:
        _render_single_decision_explanation(repository_root)
    with audit_tab:
        _render_complete_audit(catalog, evidence)
from parking_opt.app.pages_audit import _render_decision_audit  # noqa: E402
from parking_opt.application.presentation import ImportRejectedError  # noqa: E402
