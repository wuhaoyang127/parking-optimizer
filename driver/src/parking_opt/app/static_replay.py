"""Replay-layout view projection for D3."""

from __future__ import annotations

from collections import Counter

from parking_opt.application.presentation import ReplayEventView, ReplayFrame
from parking_opt.app.static_layout import (
    POSITION_STATUS_SPECS,
    ReplayLayoutView,
    StaticPositionView,
    _validate_depth_order,
)
from parking_opt.layout.model import Layout


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
