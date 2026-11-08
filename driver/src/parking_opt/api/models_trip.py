from __future__ import annotations
from typing import Annotated, Literal
from pydantic import AwareDatetime, model_validator
from parking_opt.api.models import ContractModel, Identifier
from parking_opt.api.models_journey import DriverTripEvent, DriverTripRecord, ReplanDecision
from parking_opt.api.models_recommend import Journey
from parking_opt.api.models_state import DriverRequest, Route
from parking_opt.api.models_tandem import DriverTandemArrivalReplay, DriverTandemDepartureReplay

class DriverTripSnapshot(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    observed_at: AwareDatetime
    journey: Journey | None = None
    driver: DriverRequest | None = None
    current_route: Route | None = None
    current_node_id: Identifier | None = None
    last_replan: ReplanDecision | None = None
    started_at: AwareDatetime | None = None
    parked_at: AwareDatetime | None = None
    ended_at: AwareDatetime | None = None
    recent_events: tuple[DriverTripEvent, ...] = ()
    recent_trips: tuple[DriverTripRecord, ...] = ()
    tandem_arrival_replay_enabled: bool = False
    tandem_arrival_replay: DriverTandemArrivalReplay | None = None
    tandem_departure_replay_enabled: bool = False
    tandem_departure_replay: DriverTandemDepartureReplay | None = None
    @model_validator(mode="after")
    def verify_trip(self) -> DriverTripSnapshot:
        if (self.journey is None) != (self.driver is None):
            raise ValueError("trip journey and driver must be both present or both absent")
        if self.journey is None:
            if any(item is not None for item in (self.current_route, self.current_node_id, self.last_replan, self.started_at, self.parked_at, self.ended_at, self.tandem_arrival_replay, self.tandem_departure_replay)) or self.recent_events or self.recent_trips:
                raise ValueError("empty trip cannot contain navigation or lifecycle data")
            return self
        assert self.driver is not None
        if self.journey.session_id != self.driver.session_id:
            raise ValueError("trip journey and driver belong to different sessions")
        if self.journey.parking_lot_id != self.driver.parking_lot_id:
            raise ValueError("trip journey and driver belong to different parking lots")
        if self.current_route is not None:
            if self.current_route.parking_lot_id != self.journey.parking_lot_id:
                raise ValueError("trip route belongs to another parking lot")
            if self.current_node_id is None:
                raise ValueError("trip route requires a current node")
        if self.last_replan is not None and self.current_route is None:
            raise ValueError("last replan requires a current route")
        if self.tandem_departure_replay is not None:
            if self.tandem_departure_replay.journey_id != self.journey.journey_id:
                raise ValueError("trip tandem replay belongs to another journey")
            if self.journey.state != "departed":
                raise ValueError("trip tandem replay requires a departed journey")
        if self.tandem_arrival_replay is not None:
            if self.tandem_arrival_replay.journey_id != self.journey.journey_id:
                raise ValueError("trip tandem arrival replay belongs to another journey")
            if self.journey.state not in {"occupied", "departed"}:
                raise ValueError("trip tandem arrival replay requires an occupied journey history")
        return self
