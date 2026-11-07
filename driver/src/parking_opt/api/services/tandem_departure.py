"""Authoritative synthetic tandem-departure replay construction."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from parking_opt.api.models import (
    DriverDemoProfile,
    DriverTandemDepartureReplay,
    DriverTandemReplayLocation,
    DriverTandemReplayStep,
    FacilityBuffer,
    FacilityClaimStatus,
    FacilityExit,
    FacilitySpace,
    Journey,
    ParkingFacilityLayout,
    ParkingFacilityStateSnapshot,
    Route,
    ScenarioBundle,
    SpaceStatus,
)
from parking_opt.api.routing import RouteCostService, RouteNotFoundError
from parking_opt.api.sessions import (
    JourneyRecord,
    JourneyState,
    SessionNamespace,
    TandemCoordinationRecord,
)


class TandemDepartureConflictError(ValueError):
    """The live journey or facility state cannot start this replay."""


class TandemDepartureUnavailableError(RuntimeError):
    """Required authoritative route or facility data is unavailable."""


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class TandemDepartureDraft:
    replay_id: str
    created_at: datetime
    journey_id: str
    parking_lot_id: str
    layout_version: str
    scenario_version: str
    state_version: str
    cost_version: str
    stack_group_id: str
    target_space_id: str
    blocker_vehicle_ids: tuple[str, ...]
    buffer_ids: tuple[str, ...]
    steps: tuple[DriverTandemReplayStep, ...]
    total_duration_s: float
    before_sha256: str
    facility_state: ParkingFacilityStateSnapshot

    def finalize(self, final_journey: Journey) -> DriverTandemDepartureReplay:
        after_sha256 = _sha256(
            {
                "facility_state": self.facility_state.model_dump(mode="json"),
                "journey": final_journey.model_dump(mode="json"),
                "blockers": list(zip(self.blocker_vehicle_ids, self.target_origins, strict=True)),
                "buffers": [],
            }
        )
        return DriverTandemDepartureReplay(
            replay_id=self.replay_id,
            created_at=self.created_at,
            journey_id=self.journey_id,
            parking_lot_id=self.parking_lot_id,
            layout_version=self.layout_version,
            scenario_version=self.scenario_version,
            state_version=self.state_version,
            cost_version=self.cost_version,
            stack_group_id=self.stack_group_id,
            target_space_id=self.target_space_id,
            blocker_vehicle_ids=self.blocker_vehicle_ids,
            buffer_ids=self.buffer_ids,
            steps=self.steps,
            total_duration_s=self.total_duration_s,
            before_sha256=self.before_sha256,
            after_sha256=after_sha256,
            facility_state=self.facility_state,
            final_journey=final_journey,
        )

    @property
    def target_origins(self) -> tuple[str, ...]:
        return tuple(
            item.from_location.location_id
            for item in self.steps
            if item.action == "relocate_to_buffer"
        )


def _space_location(space: FacilitySpace) -> DriverTandemReplayLocation:
    return DriverTandemReplayLocation(
        kind="space",
        location_id=space.space_id,
        node_id=space.access_node_id,
        floor_id=space.floor_id,
        coordinate=space.geometry.center,
    )


def _buffer_location(buffer: FacilityBuffer) -> DriverTandemReplayLocation:
    return DriverTandemReplayLocation(
        kind="buffer",
        location_id=buffer.buffer_id,
        node_id=buffer.access_node_id,
        floor_id=buffer.floor_id,
        coordinate=buffer.geometry.center,
    )


def _exit_location(
    exit_: FacilityExit, layout: ParkingFacilityLayout
) -> DriverTandemReplayLocation:
    node = next((item for item in layout.nodes if item.node_id == exit_.node_id), None)
    if node is None:
        raise TandemDepartureUnavailableError("tandem departure exit node is missing")
    return DriverTandemReplayLocation(
        kind="exit",
        location_id=exit_.exit_id,
        node_id=node.node_id,
        floor_id=node.floor_id,
        coordinate=node.coordinate,
    )


def _route(
    route_service: RouteCostService,
    bundle: ScenarioBundle,
    from_node_id: str,
    to_node_id: str,
) -> Route:
    try:
        return route_service.route(
            bundle.layout,
            bundle.cost_snapshot,
            from_node_id=from_node_id,
            to_node_id=to_node_id,
        )
    except RouteNotFoundError as exc:
        raise TandemDepartureUnavailableError(str(exc)) from exc


def _step(
    *,
    sequence: int,
    action: str,
    actor_id: str,
    actor_role: str,
    label: str,
    from_location: DriverTandemReplayLocation,
    to_location: DriverTandemReplayLocation,
    route: Route,
    starts_at_s: float,
) -> DriverTandemReplayStep:
    return DriverTandemReplayStep(
        sequence=sequence,
        action=action,  # type: ignore[arg-type]
        actor_id=actor_id,
        actor_role=actor_role,  # type: ignore[arg-type]
        label=label,
        from_location=from_location,
        to_location=to_location,
        route=route,
        starts_at_s=starts_at_s,
        # Keep the management replay observable without making a synthetic demo
        # wait for the route's real-world ETA. The authoritative route retains
        # its own ETA; this field controls replay pacing only.
        duration_s=max(2.0, min(5.0, float(route.dynamic_eta_s) * 0.2)),
    )


def build_tandem_departure_draft(
    *,
    journey: JourneyRecord,
    expected_state_version: str,
    profile: DriverDemoProfile,
    layout: ParkingFacilityLayout,
    state: ParkingFacilityStateSnapshot,
    bundle: ScenarioBundle,
    route_service: RouteCostService,
    created_at: datetime,
    coordination: TandemCoordinationRecord | None = None,
) -> TandemDepartureDraft:
    if journey.namespace is not SessionNamespace.DRIVER:
        raise TandemDepartureConflictError("tandem departure requires a driver journey")
    if journey.state is not JourneyState.OCCUPIED or journey.space_id is None:
        raise TandemDepartureConflictError("tandem departure requires an occupied journey")
    if profile.profile_id != "tandem-focus":
        raise TandemDepartureConflictError("tandem departure requires the tandem-focus profile")
    if state.state_version != expected_state_version:
        raise TandemDepartureConflictError("tandem departure facility state is stale")
    state.require_layout(layout)
    if (
        bundle.parking_lot.parking_lot_id != journey.parking_lot_id
        or layout.parking_lot_id != journey.parking_lot_id
        or bundle.layout.layout_version != layout.layout_version
        or state.scenario_id != journey.scenario_id
    ):
        raise TandemDepartureUnavailableError("tandem departure resource identity mismatch")

    spaces = {item.space_id: item for item in layout.spaces}
    space_states = {item.space_id: item for item in state.spaces}
    target = spaces.get(journey.space_id)
    if target is None or target.stack_group_id is None or target.depth <= 1:
        raise TandemDepartureConflictError("journey target is not a deep tandem space")
    group = next(
        (item for item in layout.tandem_groups if item.stack_group_id == target.stack_group_id),
        None,
    )
    if group is None or target.space_id not in group.space_ids_near_to_deep:
        raise TandemDepartureUnavailableError("tandem group declaration is missing")
    target_index = group.space_ids_near_to_deep.index(target.space_id)
    if target_index <= 0:
        raise TandemDepartureConflictError("journey target has no shallower blocker position")
    blocker_spaces = tuple(spaces[item] for item in group.space_ids_near_to_deep[:target_index])
    expected_blocker_space_ids = tuple(item.space_id for item in blocker_spaces)
    if coordination is not None and (
        coordination.session_id != journey.session_id
        or coordination.scenario_id != journey.scenario_id
        or coordination.parking_lot_id != journey.parking_lot_id
        or coordination.journey_id != journey.journey_id
        or coordination.stack_group_id != group.stack_group_id
        or coordination.target_space_id != target.space_id
        or coordination.blocker_space_ids != expected_blocker_space_ids
    ):
        raise TandemDepartureConflictError(
            "tandem departure coordination identity mismatch"
        )
    for blocker in blocker_spaces:
        blocker_state = space_states[blocker.space_id]
        reserved_demo_blocker = (
            blocker_state.observed_status is SpaceStatus.UNAVAILABLE
            and "DEMO_TANDEM_OUTER_RESERVED" in blocker_state.reason_codes
        )
        if blocker_state.claim_status is not FacilityClaimStatus.NONE or not (
            blocker_state.observed_status is SpaceStatus.OCCUPIED or reserved_demo_blocker
        ):
            raise TandemDepartureConflictError(
                f"tandem blocker {blocker.space_id} is not available for the authoritative replay"
            )

    buffers = {item.buffer_id: item for item in layout.buffers}
    buffer_states = {item.buffer_id: item for item in state.buffers}
    selected_buffer_ids = (
        coordination.buffer_ids
        if coordination is not None
        else tuple(group.buffer_ids[: len(blocker_spaces)])
    )
    missing_buffer_ids = tuple(
        buffer_id for buffer_id in selected_buffer_ids if buffer_id not in buffers
    )
    if missing_buffer_ids:
        raise TandemDepartureUnavailableError(
            "tandem departure coordination references missing buffers: "
            + ", ".join(missing_buffer_ids)
        )
    selected_buffers = tuple(buffers[item] for item in selected_buffer_ids)
    if len(selected_buffers) != len(blocker_spaces):
        raise TandemDepartureConflictError("tandem departure buffer capacity is insufficient")
    for buffer in selected_buffers:
        current = buffer_states.get(buffer.buffer_id)
        if current is None or current.status is not SpaceStatus.AVAILABLE:
            raise TandemDepartureConflictError(
                f"tandem departure buffer {buffer.buffer_id} is unavailable"
            )

    exit_options: list[tuple[float, str, FacilityExit, Route]] = []
    for exit_ in layout.exits:
        try:
            route = _route(route_service, bundle, target.access_node_id, exit_.node_id)
        except TandemDepartureUnavailableError:
            continue
        exit_options.append((float(route.dynamic_eta_s), exit_.exit_id, exit_, route))
    if not exit_options:
        raise TandemDepartureUnavailableError("no reachable exit for tandem departure")
    _eta, _exit_id, selected_exit, target_route = min(exit_options)

    blocker_ids = (
        coordination.blocker_vehicle_ids
        if coordination is not None
        else tuple(f"blocker-{item.space_id}" for item in blocker_spaces)
    )
    steps: list[DriverTandemReplayStep] = []
    elapsed = 0.0
    for blocker, buffer, actor_id in zip(
        blocker_spaces, selected_buffers, blocker_ids, strict=True
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

    for blocker, buffer, actor_id in reversed(
        tuple(zip(blocker_spaces, selected_buffers, blocker_ids, strict=True))
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

    identity = {
        "journey_id": journey.journey_id,
        "journey_version": journey.version,
        "state_version": state.state_version,
        "profile_id": profile.profile_id,
        "stack_group_id": group.stack_group_id,
        "target_space_id": target.space_id,
        "blockers": [item.space_id for item in blocker_spaces],
        "buffers": [item.buffer_id for item in selected_buffers],
        "cost_version": bundle.cost_snapshot.cost_version,
    }
    identity_hash = _sha256(identity)
    before_sha256 = _sha256(
        {
            **identity,
            "journey_state": journey.state.value,
            "facility_state": state.model_dump(mode="json"),
            "blocker_locations": [item.space_id for item in blocker_spaces],
            "buffer_owners": [None for _item in selected_buffers],
        }
    )
    return TandemDepartureDraft(
        replay_id=f"tandem-replay-{identity_hash[:20]}",
        created_at=created_at,
        journey_id=journey.journey_id,
        parking_lot_id=journey.parking_lot_id,
        layout_version=layout.layout_version,
        scenario_version=state.scenario_version,
        state_version=state.state_version,
        cost_version=bundle.cost_snapshot.cost_version,
        stack_group_id=group.stack_group_id,
        target_space_id=target.space_id,
        blocker_vehicle_ids=blocker_ids,
        buffer_ids=tuple(item.buffer_id for item in selected_buffers),
        steps=tuple(steps),
        total_duration_s=elapsed,
        before_sha256=before_sha256,
        facility_state=state,
    )
