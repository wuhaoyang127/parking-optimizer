"""Authoritative synthetic tandem-arrival replay construction."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from parking_opt.api.models import (
    DriverTandemArrivalLocation,
    DriverTandemArrivalReplay,
    DriverTandemArrivalStep,
    FacilityBuffer,
    FacilitySpace,
    Journey,
    ParkingFacilityLayout,
    ParkingFacilityStateSnapshot,
    Route,
    ScenarioBundle,
)
from parking_opt.api.routing import RouteCostService, RouteNotFoundError
from parking_opt.api.sessions import TandemCoordinationRecord


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


from parking_opt.api.services.tandem_arrival_build import build_tandem_arrival_draft  # noqa: E402
