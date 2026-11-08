"""External occupancy, simulation, and algorithm models for the web-v2 contract."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, Field, model_validator

from parking_opt.api.models import (
    SCHEMA_VERSION,
    AlgorithmStatus,
    ContractModel,
    Identifier,
    ParkingLot,
    SpaceStatus,
)
from parking_opt.api.models_layout import Layout
from parking_opt.api.models_journey import JourneyCommandRequest
from parking_opt.api.models_recommend import Journey, JourneyRecommendationResponse
from parking_opt.api.models_state import CostSnapshot


class ExternalOccupancyRequest(JourneyCommandRequest):
    replacement_journey_id: Identifier
    replacement_attempt_id: Identifier
    replacement_request_id: Identifier


class ExternalOccupancyResponse(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    failed_journey: Journey
    replacement: JourneyRecommendationResponse


class SimulationEvent(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    parking_lot_id: Identifier
    sequence_no: Annotated[int, Field(ge=1)]
    simulation_time_s: Annotated[int, Field(ge=0)]
    wall_time: AwareDatetime
    event_type: Identifier
    subject_id: Identifier
    payload: dict[str, Any]
    before_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    after_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class SimulationCommandRequest(ContractModel):
    simulation_time_s: Annotated[int, Field(ge=0)]
    priority: int
    sequence_hint: Annotated[int, Field(ge=0)]
    event_type: Identifier
    vehicle_id: Identifier
    payload: dict[str, Any] = Field(default_factory=dict)


class SimulationSummaryResponse(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    vehicle_count: Annotated[int, Field(ge=0)]
    occupied_space_count: Annotated[int, Field(ge=0)]
    waiting_vehicle_count: Annotated[int, Field(ge=0)]
    relocation_count: Annotated[int, Field(ge=0)]
    failure_count: Annotated[int, Field(ge=0)]
    final_state_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class SimulationRunRequest(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    parking_lot_id: Identifier
    seed: Annotated[int, Field(ge=0)]
    wall_time_origin: AwareDatetime
    commands: tuple[SimulationCommandRequest, ...]


class SimulationReplayRequest(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    parking_lot_id: Identifier
    seed: Annotated[int, Field(ge=0)]
    wall_time_origin: AwareDatetime
    events: tuple[SimulationEvent, ...]


class SimulationRunResponse(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    seed: Annotated[int, Field(ge=0)]
    events: tuple[SimulationEvent, ...]
    summary: SimulationSummaryResponse


class AlgorithmDescriptor(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    algorithm_id: Identifier
    version: Identifier
    display_name: str = Field(min_length=1, max_length=80)
    category: Literal["rule", "metaheuristic", "machine_learning", "optimization"]
    status: AlgorithmStatus
    required_inputs: tuple[str, ...]
    pending_reason: str | None = None

    @model_validator(mode="after")
    def verify_status(self) -> AlgorithmDescriptor:
        if self.status is AlgorithmStatus.ONLINE and self.pending_reason is not None:
            raise ValueError("online algorithm cannot contain pending_reason")
        if self.status is AlgorithmStatus.PENDING and not self.pending_reason:
            raise ValueError("pending algorithm requires pending_reason")
        return self


class ScenarioBundle(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    scenario_id: Identifier
    seed: Annotated[int, Field(ge=0)]
    parking_lot: ParkingLot
    layout: Layout
    cost_snapshot: CostSnapshot

    @model_validator(mode="after")
    def verify_bundle_scope(self) -> ScenarioBundle:
        lot_id = self.parking_lot.parking_lot_id
        if self.layout.parking_lot_id != lot_id or self.cost_snapshot.parking_lot_id != lot_id:
            raise ValueError("scenario resources have different parking_lot_id values")
        if self.layout.layout_version != self.cost_snapshot.layout_version:
            raise ValueError("cost snapshot layout version mismatch")
        if self.parking_lot.total_spaces != len(self.layout.spaces):
            raise ValueError("parking lot total does not match layout")
        available = sum(item.status is SpaceStatus.AVAILABLE for item in self.layout.spaces)
        if self.parking_lot.available_spaces != available:
            raise ValueError("parking lot availability does not match layout")
        charging = sum(item.charging for item in self.layout.spaces)
        if self.parking_lot.charging_spaces != charging:
            raise ValueError("parking lot charging count does not match layout")
        return self
