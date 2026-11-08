"""Tandem replay and trip-snapshot models for the web-v2 contract."""
from __future__ import annotations
from typing import Annotated, Literal
from pydantic import AwareDatetime, Field, model_validator
from parking_opt.api.models import ContractModel, Identifier, NonNegativeSeconds
from parking_opt.api.models_discovery import Coordinate
from parking_opt.api.models_journey import DriverTripEvent, DriverTripRecord, ReplanDecision
from parking_opt.api.models_recommend import Journey
from parking_opt.api.models_state import DriverRequest, ParkingFacilityStateSnapshot, Route
class DriverTandemDepartureRequest(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    expected_version: Annotated[int, Field(ge=1)]
    expected_state_version: Identifier
    idempotency_key: Identifier
class DriverTandemReplayLocation(ContractModel):
    kind: Literal["space", "buffer", "exit"]
    location_id: Identifier
    node_id: Identifier
    floor_id: Identifier
    coordinate: Coordinate
class DriverTandemReplayStep(ContractModel):
    sequence: Annotated[int, Field(ge=1)]
    action: Literal["relocate_to_buffer", "direct_exit", "restore_original"]
    actor_id: Identifier
    actor_role: Literal["driver", "blocker"]
    label: str = Field(min_length=1, max_length=100)
    from_location: DriverTandemReplayLocation
    to_location: DriverTandemReplayLocation
    route: Route
    starts_at_s: NonNegativeSeconds
    duration_s: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    @model_validator(mode="after")
    def verify_route_endpoints(self) -> DriverTandemReplayStep:
        if self.route.from_node_id != self.from_location.node_id:
            raise ValueError("tandem replay route starts at another location")
        if self.route.to_node_id != self.to_location.node_id:
            raise ValueError("tandem replay route ends at another location")
        return self
class DriverTandemDepartureReplay(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    replay_id: Identifier
    created_at: AwareDatetime
    journey_id: Identifier
    parking_lot_id: Identifier
    layout_version: Identifier
    scenario_version: Identifier
    state_version: Identifier
    cost_version: Identifier
    profile_id: Literal["tandem-focus"] = "tandem-focus"
    stack_group_id: Identifier
    target_space_id: Identifier
    blocker_vehicle_ids: tuple[Identifier, ...] = Field(min_length=1)
    buffer_ids: tuple[Identifier, ...] = Field(min_length=1)
    steps: tuple[DriverTandemReplayStep, ...] = Field(min_length=3)
    total_duration_s: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    before_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    after_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    facility_state: ParkingFacilityStateSnapshot
    final_journey: Journey
    @model_validator(mode="after")
    def verify_replay(self) -> DriverTandemDepartureReplay:
        if tuple(item.sequence for item in self.steps) != tuple(range(1, len(self.steps) + 1)):
            raise ValueError("tandem replay sequence must be contiguous")
        direct_indices = [index for index, item in enumerate(self.steps) if item.action == "direct_exit"]
        if len(direct_indices) != 1:
            raise ValueError("tandem replay requires exactly one direct exit")
        direct_index = direct_indices[0]
        if any(item.action != "relocate_to_buffer" for item in self.steps[:direct_index]):
            raise ValueError("tandem replay must move all blockers out before departure")
        if any(item.action != "restore_original" for item in self.steps[direct_index + 1 :]):
            raise ValueError("tandem replay must restore blockers after departure")
        blocker_count = direct_index
        if blocker_count < 1 or len(self.steps) != blocker_count * 2 + 1:
            raise ValueError("tandem replay blocker stages are incomplete")
        if len(self.blocker_vehicle_ids) != blocker_count or len(self.buffer_ids) != blocker_count:
            raise ValueError("tandem replay blocker and buffer counts differ")
        if self.steps[direct_index].actor_role != "driver":
            raise ValueError("tandem replay direct exit must belong to the driver")
        if any(item.actor_role != "blocker" for index, item in enumerate(self.steps) if index != direct_index):
            raise ValueError("tandem replay relocation stages must belong to blockers")
        elapsed = 0.0
        for item in self.steps:
            if abs(item.starts_at_s - elapsed) > 1e-6:
                raise ValueError("tandem replay stage timing must be contiguous")
            if item.route.parking_lot_id != self.parking_lot_id or item.route.layout_version != self.layout_version or item.route.cost_version != self.cost_version:
                raise ValueError("tandem replay route identity mismatch")
            elapsed += item.duration_s
        if abs(elapsed - self.total_duration_s) > 1e-6:
            raise ValueError("tandem replay total duration mismatch")
        if self.final_journey.journey_id != self.journey_id or self.final_journey.parking_lot_id != self.parking_lot_id or self.final_journey.state != "departed":
            raise ValueError("tandem replay final journey mismatch")
        if (self.facility_state.parking_lot_id != self.parking_lot_id or self.facility_state.layout_version != self.layout_version or self.facility_state.scenario_version != self.scenario_version or self.facility_state.state_version != self.state_version or self.facility_state.demo_profile is None or self.facility_state.demo_profile.profile_id != self.profile_id):
            raise ValueError("tandem replay facility state identity mismatch")
        return self
class DriverTandemArrivalRequest(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    expected_version: Annotated[int, Field(ge=1)]
    expected_state_version: Identifier
    idempotency_key: Identifier
class DriverTandemArrivalLocation(ContractModel):
    kind: Literal["space", "buffer", "approach"]
    location_id: Identifier
    node_id: Identifier
    floor_id: Identifier
    coordinate: Coordinate
class DriverTandemArrivalStep(ContractModel):
    sequence: Annotated[int, Field(ge=1)]
    action: Literal["relocate_to_buffer", "direct_entry", "restore_original"]
    actor_id: Identifier
    actor_role: Literal["driver", "blocker"]
    label: str = Field(min_length=1, max_length=100)
    from_location: DriverTandemArrivalLocation
    to_location: DriverTandemArrivalLocation
    route: Route
    starts_at_s: NonNegativeSeconds
    duration_s: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    @model_validator(mode="after")
    def verify_route_endpoints(self) -> DriverTandemArrivalStep:
        if self.route.from_node_id != self.from_location.node_id:
            raise ValueError("tandem arrival route starts at another location")
        if self.route.to_node_id != self.to_location.node_id:
            raise ValueError("tandem arrival route ends at another location")
        return self
class DriverTandemArrivalReplay(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    replay_id: Identifier
    created_at: AwareDatetime
    journey_id: Identifier
    parking_lot_id: Identifier
    layout_version: Identifier
    scenario_version: Identifier
    before_state_version: Identifier
    after_state_version: Identifier
    cost_version: Identifier
    profile_id: Literal["tandem-focus"] = "tandem-focus"
    stack_group_id: Identifier
    target_space_id: Identifier
    blocker_vehicle_ids: tuple[Identifier, ...] = Field(min_length=1)
    buffer_ids: tuple[Identifier, ...] = Field(min_length=1)
    steps: tuple[DriverTandemArrivalStep, ...] = Field(min_length=3)
    total_duration_s: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    before_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    after_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    before_facility_state: ParkingFacilityStateSnapshot
    after_facility_state: ParkingFacilityStateSnapshot
    final_journey: Journey
    @model_validator(mode="after")
    def verify_replay(self) -> DriverTandemArrivalReplay:
        if tuple(item.sequence for item in self.steps) != tuple(range(1, len(self.steps) + 1)):
            raise ValueError("tandem arrival sequence must be contiguous")
        direct_indices = [index for index, item in enumerate(self.steps) if item.action == "direct_entry"]
        if len(direct_indices) != 1:
            raise ValueError("tandem arrival requires exactly one direct entry")
        direct_index = direct_indices[0]
        if any(item.action != "relocate_to_buffer" for item in self.steps[:direct_index]):
            raise ValueError("tandem arrival must move all blockers out before entry")
        if any(item.action != "restore_original" for item in self.steps[direct_index + 1 :]):
            raise ValueError("tandem arrival must restore blockers after entry")
        blocker_count = direct_index
        if blocker_count < 1 or len(self.steps) != blocker_count * 2 + 1:
            raise ValueError("tandem arrival blocker stages are incomplete")
        if len(self.blocker_vehicle_ids) != blocker_count or len(self.buffer_ids) != blocker_count:
            raise ValueError("tandem arrival blocker and buffer counts differ")
        if self.steps[direct_index].actor_role != "driver":
            raise ValueError("tandem arrival direct entry must belong to the driver")
        if any(item.actor_role != "blocker" for index, item in enumerate(self.steps) if index != direct_index):
            raise ValueError("tandem arrival relocation stages must belong to blockers")
        elapsed = 0.0
        for item in self.steps:
            if abs(item.starts_at_s - elapsed) > 1e-6:
                raise ValueError("tandem arrival stage timing must be contiguous")
            if item.route.parking_lot_id != self.parking_lot_id or item.route.layout_version != self.layout_version or item.route.cost_version != self.cost_version:
                raise ValueError("tandem arrival route identity mismatch")
            elapsed += item.duration_s
        if abs(elapsed - self.total_duration_s) > 1e-6:
            raise ValueError("tandem arrival total duration mismatch")
        if self.final_journey.journey_id != self.journey_id or self.final_journey.parking_lot_id != self.parking_lot_id or self.final_journey.state != "occupied" or self.final_journey.space_id != self.target_space_id:
            raise ValueError("tandem arrival final journey mismatch")
        for state, version in ((self.before_facility_state, self.before_state_version), (self.after_facility_state, self.after_state_version)):
            if (state.parking_lot_id != self.parking_lot_id or state.layout_version != self.layout_version or state.scenario_version != self.scenario_version or state.state_version != version or state.demo_profile is None or state.demo_profile.profile_id != self.profile_id):
                raise ValueError("tandem arrival facility state identity mismatch")
        return self
