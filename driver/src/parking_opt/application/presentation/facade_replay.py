"""Replay index and frame projection for the presentation facade."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from parking_opt.application.presentation.models import (
    ReplayActionView,
    ReplayFrame,
    ReplayIndex,
    ReplayPositionView,
    ReplayVehicleView,
    ValidatedDemoBundle,
)
from parking_opt.domain.enums import ActionStatus, LocationKind, ManualStatus
from parking_opt.domain.state import AuthoritativeState
from parking_opt.domain.transitions import apply_event


def build_replay_index(
    bundle: ValidatedDemoBundle,
    *,
    checkpoint_interval: int = 64,
) -> ReplayIndex:
    if checkpoint_interval < 1:
        raise ValueError("checkpoint_interval must be positive")
    checkpoints = [bundle._initial_state]
    state = bundle._initial_state
    for event in bundle._events:
        state = apply_event(state, event)
        if state.sequence_no % checkpoint_interval == 0:
            checkpoints.append(state)
    if checkpoints[-1].sequence_no != state.sequence_no:
        checkpoints.append(state)
    return ReplayIndex(
        run_id=bundle.run_id,
        scenario_id=bundle.scenario_id,
        first_sequence_no=0,
        last_sequence_no=len(bundle._events),
        checkpoint_interval=checkpoint_interval,
        _events=bundle._events,
        _checkpoints=tuple(checkpoints),
    )


def _frame_from_state(state: AuthoritativeState, event: Mapping[str, Any] | None) -> ReplayFrame:
    metadata = {item.position_id: item for item in state.position_metadata}
    blockers: dict[str, tuple[str, ...]] = {}
    for position in state.positions:
        item_metadata = metadata[position.position_id]
        if (
            item_metadata.stack_group_id is None
            or item_metadata.depth is None
            or position.occupant_vehicle_id is None
        ):
            blockers[position.position_id] = ()
            continue
        shallower = tuple(
            candidate.occupant_vehicle_id
            for candidate in state.positions
            if candidate.occupant_vehicle_id is not None
            and metadata[candidate.position_id].stack_group_id == item_metadata.stack_group_id
            and cast(int, metadata[candidate.position_id].depth) < item_metadata.depth
        )
        blockers[position.position_id] = shallower
    positions = tuple(
        ReplayPositionView(
            position_id=item.position_id,
            position_kind=item.position_kind.value,
            stack_group_id=metadata[item.position_id].stack_group_id,
            depth=metadata[item.position_id].depth,
            occupant_vehicle_id=item.occupant_vehicle_id,
            physically_available=item.physically_available,
            assignable=item.assignable,
            blocker_vehicle_ids=blockers[item.position_id],
        )
        for item in sorted(state.positions, key=lambda value: value.position_id)
    )
    vehicles = tuple(
        ReplayVehicleView(
            anonymous_vehicle_id=item.anonymous_vehicle_id,
            location_kind=item.location_state.kind.value,
            position_id=item.location_state.position_id,
            arrival_status=item.arrival_status.value,
            departure_status=item.departure_status.value,
            manual_status=item.manual_status.value,
        )
        for item in sorted(state.vehicles, key=lambda value: value.anonymous_vehicle_id)
    )
    warnings: list[str] = []
    if any(item.location_state.kind is LocationKind.POSITION_UNCERTAIN for item in state.vehicles):
        warnings.append("POSITION_UNKNOWN")
    if any(item.manual_status is not ManualStatus.NONE for item in state.vehicles):
        warnings.append("MANUAL_INTERVENTION")
    if any(item.status is ActionStatus.FAILED for item in state.actions):
        warnings.append("ACTION_FAILURE_RETAINED")
    active_actions = tuple(
        ReplayActionView(
            action_id=item.action_id,
            transaction_id=item.transaction_id,
            action_type=item.action_type.value,
            status=item.status.value,
            anonymous_vehicle_id=item.anonymous_vehicle_id,
            origin_position_id=item.origin_position_id,
            destination_position_id=item.destination_position_id,
            destination_exit_id=item.destination_exit_id,
            distance_m=item.distance_m,
            modeled_duration_s=item.modeled_duration_s,
            executor_units=item.executor_units,
            channel_zone_ids=item.channel_zone_ids,
            failure_reason=item.failure_reason,
        )
        for item in sorted(state.actions, key=lambda value: value.action_id)
        if item.status in {ActionStatus.ACCEPTED, ActionStatus.WAITING_FOR_RESOURCES, ActionStatus.STARTED}
    )
    return ReplayFrame(
        run_id=state.run_id,
        scenario_id=state.scenario_id,
        sequence_no=state.sequence_no,
        sim_time_s=state.sim_time_s,
        event_id=None if event is None else cast(str, event["event_id"]),
        event_type=None if event is None else cast(str, event["event_type"]),
        positions=positions,
        vehicles=vehicles,
        reserved_position_ids=tuple(sorted({item.position_id for item in state.reservations})),
        active_actions=active_actions,
        transaction_states=tuple(
            (item.transaction_id, item.status.value)
            for item in sorted(state.transactions, key=lambda value: value.transaction_id)
        ),
        reservation_count=len(state.reservations),
        active_action_count=len(active_actions),
        transaction_count=len(state.transactions),
        pending_request_count=len(state.pending_requests),
        executor_used=state.executor_resource.used,
        executor_capacity=state.executor_resource.capacity,
        channel_zone_usage=tuple(
            (item.channel_zone_id, item.used, item.capacity) for item in state.channel_zone_resources
        ),
        warnings=tuple(warnings),
    )


def frame_at(index: ReplayIndex, sequence_no: int) -> ReplayFrame:
    if not index.first_sequence_no <= sequence_no <= index.last_sequence_no:
        raise IndexError("sequence_no is outside the replay index")
    checkpoint = max(
        (item for item in index._checkpoints if item.sequence_no <= sequence_no),
        key=lambda item: item.sequence_no,
    )
    state = checkpoint
    for event in index._events[checkpoint.sequence_no : sequence_no]:
        state = apply_event(state, event)
    selected_event: Mapping[str, Any] | None = (
        None if sequence_no == 0 else index._events[sequence_no - 1]
    )
    return _frame_from_state(state, selected_event)
