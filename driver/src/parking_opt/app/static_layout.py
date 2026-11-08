# ruff: noqa: RUF001
"""Pure static-layout view models for D2."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from parking_opt.app.design import (
    POSITION_STATUS_SPECS,
    SCREENSHOT_STATE_SPECS,
    ScreenshotState,
)
from parking_opt.application.presentation import ReplayActionView
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

def _all_groups(layout: Layout) -> tuple[tuple[Slot, ...], ...]:
    grouped: dict[str, list[Slot]] = defaultdict(list)
    for slot in layout.slots:
        grouped[slot.stack_group_id].append(slot)
    return tuple(
        tuple(sorted(items, key=lambda item: item.depth)) for _, items in sorted(grouped.items())
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


from parking_opt.app.static_figure import (  # noqa: E402
    build_layout_figure,
    figure_trace_summary,
)
from parking_opt.app.static_render import _position_trace, _road_trace, _stack_connectors  # noqa: E402
from parking_opt.app.static_replay import build_replay_view  # noqa: E402
