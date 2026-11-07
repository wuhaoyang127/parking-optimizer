"""Plotly figure construction for the synthetic sandbox."""

from __future__ import annotations

import plotly.graph_objects as go  # type: ignore[import-untyped]

from parking_opt.app.design import FONT_FAMILY
from parking_opt.app.sandbox_view import (
    REASON_LABELS,
    SandboxFigureSummary,
    _active_action,
    _interpolate_route,
    _road_traces,
    candidate_reason_text,
)
from parking_opt.application.sandbox import SandboxDecision, action_route_coordinates
from parking_opt.domain.enums import PositionKind
from parking_opt.domain.state import AuthoritativeState
from parking_opt.layout.model import BufferSlot, Layout, Slot


def _position_markers(layout, state, candidates, top_ids, selected_id):
    positions = {item.position_id: item for item in state.positions}
    normal_by_id = {item.position_id: item for item in layout.slots}
    all_positions: tuple[Slot | BufferSlot, ...] = (*layout.slots, *layout.buffer_slots)
    occupied_count = free_count = closed_count = 0
    x_values, y_values, colors, sizes, symbols = [], [], [], [], []
    border_colors, border_widths, labels, hover = [], [], [], []
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
                f"可行｜排名 {candidate.rank}" if candidate.feasible
                else f"排除｜{candidate_reason_text(candidate)}"
            )
        depth = (
            normal_by_id[position.position_id].depth
            if position.position_id in normal_by_id
            else "—"
        )
        hover.append(
            f"<b>{position.position_id}</b><br>车辆：{item.occupant_vehicle_id or '无'}<br>"
            f"depth：{depth}<br>候选：{candidate_text}"
        )
    trace = go.Scatter(
        x=x_values, y=y_values, mode="markers+text",
        marker={"size": sizes, "color": colors, "symbol": symbols,
                "line": {"color": border_colors, "width": border_widths}},
        text=labels, textposition="middle center",
        textfont={"family": FONT_FAMILY, "size": 10, "color": "#FFFFFF"},
        hovertext=hover, hovertemplate="%{hovertext}<extra></extra>",
        showlegend=False, name="车位与车辆",
    )
    return trace, occupied_count, free_count, closed_count


def _action_markers(figure, layout, decision, story_step, route_progress, entrances):
    action = _active_action(decision, story_step)
    if action is not None:
        route = action_route_coordinates(layout, action)
        if route:
            figure.add_trace(go.Scatter(
                x=[p[0] for p in route], y=[p[1] for p in route], mode="lines",
                line={"color": "#0EA5E9", "width": 7}, hoverinfo="skip",
                showlegend=False, name="推荐路线"))
            marker = _interpolate_route(route, route_progress)
            if marker is not None:
                figure.add_trace(go.Scatter(
                    x=[marker[0]], y=[marker[1]], mode="markers+text",
                    marker={"size": 29, "color": "#F97316", "symbol": "circle",
                            "line": {"color": "#7C2D12", "width": 3}},
                    text=[action.anonymous_vehicle_id],
                    textfont={"family": FONT_FAMILY, "size": 11, "color": "#FFFFFF"},
                    textposition="middle center",
                    hovertemplate=f"<b>{action.anonymous_vehicle_id}</b><br>动作：{action.action_type.value}<extra></extra>",
                    showlegend=False))
    elif decision is not None and decision.decision_kind == "ARRIVAL" and entrances:
        figure.add_trace(go.Scatter(
            x=[entrances[0].x_m], y=[entrances[0].y_m], mode="markers+text",
            marker={"size": 29, "color": "#F97316", "symbol": "circle",
                    "line": {"color": "#7C2D12", "width": 3}},
            text=[decision.result.target_anonymous_vehicle_id],
            textfont={"family": FONT_FAMILY, "size": 11, "color": "#FFFFFF"},
            textposition="middle center", hoverinfo="skip", showlegend=False))


def build_sandbox_figure(
    layout: Layout,
    state: AuthoritativeState,
    *,
    decision: SandboxDecision | None = None,
    story_step: int = 0,
    route_progress: float = 0.0,
) -> tuple[go.Figure, SandboxFigureSummary]:
    candidates = {item.position_id: item for item in (() if decision is None else decision.candidates)}
    selected_id = None if decision is None else decision.selected_position_id
    top_ids = {
        item.position_id for item in candidates.values()
        if item.feasible and item.rank is not None and item.rank <= 5
    }
    figure = go.Figure()
    for trace in _road_traces(layout):
        figure.add_trace(trace)
    trace, occupied_count, free_count, closed_count = _position_markers(
        layout, state, candidates, top_ids, selected_id)
    figure.add_trace(trace)
    entrances = [item for item in layout.road_nodes if item.node_kind == "entrance"]
    exits = [item for item in layout.road_nodes if item.node_kind == "exit"]
    figure.add_trace(go.Scatter(
        x=[item.x_m for item in (*entrances, *exits)],
        y=[item.y_m for item in (*entrances, *exits)], mode="markers+text",
        marker={"size": [22] * len(entrances) + [22] * len(exits),
                "symbol": ["triangle-right"] * (len(entrances) + len(exits)),
                "color": ["#16A34A"] * len(entrances) + ["#DC2626"] * len(exits)},
        text=["入口"] * len(entrances) + ["出口"] * len(exits),
        textposition="top center", hoverinfo="skip", showlegend=False))
    _action_markers(figure, layout, decision, story_step, route_progress, entrances)
    figure.update_layout(
        height=500 if len(layout.slots) <= 30 else 620,
        margin={"l": 24, "r": 24, "t": 24, "b": 36},
        paper_bgcolor="#FFFFFF", plot_bgcolor="#F8FAFC",
        font={"family": FONT_FAMILY, "size": 13, "color": "#0F172A"},
        hoverlabel={"font": {"family": FONT_FAMILY, "size": 13}}, showlegend=False,
        xaxis={"title": "停车场横向位置（米）", "gridcolor": "#E2E8F0",
               "zeroline": False, "fixedrange": False},
        yaxis={"title": "距主通道方向（米）", "gridcolor": "#E2E8F0",
               "zeroline": False, "fixedrange": False, "scaleanchor": "x", "scaleratio": 1},
        uirevision=f"sandbox-{layout.layout_id}",
    )
    summary = SandboxFigureSummary(
        occupied_count=occupied_count, free_count=free_count, closed_count=closed_count,
        feasible_candidate_count=sum(item.feasible for item in candidates.values()),
        excluded_candidate_count=sum(not item.feasible for item in candidates.values()),
    )
    return figure, summary
