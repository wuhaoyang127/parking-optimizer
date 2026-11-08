"""Build the authoritative synthetic tandem-arrival replay."""

from __future__ import annotations

from datetime import datetime

from parking_opt.api.models import (
    DriverDemoProfile,
    FacilityClaimStatus,
    FacilityObservationSource,
    ParkingFacilityLayout,
    ParkingFacilityStateSnapshot,
    ScenarioBundle,
    SpaceStatus,
)
from parking_opt.api.routing import RouteCostService
from parking_opt.api.services.tandem_arrival import (
    TandemArrivalConflictError,
    TandemArrivalDraft,
    TandemArrivalUnavailableError,
    _sha256,
)
from parking_opt.api.services.tandem_arrival_steps import build_steps
from parking_opt.api.sessions import (
    JourneyRecord,
    JourneyState,
    SessionNamespace,
    TandemCoordinationRecord,
)


def _activate_blockers(
    *,
    state: ParkingFacilityStateSnapshot,
    blocker_space_ids: tuple[str, ...],
    identity_hash: str,
    created_at: datetime,
) -> ParkingFacilityStateSnapshot:
    blocker_ids = frozenset(blocker_space_ids)
    return state.model_copy(
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
    steps, elapsed = build_steps(
        route_service=route_service,
        bundle=bundle,
        blocker_spaces=blocker_spaces,
        selected_buffers=selected_buffers,
        blocker_vehicle_ids=blocker_vehicle_ids,
        target=target,
        layout=layout,
        journey=journey,
    )

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
        steps=steps,
        total_duration_s=elapsed,
        before_sha256=before_sha256,
        before_facility_state=before_state,
        coordination=coordination,
    )
