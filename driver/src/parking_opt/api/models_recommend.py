"""Recommendation and journey models for the web-v2 contract."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from parking_opt.api.models import (
    SCHEMA_VERSION,
    ContractModel,
    DataMode,
    DataSourceStatus,
    Identifier,
    NonNegativeMeters,
    NonNegativeSeconds,
)
from parking_opt.api.models_discovery import ParkingSpace, TandemGroup
from parking_opt.api.models_state import DriverDemoProfile, DriverRequest, Route


class CandidateAssessment(ContractModel):
    space_id: Identifier
    feasible: bool
    reason_codes: tuple[str, ...]
    recoverability_rank: Annotated[int, Field(ge=0)] | None = None
    dynamic_eta_s: NonNegativeSeconds | None = None
    distance_m: NonNegativeMeters | None = None
    depth: Annotated[int, Field(ge=1)]


class Recommendation(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    recommendation_id: Identifier
    request_id: Identifier
    parking_lot_id: Identifier
    algorithm_id: Identifier
    algorithm_version: Identifier
    data_source: DataSourceStatus
    solver_status: Literal["success", "no_feasible_space", "failed"]
    failure_code: Identifier | None = None
    recommended_space_id: Identifier | None = None
    alternative_space_ids: tuple[Identifier, ...] = ()
    assessments: tuple[CandidateAssessment, ...]
    route: Route | None = None
    explanation_codes: tuple[str, ...]
    degraded: bool = False
    degradation_reason: str | None = None
    claim_status: Literal["not_created_m2", "soft_held"] = "not_created_m2"
    soft_lock_expires_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def verify_success_payload(self) -> Recommendation:
        success = self.solver_status == "success"
        if success and (self.recommended_space_id is None or self.route is None):
            raise ValueError("successful recommendation requires a space and route")
        if not success and (self.recommended_space_id is not None or self.route is not None or self.alternative_space_ids):
            raise ValueError("non-success recommendation cannot contain spaces or a route")
        failed = self.solver_status == "failed"
        if failed != (self.failure_code is not None):
            raise ValueError("failed recommendation requires failure_code only")
        if self.data_source.parking_lot_id != self.parking_lot_id:
            raise ValueError("data source belongs to another parking lot")
        if self.route is not None and self.route.parking_lot_id != self.parking_lot_id:
            raise ValueError("route belongs to another parking lot")
        if self.degraded != (self.degradation_reason is not None):
            raise ValueError("degraded flag and degradation_reason must agree")
        if self.claim_status == "soft_held" and (not success or self.soft_lock_expires_at is None):
            raise ValueError("soft-held recommendation requires success and an expiry")
        if self.claim_status == "not_created_m2" and self.soft_lock_expires_at is not None:
            raise ValueError("unclaimed recommendation cannot contain a soft-lock expiry")
        return self


class Journey(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    journey_id: Identifier
    attempt_id: Identifier
    session_id: Identifier
    namespace: Literal["driver", "defense"]
    scenario_id: Identifier
    parking_lot_id: Identifier
    state: Literal["idle", "waiting", "soft_held", "session_reserved", "navigating", "occupied", "departed", "cancelled", "expired", "failed"]
    version: Annotated[int, Field(ge=1)]
    space_id: Identifier | None = None
    recommendation_id: Identifier | None = None
    updated_at: AwareDatetime
    expires_at: AwareDatetime | None = None
    terminal_reason: Identifier | None = None
    legal_operations: tuple[str, ...]


class JourneyRecommendationRequest(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    namespace: Literal["driver", "defense"] = "driver"
    scenario_id: Identifier
    journey_id: Identifier
    attempt_id: Identifier
    algorithm_id: Identifier = "online-rule-v2"
    idempotency_key: Identifier
    driver: DriverRequest


class JourneyRecommendationResponse(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    recommendation: Recommendation
    journey: Journey


class DriverEntrance(ContractModel):
    node_id: Identifier
    label: str = Field(min_length=1, max_length=80)


class DriverRecommendationContext(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    observed_at: AwareDatetime
    scenario_id: Identifier
    parking_lot_id: Identifier
    layout_version: Identifier
    entrances: tuple[DriverEntrance, ...] = Field(min_length=1)
    spaces: tuple[ParkingSpace, ...] = Field(min_length=1)
    tandem_groups: tuple[TandemGroup, ...] = ()
    data_source: DataSourceStatus
    demo_profile: DriverDemoProfile | None = None

    @model_validator(mode="after")
    def verify_context_scope(self) -> DriverRecommendationContext:
        if self.data_source.parking_lot_id != self.parking_lot_id:
            raise ValueError("driver context data source belongs to another parking lot")
        if self.demo_profile is not None and self.data_source.mode is not DataMode.SYNTHETIC:
            raise ValueError("driver demo profile requires a synthetic data source")
        if len({item.node_id for item in self.entrances}) != len(self.entrances):
            raise ValueError("driver context entrances must be unique")
        if any(item.parking_lot_id != self.parking_lot_id for item in self.spaces):
            raise ValueError("driver context spaces belong to another parking lot")
        space_ids = {item.space_id for item in self.spaces}
        if any(not set(item.space_ids_near_to_deep) <= space_ids for item in self.tandem_groups):
            raise ValueError("driver context tandem groups reference unknown spaces")
        return self


class DriverJourneySnapshot(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    observed_at: AwareDatetime
    journey: Journey | None = None
    recommendation: Recommendation | None = None
    driver: DriverRequest | None = None
    waiting_since: AwareDatetime | None = None

    @model_validator(mode="after")
    def verify_snapshot(self) -> DriverJourneySnapshot:
        present = (self.journey is not None, self.recommendation is not None, self.driver is not None)
        if any(present) and not all(present):
            raise ValueError("driver journey snapshot payloads must be all present or all absent")
        if self.journey is not None and self.driver is not None:
            if self.journey.session_id != self.driver.session_id:
                raise ValueError("journey and driver belong to different sessions")
            if self.journey.parking_lot_id != self.driver.parking_lot_id:
                raise ValueError("journey and driver belong to different parking lots")
        if self.journey is not None and self.recommendation is not None:
            if self.recommendation.parking_lot_id != self.journey.parking_lot_id:
                raise ValueError("journey and recommendation belong to different parking lots")
        if self.waiting_since is not None and (self.journey is None or self.journey.state != "waiting"):
            raise ValueError("waiting_since is only valid for a waiting journey")
        return self
