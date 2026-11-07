# ruff: noqa: RUF001
"""Neutral Plotly projections for D4 saved comparison evidence."""

from __future__ import annotations

from types import MappingProxyType

import plotly.graph_objects as go  # type: ignore[import-untyped]

from parking_opt.app.design import FONT_FAMILY
from parking_opt.application.presentation import ComparisonEvidenceView

METRIC_LABELS = MappingProxyType(
    {
        "occupancy_rate": "期末占用率",
        "normal_space_time_utilization": "正常位时空利用率",
        "facility_position_space_time_utilization": "设施位置时空利用率",
        "buffer_utilization": "缓冲位利用率",
        "demand_satisfaction_rate": "需求满足率",
        "throughput_per_hour": "每小时吞吐量",
        "relocation_count": "移位次数",
        "relocation_distance_m": "移位距离",
        "arrival_wait_s_completed_only_mean": "到达等待（仅完成样本）",
        "departure_wait_s_completed_only_mean": "离场等待（仅完成样本）",
        "departure_delay_s_completed_only_mean": "离场延误（仅完成样本）",
        "arrival_wait_s_censoring_rate": "到达等待右删失率",
        "departure_wait_s_censoring_rate": "离场等待右删失率",
        "departure_delay_s_censoring_rate": "离场延误右删失率",
        "executor_utilization": "执行器利用率",
        "channel_zone_utilization": "通道区利用率",
        "fallback_count": "回退次数",
        "manual_intervention_count": "人工介入次数",
        "sla_violation_count": "离场 SLA 违反次数",
        "failed_action_count": "失败动作次数",
    }
)

UNIT_LABELS = MappingProxyType(
    {
        "ratio": "比例",
        "count": "次",
        "meter": "米",
        "second": "秒",
        "per_hour": "辆/小时",
    }
)


def build_ratio_comparison_figure(evidence: ComparisonEvidenceView) -> go.Figure:
    """Show saved ratio values as absolute values, never as a ranking."""

    selected_names = (
        "occupancy_rate",
        "normal_space_time_utilization",
        "facility_position_space_time_utilization",
        "demand_satisfaction_rate",
        "executor_utilization",
        "channel_zone_utilization",
    )
    by_name = {item.metric_name: item for item in evidence.metrics}
    selected = [by_name[name] for name in selected_names if name in by_name]
    labels = [METRIC_LABELS[item.metric_name] for item in selected]
    figure = go.Figure()
    figure.add_bar(
        name="在线规则基线｜绝对值",
        y=labels,
        x=[item.baseline_value * 100 for item in selected],
        orientation="h",
        marker={"color": "#2563EB", "pattern": {"shape": ""}},
        customdata=[[item.sample_n, item.baseline_value] for item in selected],
        hovertemplate=(
            "%{y}<br>在线基线：%{customdata[1]:.4f}<br>配对 n=%{customdata[0]}<extra></extra>"
        ),
    )
    figure.add_bar(
        name="滚动候选｜绝对值",
        y=labels,
        x=[item.candidate_value * 100 for item in selected],
        orientation="h",
        marker={"color": "#7C3AED", "pattern": {"shape": "/"}},
        customdata=[[item.sample_n, item.candidate_value] for item in selected],
        hovertemplate=(
            "%{y}<br>滚动候选：%{customdata[1]:.4f}<br>配对 n=%{customdata[0]}<extra></extra>"
        ),
    )
    figure.update_layout(
        title="已保存绝对比例（配对 n=1，不表达排名或研究门结论）",
        barmode="group",
        height=390,
        margin={"l": 190, "r": 30, "t": 70, "b": 55},
        font={"family": FONT_FAMILY, "size": 13, "color": "#0F172A"},
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        xaxis={
            "title": "百分比（%）",
            "range": [0, 105],
            "gridcolor": "#E2E8F0",
            "ticksuffix": "%",
        },
        yaxis={"autorange": "reversed"},
        legend={"orientation": "h", "y": -0.18, "x": 0},
        hoverlabel={"font": {"family": FONT_FAMILY, "size": 13}},
        uirevision="d4-saved-ratio-comparison",
    )
    return figure
