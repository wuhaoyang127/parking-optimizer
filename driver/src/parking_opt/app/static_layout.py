# ruff: noqa: RUF001
"""Pure static-layout view models and Plotly rendering for D2."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from types import MappingProxyType

import plotly.graph_objects as go  # type: ignore[import-untyped]

from parking_opt.app.design import (
    FONT_FAMILY,
    POSITION_STATUS_SPECS,
    SCREENSHOT_STATE_SPECS,
    ScreenshotState,
)
from parking_opt.application.presentation import (
    ReplayActionView,
    ReplayEventView,
    ReplayFrame,
)
from parking_opt.layout.model import Layout, Slot


@dataclass(frozen=True, slots=True)
class StaticPositionView:
    position_id: str
    position_kind: str
    x_m: float
    y_m: float
    stack_group_id: str | None
    depth: int | None
    channel_zone_ids: tuple[str, ...]
    status: str
    anonymous_vehicle_id: str | None


@dataclass(frozen=True, slots=True)
class StaticLayoutView:
    layout: Layout
    state: ScreenshotState
    positions: tuple[StaticPositionView, ...]
    status_counts: tuple[tuple[str, int], ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReplayLayoutView:
    """Layout projection for one confirmed event-log prefix."""

    layout: Layout
    sequence_no: int
    positions: tuple[StaticPositionView, ...]
    status_counts: tuple[tuple[str, int], ...]
    warnings: tuple[str, ...]
    action_overlays: tuple[ReplayActionView, ...]


def parse_screenshot_state(value: str) -> ScreenshotState:
    """Fail closed on unsupported externally supplied state names."""

    try:
        return ScreenshotState(value)
    except ValueError as exc:
        raise ValueError("unsupported D2 screenshot state") from exc


def _validate_depth_order(layout: Layout) -> None:
    groups: dict[str, list[int]] = defaultdict(list)
    for slot in layout.slots:
        if slot.depth < 1:
            raise ValueError(f"slot {slot.position_id} has invalid depth")
        groups[slot.stack_group_id].append(slot.depth)
    for group_id, depths in groups.items():
        ordered = sorted(depths)
        if ordered != list(range(1, len(ordered) + 1)):
            raise ValueError(f"stack group {group_id} depth sequence is not contiguous from one")


def _tandem_groups(layout: Layout) -> tuple[tuple[Slot, ...], ...]:
    grouped: dict[str, list[Slot]] = defaultdict(list)
    for slot in layout.slots:
        grouped[slot.stack_group_id].append(slot)
    return tuple(
        tuple(sorted(items, key=lambda item: item.depth))
        for _, items in sorted(grouped.items())
        if len(items) > 1
    )


def _state_assignments(
    layout: Layout,
    state: ScreenshotState,
) -> tuple[dict[str, str], dict[str, str]]:
    slots = sorted(layout.slots, key=lambda item: item.position_id)
    buffers = sorted(layout.buffer_slots, key=lambda item: item.position_id)
    tandem = _tandem_groups(layout)
    status: dict[str, str] = {item.position_id: "free" for item in slots}
    status.update({item.position_id: "free" for item in buffers})
    vehicles: dict[str, str] = {}

    def mark(position_id: str, position_status: str, vehicle_number: int | None = None) -> None:
        status[position_id] = position_status
        if vehicle_number is not None:
            vehicles[position_id] = f"vehicle-{vehicle_number:03d}"

    if state is ScreenshotState.INDEPENDENT_NORMAL:
        if any(group[0].depth != 1 or len(group) != 1 for group in _all_groups(layout)):
            raise ValueError("independent state requires only one-deep groups")
        mark(slots[0].position_id, "occupied", 1)
        mark(slots[1].position_id, "reserved")
        mark(slots[2].position_id, "locked")
    else:
        if len(tandem) < 3 or not buffers:
            raise ValueError("mixed-depth states require tandem groups and a buffer")
        first, second, third = tandem[:3]
        if state is ScreenshotState.MIXED_BLOCKED:
            mark(first[0].position_id, "occupied", 1)
            mark(first[1].position_id, "blocked", 2)
            mark(second[1].position_id, "reserved")
        elif state is ScreenshotState.RELOCATION:
            mark(first[1].position_id, "occupied", 2)
            mark(first[0].position_id, "moving", 1)
            mark(buffers[0].position_id, "moving", 1)
        elif state is ScreenshotState.RESOURCE_WAIT:
            mark(first[0].position_id, "occupied", 1)
            mark(first[1].position_id, "blocked", 2)
            mark(second[0].position_id, "locked")
            mark(buffers[0].position_id, "unavailable")
        elif state is ScreenshotState.FAILURE_UNKNOWN:
            mark(first[0].position_id, "unknown")
            mark(first[1].position_id, "blocked", 2)
            mark(second[0].position_id, "unavailable")
            mark(buffers[0].position_id, "locked")
        elif state is ScreenshotState.INSUFFICIENT_EVIDENCE:
            mark(first[0].position_id, "occupied", 1)
            mark(second[1].position_id, "reserved")
            mark(third[0].position_id, "unknown")
        else:  # pragma: no cover - Enum exhaustiveness guard
            raise ValueError("unsupported D2 screenshot state")
    return status, vehicles


def _all_groups(layout: Layout) -> tuple[tuple[Slot, ...], ...]:
    grouped: dict[str, list[Slot]] = defaultdict(list)
    for slot in layout.slots:
        grouped[slot.stack_group_id].append(slot)
    return tuple(
        tuple(sorted(items, key=lambda item: item.depth)) for _, items in sorted(grouped.items())
    )


def build_static_view(layout: Layout, state: ScreenshotState) -> StaticLayoutView:
    """Build a deterministic, immutable D2 view without invoking simulation logic."""

    if not isinstance(layout, Layout):
        raise TypeError("layout must be the frozen Layout value")
    if not layout.slots or not layout.road_nodes:
        raise ValueError("layout must contain road nodes and normal slots")
    _validate_depth_order(layout)
    position_ids = [
        *(item.position_id for item in layout.slots),
        *(item.position_id for item in layout.buffer_slots),
    ]
    if len(position_ids) != len(set(position_ids)):
        raise ValueError("layout position IDs must be unique")

    statuses, vehicles = _state_assignments(layout, state)
    positions = tuple(
        [
            StaticPositionView(
                item.position_id,
                "normal",
                item.x_m,
                item.y_m,
                item.stack_group_id,
                item.depth,
                item.channel_zone_ids,
                statuses[item.position_id],
                vehicles.get(item.position_id),
            )
            for item in layout.slots
        ]
        + [
            StaticPositionView(
                item.position_id,
                "buffer",
                item.x_m,
                item.y_m,
                None,
                None,
                item.channel_zone_ids,
                statuses[item.position_id],
                vehicles.get(item.position_id),
            )
            for item in layout.buffer_slots
        ]
    )
    counts = Counter(item.status for item in positions)
    spec = SCREENSHOT_STATE_SPECS[state]
    warnings = (spec.note,) if state is not ScreenshotState.INDEPENDENT_NORMAL else ()
    return StaticLayoutView(
        layout=layout,
        state=state,
        positions=positions,
        status_counts=tuple((status, counts.get(status, 0)) for status in POSITION_STATUS_SPECS),
        warnings=warnings,
    )


def build_replay_view(
    layout: Layout,
    frame: ReplayFrame,
    event: ReplayEventView | None,
) -> ReplayLayoutView:
    """Project only confirmed frame state plus saved discrete action context."""

    if not isinstance(layout, Layout) or not isinstance(frame, ReplayFrame):
        raise TypeError("layout and frame must be frozen presentation values")
    _validate_depth_order(layout)
    frame_positions = {item.position_id: item for item in frame.positions}
    active_actions = frame.active_actions
    moving_ids = {
        position_id
        for action in active_actions
        if action.status == "STARTED"
        for position_id in (action.origin_position_id, action.destination_position_id)
        if position_id is not None
    }
    waiting_ids = {
        action.destination_position_id
        for action in active_actions
        if action.status in {"ACCEPTED", "WAITING_FOR_RESOURCES"}
        and action.destination_position_id is not None
    }
    uncertain_vehicle_ids = {
        item.anonymous_vehicle_id
        for item in frame.vehicles
        if item.location_kind == "POSITION_UNCERTAIN"
    }
    unknown_ids = {
        position_id
        for action in (
            (() if event is None or event.action is None else (event.action,)) + active_actions
        )
        if action.anonymous_vehicle_id in uncertain_vehicle_ids
        for position_id in (action.origin_position_id, action.destination_position_id)
        if position_id is not None
    }

    def status_for(position_id: str) -> str:
        item = frame_positions[position_id]
        if position_id in unknown_ids:
            return "unknown"
        if position_id in moving_ids:
            return "moving"
        if not item.physically_available:
            return "unavailable"
        if position_id in waiting_ids or position_id in frame.reserved_position_ids:
            return "reserved"
        if not item.assignable:
            return "locked"
        if item.occupant_vehicle_id is not None and item.blocker_vehicle_ids:
            return "blocked"
        if item.occupant_vehicle_id is not None:
            return "occupied"
        return "free"

    positions = tuple(
        [
            StaticPositionView(
                item.position_id,
                "normal",
                item.x_m,
                item.y_m,
                item.stack_group_id,
                item.depth,
                item.channel_zone_ids,
                status_for(item.position_id),
                frame_positions[item.position_id].occupant_vehicle_id,
            )
            for item in layout.slots
        ]
        + [
            StaticPositionView(
                item.position_id,
                "buffer",
                item.x_m,
                item.y_m,
                None,
                None,
                item.channel_zone_ids,
                status_for(item.position_id),
                frame_positions[item.position_id].occupant_vehicle_id,
            )
            for item in layout.buffer_slots
        ]
    )
    counts = Counter(item.status for item in positions)
    if event is not None and event.transaction_id is not None:
        overlays = tuple(
            item
            for item in active_actions
            if item.transaction_id == event.transaction_id
            and item.status in {"WAITING_FOR_RESOURCES", "STARTED"}
        )
    elif event is not None and event.action is not None:
        overlays = tuple(
            item for item in active_actions if item.action_id == event.action.action_id
        )
    else:
        overlays = ()
    if event is not None and event.action is not None and event.action not in overlays:
        overlays = (*overlays, event.action)
    return ReplayLayoutView(
        layout=layout,
        sequence_no=frame.sequence_no,
        positions=positions,
        status_counts=tuple((status, counts.get(status, 0)) for status in POSITION_STATUS_SPECS),
        warnings=tuple(dict.fromkeys((*frame.warnings, *(event.warning_codes if event else ())))),
        action_overlays=overlays,
    )


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
