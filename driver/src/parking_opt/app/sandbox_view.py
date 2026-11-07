# ruff: noqa: RUF001
"""Plotly views for the synthetic online-rule teaching sandbox."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from math import hypot
from types import MappingProxyType

import plotly.graph_objects as go  # type: ignore[import-untyped]

from parking_opt.app.design import FONT_FAMILY
from parking_opt.application.sandbox import (
    CandidateExplanation,
    SandboxDecision,
    action_route_coordinates,
)
from parking_opt.domain.enums import PositionKind
from parking_opt.domain.state import AuthoritativeState
from parking_opt.layout.model import BufferSlot, Layout, Slot

REASON_LABELS = MappingProxyType(
    {
        "POSITION_PHYSICALLY_UNAVAILABLE": "车位物理不可用",
        "POSITION_NOT_ASSIGNABLE": "车位当前禁止分配",
        "POSITION_PLANNED_CLOSURE": "车位计划关闭",
        "POSITION_OCCUPIED_OR_RESERVED": "车位已占用或被预留",
        "STACK_GROUP_BUSY": "所在纵深组正在执行事务",
        "ENTRY_NOT_CLEAR": "进入路径被浅位占用或锁定",
        "ENTRY_PATH_UNREACHABLE": "入口到车位不可达",
        "UNRECOVERABLE_BLOCKING_EXPOSURE": "会产生无法自动恢复的阻挡",
    }
)


@dataclass(frozen=True, slots=True)
class SandboxFigureSummary:
    """Small deterministic diagnostic for tests and page captions."""

    occupied_count: int
    free_count: int
    closed_count: int
    feasible_candidate_count: int
    excluded_candidate_count: int


def candidate_reason_text(candidate: CandidateExplanation) -> str:
    """Translate stable machine reason codes into concise Chinese."""

    if candidate.feasible:
        return "可行候选"
    return "；".join(REASON_LABELS.get(code, code) for code in candidate.reason_codes)


def candidate_rows(
    decision: SandboxDecision,
    *,
    feasible_limit: int | None = None,
) -> tuple[dict[str, object], ...]:
    """Build display rows without changing candidate ranking."""

    feasible = [item for item in decision.candidates if item.feasible]
    excluded = [item for item in decision.candidates if not item.feasible]
    if feasible_limit is not None:
        feasible = feasible[:feasible_limit]
    return tuple(
        {
            "排名": item.rank or "—",
            "车位": item.position_id,
            "结果": "最终选择"
            if item.position_id == decision.selected_position_id
            else "可行候选"
            if item.feasible
            else "已排除",
            "阻挡风险": item.incremental_unrecoverable_exposure
            if item.incremental_unrecoverable_exposure is not None
            else "—",
            "新增阻挡": item.incremental_blocked_vehicle_count
            if item.incremental_blocked_vehicle_count is not None
            else "—",
            "剩余一步容量": item.remaining_one_step_assignable_capacity
            if item.remaining_one_step_assignable_capacity is not None
            else "—",
            "路径距离": f"{item.distance_m:.1f} m" if item.distance_m is not None else "—",
            "depth": item.depth,
            "说明": candidate_reason_text(item),
        }
        for item in (*feasible, *excluded)
    )


def _road_traces(layout: Layout) -> tuple[go.Scatter, go.Scatter]:
    nodes = {item.road_node_id: item for item in layout.road_nodes}
    x: list[float | None] = []
    y: list[float | None] = []
    for edge in layout.road_edges:
        start = nodes[edge.from_node_id]
        end = nodes[edge.to_node_id]
        x.extend((start.x_m, end.x_m, None))
        y.extend((start.y_m, end.y_m, None))
    road = go.Scatter(
        x=x,
        y=y,
        mode="lines",
        line={"color": "#94A3B8", "width": 7},
        hoverinfo="skip",
        showlegend=False,
        name="通道路网",
    )
    connector_x: list[float | None] = []
    connector_y: list[float | None] = []
    for slot in layout.slots:
        access = nodes[slot.access_node_id]
        connector_x.extend((access.x_m, slot.x_m, None))
        connector_y.extend((access.y_m, slot.y_m, None))
    connector = go.Scatter(
        x=connector_x,
        y=connector_y,
        mode="lines",
        line={"color": "#CBD5E1", "width": 1.5, "dash": "dot"},
        hoverinfo="skip",
        showlegend=False,
        name="车位连接",
    )
    return road, connector


def _interpolate_route(
    route: tuple[tuple[float, float], ...],
    progress: float,
) -> tuple[float, float] | None:
    if not route:
        return None
    if len(route) == 1:
        return route[0]
    bounded = min(max(progress, 0.0), 1.0)
    lengths = tuple(
        hypot(right[0] - left[0], right[1] - left[1]) for left, right in pairwise(route)
    )
    total = sum(lengths)
    if total <= 0:
        return route[-1]
    target = bounded * total
    traversed = 0.0
    for (left, right), length in zip(pairwise(route), lengths, strict=True):
        if traversed + length >= target:
            ratio = 0.0 if length == 0 else (target - traversed) / length
            return (
                left[0] + ratio * (right[0] - left[0]),
                left[1] + ratio * (right[1] - left[1]),
            )
        traversed += length
    return route[-1]


def _active_action(decision: SandboxDecision | None, story_step: int):  # type: ignore[no-untyped-def]
    if decision is None or not decision.result.recommended_actions:
        return None
    actions = decision.result.recommended_actions
    if decision.decision_kind == "ARRIVAL":
        return actions[0] if story_step >= len(decision.story_steps) - 1 else None
    if len(actions) == 1:
        return actions[0] if story_step >= 1 else None
    action_index = min(max(story_step - 1, 0), len(actions) - 1)
    return actions[action_index]


def build_sandbox_figure(
    layout: Layout,
    state: AuthoritativeState,
    *,
    decision: SandboxDecision | None = None,
    story_step: int = 0,
    route_progress: float = 0.0,
) -> tuple[go.Figure, SandboxFigureSummary]:
    """Render visible vehicles, candidates, and one management-level route."""

    positions = {item.position_id: item for item in state.positions}
    candidates = {
        item.position_id: item for item in (() if decision is None else decision.candidates)
    }
    selected_id = None if decision is None else decision.selected_position_id
    top_ids = {
        item.position_id
        for item in candidates.values()
        if item.feasible and item.rank is not None and item.rank <= 5
    }
    figure = go.Figure()
    for trace in _road_traces(layout):
        figure.add_trace(trace)

    normal_by_id = {item.position_id: item for item in layout.slots}
    all_positions: tuple[Slot | BufferSlot, ...] = (
        *layout.slots,
        *layout.buffer_slots,
    )
    occupied_count = 0
    free_count = 0
    closed_count = 0
    x_values: list[float] = []
    y_values: list[float] = []
    colors: list[str] = []
    sizes: list[int] = []
    symbols: list[str] = []
    border_colors: list[str] = []
    border_widths: list[int] = []
    labels: list[str] = []
    hover: list[str] = []
    for position in all_positions:
        item = positions[position.position_id]
        candidate = candidates.get(position.position_id)
        if item.occupant_vehicle_id is not None:
            occupied_count += 1
            color, symbol, size = "#2563EB", "square", 21
        elif not item.physically_available or item.planned_closure:
            closed_count += 1
            color, symbol, size = "#334155", "x", 18
        elif item.position_kind is PositionKind.BUFFER:
            free_count += 1
            color, symbol, size = "#F59E0B", "diamond-open", 20
        else:
            free_count += 1
            color, symbol, size = "#E2E8F0", "square-open", 16
        border_color, border_width = "#64748B", 1
        if candidate is not None and not candidate.feasible:
            border_color, border_width = "#DC2626", 1
        if position.position_id in top_ids:
            border_color, border_width, size = "#16A34A", 3, max(size, 21)
        if position.position_id == selected_id:
            color, border_color, border_width, size = "#0EA5E9", "#075985", 4, 27
        x_values.append(position.x_m)
        y_values.append(position.y_m)
        colors.append(color)
        symbols.append(symbol)
        sizes.append(size)
        border_colors.append(border_color)
        border_widths.append(border_width)
        labels.append(item.occupant_vehicle_id or "")
        candidate_text = "未参与本次候选"
        if candidate is not None:
            candidate_text = (
                f"可行｜排名 {candidate.rank}"
                if candidate.feasible
                else f"排除｜{candidate_reason_text(candidate)}"
            )
        depth = (
            normal_by_id[position.position_id].depth
            if position.position_id in normal_by_id
            else "—"
        )
        hover.append(
            f"<b>{position.position_id}</b><br>"
            f"车辆：{item.occupant_vehicle_id or '无'}<br>"
            f"depth：{depth}<br>"
            f"候选：{candidate_text}"
        )
    figure.add_trace(
        go.Scatter(
            x=x_values,
            y=y_values,
            mode="markers+text",
            marker={
                "size": sizes,
                "color": colors,
                "symbol": symbols,
                "line": {"color": border_colors, "width": border_widths},
            },
            text=labels,
            textposition="middle center",
            textfont={"family": FONT_FAMILY, "size": 10, "color": "#FFFFFF"},
            hovertext=hover,
            hovertemplate="%{hovertext}<extra></extra>",
            showlegend=False,
            name="车位与车辆",
        )
    )
    entrances = [item for item in layout.road_nodes if item.node_kind == "entrance"]
    exits = [item for item in layout.road_nodes if item.node_kind == "exit"]
    figure.add_trace(
        go.Scatter(
            x=[item.x_m for item in (*entrances, *exits)],
            y=[item.y_m for item in (*entrances, *exits)],
            mode="markers+text",
            marker={
                "size": [22] * len(entrances) + [22] * len(exits),
                "symbol": ["triangle-right"] * (len(entrances) + len(exits)),
                "color": ["#16A34A"] * len(entrances) + ["#DC2626"] * len(exits),
            },
            text=["入口"] * len(entrances) + ["出口"] * len(exits),
            textposition="top center",
            hoverinfo="skip",
            showlegend=False,
        )
    )
    action = _active_action(decision, story_step)
    if action is not None:
        route = action_route_coordinates(layout, action)
        if route:
            figure.add_trace(
                go.Scatter(
                    x=[point[0] for point in route],
                    y=[point[1] for point in route],
                    mode="lines",
                    line={"color": "#0EA5E9", "width": 7},
                    hoverinfo="skip",
                    showlegend=False,
                    name="推荐路线",
                )
            )
            marker = _interpolate_route(route, route_progress)
            if marker is not None:
                figure.add_trace(
                    go.Scatter(
                        x=[marker[0]],
                        y=[marker[1]],
                        mode="markers+text",
                        marker={
                            "size": 29,
                            "color": "#F97316",
                            "symbol": "circle",
                            "line": {"color": "#7C2D12", "width": 3},
                        },
                        text=[action.anonymous_vehicle_id],
                        textfont={"family": FONT_FAMILY, "size": 11, "color": "#FFFFFF"},
                        textposition="middle center",
                        hovertemplate=(
                            f"<b>{action.anonymous_vehicle_id}</b><br>"
                            f"动作：{action.action_type.value}<extra></extra>"
                        ),
                        showlegend=False,
                    )
                )
    elif decision is not None and decision.decision_kind == "ARRIVAL" and entrances:
        figure.add_trace(
            go.Scatter(
                x=[entrances[0].x_m],
                y=[entrances[0].y_m],
                mode="markers+text",
                marker={
                    "size": 29,
                    "color": "#F97316",
                    "symbol": "circle",
                    "line": {"color": "#7C2D12", "width": 3},
                },
                text=[decision.result.target_anonymous_vehicle_id],
                textfont={"family": FONT_FAMILY, "size": 11, "color": "#FFFFFF"},
                textposition="middle center",
                hoverinfo="skip",
                showlegend=False,
            )
        )
    figure.update_layout(
        height=500 if len(layout.slots) <= 30 else 620,
        margin={"l": 24, "r": 24, "t": 24, "b": 36},
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#F8FAFC",
        font={"family": FONT_FAMILY, "size": 13, "color": "#0F172A"},
        hoverlabel={"font": {"family": FONT_FAMILY, "size": 13}},
        showlegend=False,
        xaxis={
            "title": "停车场横向位置（米）",
            "gridcolor": "#E2E8F0",
            "zeroline": False,
            "fixedrange": False,
        },
        yaxis={
            "title": "距主通道方向（米）",
            "gridcolor": "#E2E8F0",
            "zeroline": False,
            "fixedrange": False,
            "scaleanchor": "x",
            "scaleratio": 1,
        },
        uirevision=f"sandbox-{layout.layout_id}",
    )
    summary = SandboxFigureSummary(
        occupied_count=occupied_count,
        free_count=free_count,
        closed_count=closed_count,
        feasible_candidate_count=sum(item.feasible for item in candidates.values()),
        excluded_candidate_count=sum(not item.feasible for item in candidates.values()),
    )
    return figure, summary


__all__ = [
    "REASON_LABELS",
    "SandboxFigureSummary",
    "build_sandbox_figure",
    "candidate_reason_text",
    "candidate_rows",
]
