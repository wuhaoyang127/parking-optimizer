"""Journey command and trip-record models for the web-v2 contract."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from parking_opt.api.models import SCHEMA_VERSION, ContractModel, Identifier, NonNegativeSeconds, ParkingLot
from parking_opt.api.models_recommend import Journey, JourneyRecommendationResponse
from parking_opt.api.models_state import (
    ChannelLoadSnapshot,
    CostSnapshot,
    DriverDemoProfile,
    ParkingFacilityStateSnapshot,
    Route,
)


class DriverDemoProfileAdvanceRequest(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    expected_profile_id: Identifier
    expected_state_version: Identifier
    idempotency_key: Identifier


class DriverDemoProfileAdvanceResponse(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    demo_profile: DriverDemoProfile
    facility_state: ParkingFacilityStateSnapshot
    parking_lot: ParkingLot

    @model_validator(mode="after")
    def verify_scope(self) -> DriverDemoProfileAdvanceResponse:
        if self.facility_state.parking_lot_id != self.parking_lot.parking_lot_id:
            raise ValueError("demo profile response resources belong to different parking lots")
        if self.facility_state.demo_profile != self.demo_profile:
            raise ValueError("demo profile response metadata is inconsistent")
        return self


class JourneyCommandRequest(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    expected_version: Annotated[int, Field(ge=1)]
    idempotency_key: Identifier


class JourneyConfirmRequest(JourneyCommandRequest):
    accepted: bool


class JourneyAlternativeRequest(JourneyCommandRequest):
    space_id: Identifier


class JourneyDeclineRequest(JourneyCommandRequest):
    replacement_journey_id: Identifier
    replacement_attempt_id: Identifier
    replacement_request_id: Identifier


class JourneyDeclineResponse(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    declined_journey: Journey
    replacement: JourneyRecommendationResponse


class JourneyReassignmentRequest(JourneyCommandRequest):
    reason: Literal["unable_to_park", "eta_exceeds_reservation"]
    replacement_journey_id: Identifier
    replacement_attempt_id: Identifier
    replacement_request_id: Identifier


class JourneyReassignmentResponse(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    ended_journey: Journey
    replacement: JourneyRecommendationResponse


class JourneyReplanRequest(JourneyCommandRequest):
    current_node_id: Identifier
    trigger: Literal["deviation", "cost_update", "manual_refresh"]
    channel_load: ChannelLoadSnapshot


class DriverDemoReplanRequest(JourneyCommandRequest):
    action: Literal["simulate_deviation", "simulate_cost_update"]


class ReplanDecision(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    status: Literal["success", "warning", "failed"]
    trigger: Literal["deviation", "cost_update", "manual_refresh"]
    cost_snapshot: CostSnapshot
    previous_route: Route
    route: Route | None = None
    remaining_reservation_s: NonNegativeSeconds
    eta_with_safety_margin_s: NonNegativeSeconds | None = None
    reason_codes: tuple[Identifier, ...]


class JourneyReplanResponse(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    journey: Journey
    decision: ReplanDecision


class DriverTripEvent(ContractModel):
    sequence_no: Annotated[int, Field(ge=1)]
    event_type: Identifier
    reason_code: Identifier | None = None
    occurred_at: AwareDatetime


class DriverTripRecord(ContractModel):
    journey_id: Identifier
    parking_lot_id: Identifier
    space_id: Identifier | None = None
    state: Literal["occupied", "departed", "cancelled", "expired", "failed"]
    started_at: AwareDatetime | None = None
    parked_at: AwareDatetime | None = None
    ended_at: AwareDatetime | None = None
    terminal_reason: Identifier | None = None
