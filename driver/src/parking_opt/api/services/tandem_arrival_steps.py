"""Build the ordered tandem-arrival replay steps."""

from __future__ import annotations

from parking_opt.api.models import DriverTandemArrivalStep, ScenarioBundle
from parking_opt.api.routing import RouteCostService
from parking_opt.api.services.tandem_arrival import (
    _approach_location,
    _buffer_location,
    _route,
    _space_location,
    _step,
)
from parking_opt.api.sessions import JourneyRecord


def build_steps(
    *,
    route_service: RouteCostService,
    bundle: ScenarioBundle,
    blocker_spaces,
    selected_buffers,
    blocker_vehicle_ids,
    target,
    layout,
    journey: JourneyRecord,
) -> tuple[tuple[DriverTandemArrivalStep, ...], float]:
    steps: list[DriverTandemArrivalStep] = []
    elapsed = 0.0
    for blocker, buffer, actor_id in zip(
        blocker_spaces, selected_buffers, blocker_vehicle_ids, strict=True
    ):
        origin = _space_location(blocker)
        destination = _buffer_location(buffer)
        route = _route(route_service, bundle, origin.node_id, destination.node_id)
        step = _step(
            sequence=len(steps) + 1,
            action="relocate_to_buffer",
            actor_id=actor_id,
            actor_role="blocker",
            label=f"外侧车辆从 {blocker.space_id} 移至 {buffer.buffer_id}",
            from_location=origin,
            to_location=destination,
            route=route,
            starts_at_s=elapsed,
        )
        steps.append(step)
        elapsed += step.duration_s

    approach = _approach_location(target, layout)
    target_location = _space_location(target)
    entry_route = _route(
        route_service,
        bundle,
        approach.node_id,
        target_location.node_id,
    )
    entry_step = _step(
        sequence=len(steps) + 1,
        action="direct_entry",
        actor_id=journey.journey_id,
        actor_role="driver",
        label=f"您的车辆驶入 {target.space_id}",
        from_location=approach,
        to_location=target_location,
        route=entry_route,
        starts_at_s=elapsed,
    )
    steps.append(entry_step)
    elapsed += entry_step.duration_s

    for blocker, buffer, actor_id in reversed(
        tuple(zip(blocker_spaces, selected_buffers, blocker_vehicle_ids, strict=True))
    ):
        origin = _buffer_location(buffer)
        destination = _space_location(blocker)
        route = _route(route_service, bundle, origin.node_id, destination.node_id)
        step = _step(
            sequence=len(steps) + 1,
            action="restore_original",
            actor_id=actor_id,
            actor_role="blocker",
            label=f"外侧车辆返回 {blocker.space_id}",
            from_location=origin,
            to_location=destination,
            route=route,
            starts_at_s=elapsed,
        )
        steps.append(step)
        elapsed += step.duration_s
    return tuple(steps), elapsed
