# ruff: noqa: RUF001
"""Plotly views for the synthetic online-rule teaching sandbox."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from math import hypot
from types import MappingProxyType

import plotly.graph_objects as go  # type: ignore[import-untyped]

from parking_opt.application.sandbox import CandidateExplanation, SandboxDecision
from parking_opt.layout.model import Layout

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
        x=x, y=y, mode="lines", line={"color": "#94A3B8", "width": 7},
        hoverinfo="skip", showlegend=False, name="通道路网",
    )
    connector_x: list[float | None] = []
    connector_y: list[float | None] = []
    for slot in layout.slots:
        access = nodes[slot.access_node_id]
        connector_x.extend((access.x_m, slot.x_m, None))
        connector_y.extend((access.y_m, slot.y_m, None))
    connector = go.Scatter(
        x=connector_x, y=connector_y, mode="lines",
        line={"color": "#CBD5E1", "width": 1.5, "dash": "dot"},
        hoverinfo="skip", showlegend=False, name="车位连接",
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


from parking_opt.app.sandbox_figure import build_sandbox_figure  # noqa: E402

__all__ = [
    "REASON_LABELS",
    "SandboxFigureSummary",
    "build_sandbox_figure",
    "candidate_reason_text",
    "candidate_rows",
]
