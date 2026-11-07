"""Build the ordered tandem-departure replay steps."""

from __future__ import annotations

from parking_opt.api.models import (
    DriverTandemReplayStep,
    FacilityExit,
    ParkingFacilityLayout,
    Route,
    ScenarioBundle,
)
from parking_opt.api.routing import RouteCostService
from parking_opt.api.services.tandem_departure import (
    _buffer_location,
    _exit_location,
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
    blocker_ids,
    target,
    selected_exit: FacilityExit,
    target_route: Route,
    journey: JourneyRecord,
    layout: ParkingFacilityLayout,
) -> tuple[tuple[DriverTandemReplayStep, ...], float]:
    steps: list[DriverTandemReplayStep] = []
    elapsed = 0.0
    for blocker, buffer, actor_id in zip(blocker_spaces, selected_buffers, blocker_ids, strict=True):
        step = _step(
            sequence=len(steps) + 1,
            action="relocate_to_buffer",
            actor_id=actor_id,
            actor_role="blocker",
            label=f"外侧车辆从 {blocker.space_id} 移至 {buffer.buffer_id}",
            from_location=_space_location(blocker),
            to_location=_buffer_location(buffer),
            route=_route(route_service, bundle, blocker.access_node_id, buffer.access_node_id),
            starts_at_s=elapsed,
        )
        steps.append(step)
        elapsed += step.duration_s

    target_step = _step(
        sequence=len(steps) + 1,
        action="direct_exit",
        actor_id=journey.journey_id,
        actor_role="driver",
        label=f"您的车辆从 {target.space_id} 驶向出口",
        from_location=_space_location(target),
        to_location=_exit_location(selected_exit, layout),
        route=target_route,
        starts_at_s=elapsed,
    )
    steps.append(target_step)
    elapsed += target_step.duration_s

    for blocker, buffer, actor_id in reversed(tuple(zip(blocker_spaces, selected_buffers, blocker_ids, strict=True))):
        step = _step(
            sequence=len(steps) + 1,
            action="restore_original",
            actor_id=actor_id,
            actor_role="blocker",
            label=f"外侧车辆返回 {blocker.space_id}",
            from_location=_buffer_location(buffer),
            to_location=_space_location(blocker),
            route=_route(route_service, bundle, buffer.access_node_id, blocker.access_node_id),
            starts_at_s=elapsed,
        )
        steps.append(step)
        elapsed += step.duration_s
    return tuple(steps), elapsed
