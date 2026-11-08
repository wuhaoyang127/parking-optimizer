"""Plotly road, stack, and position traces for static layouts."""

from __future__ import annotations

import plotly.graph_objects as go  # type: ignore[import-untyped]

from parking_opt.app.design import POSITION_STATUS_SPECS
from parking_opt.app.static_layout import (
    ReplayLayoutView,
    StaticLayoutView,
    _all_groups,
)
from parking_opt.layout.model import Layout


def _road_trace(layout: Layout) -> go.Scatter:
    nodes = {item.road_node_id: item for item in layout.road_nodes}
    x: list[float | None] = []
    y: list[float | None] = []
    for edge in layout.road_edges:
        start = nodes[edge.from_node_id]
        end = nodes[edge.to_node_id]
        x.extend((start.x_m, end.x_m, None))
        y.extend((start.y_m, end.y_m, None))
    return go.Scatter(
        x=x,
        y=y,
        mode="lines",
        line={"color": "#64748B", "width": 5},
        hoverinfo="skip",
        name="道路 / 通道区",
        legendgroup="infrastructure",
        showlegend=False,
    )


def _stack_connectors(layout: Layout) -> go.Scatter:
    nodes = {item.road_node_id: item for item in layout.road_nodes}
    x: list[float | None] = []
    y: list[float | None] = []
    for group in _all_groups(layout):
        if len(group) < 2:
            continue
        access = nodes[group[0].access_node_id]
        x.extend((access.x_m, *(item.x_m for item in group), None))
        y.extend((access.y_m, *(item.y_m for item in group), None))
    return go.Scatter(
        x=x,
        y=y,
        mode="lines",
        line={"color": "#94A3B8", "width": 1.5, "dash": "dot"},
        hoverinfo="skip",
        name="纵深组连接",
        legendgroup="infrastructure",
        showlegend=False,
    )


def _position_trace(view: StaticLayoutView | ReplayLayoutView, status: str) -> go.Scatter:
    spec = POSITION_STATUS_SPECS[status]
    points = [item for item in view.positions if item.status == status]
    if points:
        x_values: list[float | None] = [item.x_m for item in points]
        y_values: list[float | None] = [item.y_m for item in points]
        marker_sizes: list[int] = [15 if item.position_kind == "buffer" else 10 for item in points]
        customdata = [
            [
                item.position_id,
                "缓冲位" if item.position_kind == "buffer" else "普通位",
                item.stack_group_id or "—",
                item.depth if item.depth is not None else "—",
                spec.label,
                item.anonymous_vehicle_id or "—",
                "、".join(item.channel_zone_ids) or "—",
            ]
            for item in points
        ]
    else:
        x_values = [None]
        y_values = [None]
        marker_sizes = [10]
        customdata = [["—", "—", "—", "—", spec.label, "—", "—"]]
    return go.Scatter(
        x=x_values,
        y=y_values,
        mode="markers",
        marker={
            "size": marker_sizes,
            "color": spec.color,
            "symbol": spec.symbol,
            "line": {"color": spec.border, "width": 2},
        },
        customdata=customdata,
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>"
            "类型：%{customdata[1]}<br>"
            "纵深组：%{customdata[2]}<br>"
            "depth：%{customdata[3]}<br>"
            "状态：%{customdata[4]}<br>"
            "匿名车辆：%{customdata[5]}<br>"
            "通道区：%{customdata[6]}<extra></extra>"
        ),
        name=f"{spec.glyph} {spec.label}",
    )
