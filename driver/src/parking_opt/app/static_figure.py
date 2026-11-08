"""Assemble the full static-layout Plotly figure."""

from __future__ import annotations

from types import MappingProxyType

import plotly.graph_objects as go  # type: ignore[import-untyped]

from parking_opt.app.design import FONT_FAMILY, POSITION_STATUS_SPECS
from parking_opt.app.static_layout import (
    ReplayLayoutView,
    StaticLayoutView,
    _tandem_groups,
)
from parking_opt.app.static_render import _position_trace, _road_trace, _stack_connectors


def _add_action_overlays(figure: go.Figure, view: ReplayLayoutView) -> None:
    positions = {item.position_id: (item.x_m, item.y_m) for item in view.layout.slots}
    positions.update({item.position_id: (item.x_m, item.y_m) for item in view.layout.buffer_slots})
    nodes = {item.road_node_id: (item.x_m, item.y_m) for item in view.layout.road_nodes}
    status_colors = {
        "RECOMMENDED": "#64748B",
        "ACCEPTED": "#7C3AED",
        "WAITING_FOR_RESOURCES": "#D97706",
        "STARTED": "#2563EB",
        "COMPLETED": "#16A34A",
        "FAILED": "#DC2626",
    }
    for action in view.action_overlays:
        origin_key = action.origin_position_id
        if origin_key is None:
            entrance = next(
                (item for item in view.layout.road_nodes if item.node_kind == "entrance"),
                None,
            )
            start = None if entrance is None else (entrance.x_m, entrance.y_m)
        else:
            start = positions.get(origin_key)
        if action.destination_position_id is not None:
            end = positions.get(action.destination_position_id)
        elif action.destination_exit_id is not None:
            end = nodes.get(action.destination_exit_id)
        else:
            end = None
        if start is None or end is None:
            continue
        color = status_colors.get(action.status, "#475569")
        figure.add_annotation(
            x=end[0],
            y=end[1],
            ax=start[0],
            ay=start[1],
            xref="x",
            yref="y",
            axref="x",
            ayref="y",
            text=f"{action.action_type} · {action.status}",
            showarrow=True,
            arrowhead=3,
            arrowwidth=2,
            arrowcolor=color,
            font={"family": FONT_FAMILY, "size": 10, "color": color},
            bgcolor="rgba(255,255,255,0.88)",
            bordercolor=color,
            borderwidth=1,
        )


def build_layout_figure(
    view: StaticLayoutView | ReplayLayoutView,
    *,
    dark: bool = False,
) -> go.Figure:
    """Render one local-resource Plotly figure with redundant state encoding."""

    if not isinstance(view, StaticLayoutView | ReplayLayoutView):
        raise TypeError("view must be a static or replay layout view")
    background = "#0B1220" if dark else "#FFFFFF"
    text = "#F8FAFC" if dark else "#0F172A"
    grid = "#334155" if dark else "#E2E8F0"
    figure = go.Figure()
    figure.add_trace(_road_trace(view.layout))
    figure.add_trace(_stack_connectors(view.layout))
    for status in POSITION_STATUS_SPECS:
        figure.add_trace(_position_trace(view, status))
    if isinstance(view, ReplayLayoutView):
        _add_action_overlays(figure, view)

    entrances = [item for item in view.layout.road_nodes if item.node_kind == "entrance"]
    exits = [item for item in view.layout.road_nodes if item.node_kind == "exit"]
    figure.add_trace(
        go.Scatter(
            x=[item.x_m for item in entrances],
            y=[item.y_m for item in entrances],
            mode="markers+text",
            marker={"size": 18, "symbol": "triangle-right", "color": "#16A34A"},
            text=["入口"] * len(entrances),
            textposition="top center",
            name="▶ 入口",
            hovertemplate="入口：%{text}<extra></extra>",
            showlegend=False,
        )
    )
    figure.add_trace(
        go.Scatter(
            x=[item.x_m for item in exits],
            y=[item.y_m for item in exits],
            mode="markers+text",
            marker={"size": 18, "symbol": "triangle-right", "color": "#DC2626"},
            text=["出口"] * len(exits),
            textposition="top center",
            name="▶ 出口",
            hovertemplate="出口：%{text}<extra></extra>",
            showlegend=False,
        )
    )
    if _tandem_groups(view.layout):
        figure.add_annotation(
            x=7,
            y=14,
            ax=7,
            ay=2,
            xref="x",
            yref="y",
            axref="x",
            ayref="y",
            text="远离通道：depth 1 → 2",
            showarrow=True,
            arrowhead=3,
            arrowwidth=2,
            arrowcolor="#1D4ED8",
            font={"family": FONT_FAMILY, "size": 12, "color": text},
            bgcolor=background,
            bordercolor="#1D4ED8",
            borderwidth=1,
        )
    channel_label = " / ".join(
        f"{item.channel_zone_id}（容量 {item.capacity}）" for item in view.layout.channel_zones
    )
    figure.add_annotation(
        x=55,
        y=0,
        text=f"通道区：{channel_label}",
        showarrow=False,
        font={"family": FONT_FAMILY, "size": 12, "color": "#FFFFFF"},
        bgcolor="#475569",
        borderpad=4,
    )
    figure.update_layout(
        height=295,
        margin={"l": 72, "r": 24, "t": 12, "b": 38},
        paper_bgcolor=background,
        plot_bgcolor=background,
        font={"family": FONT_FAMILY, "size": 13, "color": text},
        hoverlabel={"font": {"family": FONT_FAMILY, "size": 13}},
        showlegend=False,
        xaxis={
            "title": "横向坐标 x（米）",
            "gridcolor": grid,
            "zeroline": False,
            "fixedrange": False,
        },
        yaxis={
            "title": "距主通道方向 y（米）",
            "gridcolor": grid,
            "zeroline": False,
            "fixedrange": False,
        },
        uirevision=(
            f"d2-{view.layout.layout_id}-{view.state.value}"
            if isinstance(view, StaticLayoutView)
            else f"d3-{view.layout.layout_id}-{view.sequence_no}"
        ),
    )
    return figure


def figure_trace_summary(figure: go.Figure) -> MappingProxyType[str, int]:
    """Small deterministic diagnostic used by tests and documentation probes."""

    return MappingProxyType(
        {
            "trace_count": len(figure.data),
            "point_count": sum(len(trace.x or ()) for trace in figure.data),
        }
    )
