"""Authoritative synthetic tandem-arrival replay construction."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from parking_opt.api.models import (
    DriverDemoProfile,
    DriverTandemArrivalLocation,
    DriverTandemArrivalReplay,
    DriverTandemArrivalStep,
    FacilityBuffer,
    FacilityClaimStatus,
    FacilityObservationSource,
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


class TandemArrivalConflictError(ValueError):
    """The live journey or facility state cannot start this replay."""


class TandemArrivalUnavailableError(RuntimeError):
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
class TandemArrivalDraft:
    replay_id: str
    created_at: datetime
    journey_id: str
    parking_lot_id: str
    layout_version: str
    scenario_version: str
    cost_version: str
    stack_group_id: str
    target_space_id: str
    blocker_space_ids: tuple[str, ...]
    blocker_vehicle_ids: tuple[str, ...]
    buffer_ids: tuple[str, ...]
    steps: tuple[DriverTandemArrivalStep, ...]
    total_duration_s: float
    before_sha256: str
    before_facility_state: ParkingFacilityStateSnapshot
    coordination: TandemCoordinationRecord

    def finalize(
        self,
        *,
        after_facility_state: ParkingFacilityStateSnapshot,
        final_journey: Journey,
    ) -> DriverTandemArrivalReplay:
        after_sha256 = _sha256(
            {
                "facility_state": after_facility_state.model_dump(mode="json"),
                "journey": final_journey.model_dump(mode="json"),
                "blocker_spaces": self.blocker_space_ids,
                "buffers": self.buffer_ids,
            }
        )
        return DriverTandemArrivalReplay(
            replay_id=self.replay_id,
            created_at=self.created_at,
            journey_id=self.journey_id,
            parking_lot_id=self.parking_lot_id,
            layout_version=self.layout_version,
            scenario_version=self.scenario_version,
            before_state_version=self.before_facility_state.state_version,
            after_state_version=after_facility_state.state_version,
            cost_version=self.cost_version,
            stack_group_id=self.stack_group_id,
            target_space_id=self.target_space_id,
            blocker_vehicle_ids=self.blocker_vehicle_ids,
            buffer_ids=self.buffer_ids,
            steps=self.steps,
            total_duration_s=self.total_duration_s,
            before_sha256=self.before_sha256,
            after_sha256=after_sha256,
            before_facility_state=self.before_facility_state,
            after_facility_state=after_facility_state,
            final_journey=final_journey,
        )


def _space_location(space: FacilitySpace) -> DriverTandemArrivalLocation:
    return DriverTandemArrivalLocation(
        kind="space",
        location_id=space.space_id,
        node_id=space.access_node_id,
        floor_id=space.floor_id,
        coordinate=space.geometry.center,
    )


def _buffer_location(buffer: FacilityBuffer) -> DriverTandemArrivalLocation:
    return DriverTandemArrivalLocation(
        kind="buffer",
        location_id=buffer.buffer_id,
        node_id=buffer.access_node_id,
        floor_id=buffer.floor_id,
        coordinate=buffer.geometry.center,
    )


def _approach_location(
    target: FacilitySpace, layout: ParkingFacilityLayout
) -> DriverTandemArrivalLocation:
    node = next(
        (item for item in layout.nodes if item.node_id == target.access_node_id),
        None,
    )
    if node is None:
        raise TandemArrivalUnavailableError("tandem arrival access node is missing")
    return DriverTandemArrivalLocation(
        kind="approach",
        location_id=f"{target.space_id}:approach",
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
        raise TandemArrivalUnavailableError(str(exc)) from exc


def _step(
    *,
    sequence: int,
    action: str,
    actor_id: str,
    actor_role: str,
    label: str,
    from_location: DriverTandemArrivalLocation,
    to_location: DriverTandemArrivalLocation,
    route: Route,
    starts_at_s: float,
) -> DriverTandemArrivalStep:
    return DriverTandemArrivalStep(
        sequence=sequence,
        action=action,  # type: ignore[arg-type]
        actor_id=actor_id,
        actor_role=actor_role,  # type: ignore[arg-type]
        label=label,
        from_location=from_location,
        to_location=to_location,
        route=route,
        starts_at_s=starts_at_s,
        duration_s=max(3.0, min(5.0, float(route.dynamic_eta_s) * 0.2)),
    )


def _activate_blockers(
    *,
    state: ParkingFacilityStateSnapshot,
    blocker_space_ids: tuple[str, ...],
    identity_hash: str,
    created_at: datetime,
) -> ParkingFacilityStateSnapshot:
    blocker_ids = frozenset(blocker_space_ids)
    result = state.model_copy(
        update={
            "state_version": f"state-tandem-arrival-{identity_hash[:12]}",
            "observed_at": created_at,
            "spaces": tuple(
                item.model_copy(
                    update={
                        "observed_status": SpaceStatus.OCCUPIED,
                        "observation_source": FacilityObservationSource.SYNTHETIC_TRUTH,
                        "claim_status": FacilityClaimStatus.NONE,
                        "effective_status": SpaceStatus.OCCUPIED,
                        "assignable": False,
                        "reason_codes": ("TANDEM_COORDINATION_BLOCKER",),
                    }
                )
                if item.space_id in blocker_ids
                else item
                for item in state.spaces
            ),
        }
    )
    return result


def build_tandem_arrival_draft(
    *,
    journey: JourneyRecord,
    expected_state_version: str,
    profile: DriverDemoProfile,
    layout: ParkingFacilityLayout,
    state: ParkingFacilityStateSnapshot,
    bundle: ScenarioBundle,
    route_service: RouteCostService,
    created_at: datetime,
) -> TandemArrivalDraft:
    if journey.namespace is not SessionNamespace.DRIVER:
        raise TandemArrivalConflictError("tandem arrival requires a driver journey")
    if journey.state is not JourneyState.NAVIGATING or journey.space_id is None:
        raise TandemArrivalConflictError("tandem arrival requires a navigating journey")
    if profile.profile_id != "tandem-focus":
        raise TandemArrivalConflictError("tandem arrival requires the tandem-focus profile")
    if state.state_version != expected_state_version:
        raise TandemArrivalConflictError("tandem arrival facility state is stale")
    state.require_layout(layout)
    if (
        bundle.parking_lot.parking_lot_id != journey.parking_lot_id
        or layout.parking_lot_id != journey.parking_lot_id
        or bundle.layout.layout_version != layout.layout_version
        or state.scenario_id != journey.scenario_id
    ):
        raise TandemArrivalUnavailableError("tandem arrival resource identity mismatch")

    spaces = {item.space_id: item for item in layout.spaces}
    space_states = {item.space_id: item for item in state.spaces}
    target = spaces.get(journey.space_id)
    if target is None or target.stack_group_id is None or target.depth <= 1:
        raise TandemArrivalConflictError("journey target is not a deep tandem space")
    target_state = space_states[target.space_id]
    if target_state.claim_status is not FacilityClaimStatus.NAVIGATING:
        raise TandemArrivalConflictError("tandem arrival target is not claimed for navigation")
    group = next(
        (item for item in layout.tandem_groups if item.stack_group_id == target.stack_group_id),
        None,
    )
    if group is None or target.space_id not in group.space_ids_near_to_deep:
        raise TandemArrivalUnavailableError("tandem group declaration is missing")
    target_index = group.space_ids_near_to_deep.index(target.space_id)
    if target_index <= 0:
        raise TandemArrivalConflictError("journey target has no shallower blocker position")
    blocker_spaces = tuple(spaces[item] for item in group.space_ids_near_to_deep[:target_index])
    for blocker in blocker_spaces:
        blocker_state = space_states[blocker.space_id]
        if not (
            blocker_state.observed_status is SpaceStatus.UNAVAILABLE
            and blocker_state.claim_status is FacilityClaimStatus.NONE
            and "DEMO_TANDEM_OUTER_RESERVED" in blocker_state.reason_codes
        ):
            raise TandemArrivalConflictError(
                f"tandem arrival blocker {blocker.space_id} is not reserved for coordination"
            )

    buffers = {item.buffer_id: item for item in layout.buffers}
    buffer_states = {item.buffer_id: item for item in state.buffers}
    selected_buffers = tuple(buffers[item] for item in group.buffer_ids[: len(blocker_spaces)])
    if len(selected_buffers) != len(blocker_spaces):
        raise TandemArrivalConflictError("tandem arrival buffer capacity is insufficient")
    for buffer in selected_buffers:
        current = buffer_states.get(buffer.buffer_id)
        if current is None or current.status is not SpaceStatus.AVAILABLE:
            raise TandemArrivalConflictError(
                f"tandem arrival buffer {buffer.buffer_id} is unavailable"
            )

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
    blocker_vehicle_ids = tuple(f"blocker-{item.space_id}" for item in blocker_spaces)
    before_state = _activate_blockers(
        state=state,
        blocker_space_ids=tuple(item.space_id for item in blocker_spaces),
        identity_hash=identity_hash,
        created_at=created_at,
    ).require_layout(layout)

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

    blocker_space_ids = tuple(item.space_id for item in blocker_spaces)
    buffer_ids = tuple(item.buffer_id for item in selected_buffers)
    before_sha256 = _sha256(
        {
            **identity,
            "journey_state": journey.state.value,
            "facility_state": before_state.model_dump(mode="json"),
            "blocker_locations": blocker_space_ids,
            "buffer_owners": [None for _item in selected_buffers],
        }
    )
    coordination = TandemCoordinationRecord(
        session_id=journey.session_id,
        scenario_id=journey.scenario_id,
        parking_lot_id=journey.parking_lot_id,
        journey_id=journey.journey_id,
        stack_group_id=group.stack_group_id,
        target_space_id=target.space_id,
        blocker_space_ids=blocker_space_ids,
        blocker_vehicle_ids=blocker_vehicle_ids,
        buffer_ids=buffer_ids,
        created_at=created_at,
    )
    return TandemArrivalDraft(
        replay_id=f"tandem-arrival-{identity_hash[:20]}",
        created_at=created_at,
        journey_id=journey.journey_id,
        parking_lot_id=journey.parking_lot_id,
        layout_version=layout.layout_version,
        scenario_version=state.scenario_version,
        cost_version=bundle.cost_snapshot.cost_version,
        stack_group_id=group.stack_group_id,
        target_space_id=target.space_id,
        blocker_space_ids=blocker_space_ids,
        blocker_vehicle_ids=blocker_vehicle_ids,
        buffer_ids=buffer_ids,
        steps=tuple(steps),
        total_duration_s=elapsed,
        before_sha256=before_sha256,
        before_facility_state=before_state,
        coordination=coordination,
    )
