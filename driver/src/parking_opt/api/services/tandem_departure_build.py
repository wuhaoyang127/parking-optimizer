"""Build the authoritative synthetic tandem-departure replay."""

from __future__ import annotations

from datetime import datetime

from parking_opt.api.models import (
    DriverDemoProfile,
    FacilityClaimStatus,
    FacilityExit,
    ParkingFacilityLayout,
    ParkingFacilityStateSnapshot,
    Route,
    ScenarioBundle,
    SpaceStatus,
)
from parking_opt.api.routing import RouteCostService
from parking_opt.api.services.tandem_departure import (
    TandemDepartureConflictError,
    TandemDepartureDraft,
    TandemDepartureUnavailableError,
    _route,
    _sha256,
)
from parking_opt.api.services.tandem_departure_steps import build_steps
from parking_opt.api.sessions import JourneyRecord, JourneyState, SessionNamespace, TandemCoordinationRecord


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
    group = next((item for item in layout.tandem_groups if item.stack_group_id == target.stack_group_id), None)
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
        raise TandemDepartureConflictError("tandem departure coordination identity mismatch")
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
    selected_buffer_ids = coordination.buffer_ids if coordination is not None else tuple(group.buffer_ids[: len(blocker_spaces)])
    missing_buffer_ids = tuple(buffer_id for buffer_id in selected_buffer_ids if buffer_id not in buffers)
    if missing_buffer_ids:
        raise TandemDepartureUnavailableError(
            "tandem departure coordination references missing buffers: " + ", ".join(missing_buffer_ids)
        )
    selected_buffers = tuple(buffers[item] for item in selected_buffer_ids)
    if len(selected_buffers) != len(blocker_spaces):
        raise TandemDepartureConflictError("tandem departure buffer capacity is insufficient")
    for buffer in selected_buffers:
        current = buffer_states.get(buffer.buffer_id)
        if current is None or current.status is not SpaceStatus.AVAILABLE:
            raise TandemDepartureConflictError(f"tandem departure buffer {buffer.buffer_id} is unavailable")

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
    steps, elapsed = build_steps(
        route_service=route_service,
        bundle=bundle,
        blocker_spaces=blocker_spaces,
        selected_buffers=selected_buffers,
        blocker_ids=blocker_ids,
        target=target,
        selected_exit=selected_exit,
        target_route=target_route,
        journey=journey,
        layout=layout,
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
        steps=steps,
        total_duration_s=elapsed,
        before_sha256=before_sha256,
        facility_state=state,
    )
