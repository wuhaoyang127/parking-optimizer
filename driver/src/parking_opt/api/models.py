"""Pydantic source models for the frozen web-v2 transport contract."""
from __future__ import annotations
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
SCHEMA_VERSION: Literal["2.0.0"] = "2.0.0"
Identifier = Annotated[
    str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
]
VenueType = Literal["school", "hospital", "commercial", "transport_hub"]
NonNegativeSeconds = Annotated[float, Field(ge=0)]
NonNegativeMeters = Annotated[float, Field(ge=0)]
class ContractModel(BaseModel):
    """Immutable, fail-closed base for externally visible v2 values."""
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True, allow_inf_nan=False)
class DataMode(StrEnum):
    SYNTHETIC = "synthetic"
    REAL = "real"
class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
class SpaceStatus(StrEnum):
    AVAILABLE = "available"
    OCCUPIED = "occupied"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
class FacilitySourceKind(StrEnum):
    SYNTHETIC = "synthetic"
    IMPORTED = "imported"
    REAL = "real"
class FacilityObservationSource(StrEnum):
    SYNTHETIC_TRUTH = "synthetic_truth"
    OBSERVATION = "observation"
    USER_OVERRIDE = "user_override"
class FacilityClaimStatus(StrEnum):
    NONE = "none"
    SOFT_HELD = "soft_held"
    SESSION_RESERVED = "session_reserved"
    NAVIGATING = "navigating"
class AlgorithmStatus(StrEnum):
    ONLINE = "online"
    PENDING = "pending"
class DataSourceStatus(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    parking_lot_id: Identifier
    mode: DataMode
    health: HealthStatus
    source_name: str = Field(min_length=1, max_length=100)
    missing_fields: tuple[str, ...] = ()
    updated_at: AwareDatetime
    fail_reason: str | None = Field(default=None, max_length=300)
    @model_validator(mode="after")
    def require_failure_evidence(self) -> DataSourceStatus:
        if self.health is HealthStatus.HEALTHY and (self.missing_fields or self.fail_reason):
            raise ValueError("healthy data source cannot contain missing fields or fail_reason")
        if self.health is not HealthStatus.HEALTHY and not (self.missing_fields or self.fail_reason):
            raise ValueError("non-healthy data source requires missing_fields or fail_reason")
        return self
class PricingSummary(ContractModel):
    currency: Literal["CNY"] = "CNY"
    first_hour_yuan: Annotated[float, Field(ge=0)]
    additional_hour_yuan: Annotated[float, Field(ge=0)]
    daily_cap_yuan: Annotated[float, Field(ge=0)] | None = None
    note: str = Field(min_length=1, max_length=160)
class ParkingLot(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    parking_lot_id: Identifier
    name: str = Field(min_length=1, max_length=80)
    region_label: str = Field(min_length=1, max_length=80)
    venue_type: VenueType
    synthetic: bool
    opening_status: Literal["open", "closed", "unknown"]
    total_spaces: Annotated[int, Field(ge=1)]
    available_spaces: Annotated[int, Field(ge=0)]
    charging_spaces: Annotated[int, Field(ge=0)]
    pricing: PricingSummary
    updated_at: AwareDatetime
    data_source: DataSourceStatus
    @model_validator(mode="after")
    def verify_scope_and_counts(self) -> ParkingLot:
        if self.parking_lot_id != self.data_source.parking_lot_id:
            raise ValueError("parking lot and data source scopes differ")
        if self.available_spaces > self.total_spaces:
            raise ValueError("available_spaces cannot exceed total_spaces")
        if self.charging_spaces > self.total_spaces:
            raise ValueError("charging_spaces cannot exceed total_spaces")
        if self.synthetic != (self.data_source.mode is DataMode.SYNTHETIC):
            raise ValueError("synthetic flag must agree with data source mode")
        return self
from parking_opt.api.models_discovery import (  # noqa: E402
    BufferSpace,
    ChannelZone,
    Coordinate,
    DiscoveryArea,
    DiscoveryLotSummary,
    DiscoveryPosition,
    DiscoveryReferencePoint,
    OffsiteEstimate,
    ParkingSpace,
    RoadEdge,
    RoadNode,
    TandemGroup,
)
from parking_opt.api.models_facility import (  # noqa: E402
    FacilityBounds,
    FacilityBuffer,
    FacilityEdge,
    FacilityEntrance,
    FacilityExit,
    FacilityFloor,
    FacilityImageRegistration,
    FacilityInterFloorConnection,
    FacilityNode,
    FacilityProvenance,
    FacilityRectangle,
    FacilityRestrictedArea,
    FacilitySourceStatus,
    FacilitySpace,
    FacilityTandemGroup,
    FacilityZone,
)
from parking_opt.api.models_facility_layout import ParkingFacilityLayout  # noqa: E402
from parking_opt.api.models_state import (  # noqa: E402
    ChannelLoadSnapshot,
    CostSnapshot,
    DriverDemoProfile,
    DriverRequest,
    ErrorResponse,
    FacilityBufferState,
    FacilitySpaceState,
    HealthResponse,
    ParkingFacilityStateSnapshot,
    RecommendationRequest,
    Route,
    RouteInstruction,
    RoutePreviewRequest,
)
from parking_opt.api.models_route import RoutePreview  # noqa: E402
from parking_opt.api.models_recommend import (  # noqa: E402
    CandidateAssessment,
    DriverEntrance,
    DriverJourneySnapshot,
    DriverRecommendationContext,
    Journey,
    JourneyRecommendationRequest,
    JourneyRecommendationResponse,
    Recommendation,
)
from parking_opt.api.models_journey import (  # noqa: E402
    DriverDemoProfileAdvanceRequest,
    DriverDemoProfileAdvanceResponse,
    DriverDemoReplanRequest,
    DriverTripEvent,
    DriverTripRecord,
    JourneyAlternativeRequest,
    JourneyCommandRequest,
    JourneyConfirmRequest,
    JourneyDeclineRequest,
    JourneyDeclineResponse,
    JourneyReassignmentRequest,
    JourneyReassignmentResponse,
    JourneyReplanRequest,
    JourneyReplanResponse,
    ReplanDecision,
)
from parking_opt.api.models_tandem import (  # noqa: E402
    DriverTandemArrivalLocation,
    DriverTandemArrivalReplay,
    DriverTandemArrivalRequest,
    DriverTandemArrivalStep,
    DriverTandemDepartureReplay,
    DriverTandemDepartureRequest,
    DriverTandemReplayLocation,
    DriverTandemReplayStep,
)
from parking_opt.api.models_simulation import (  # noqa: E402
    AlgorithmDescriptor,
    ExternalOccupancyRequest,
    ExternalOccupancyResponse,
    ScenarioBundle,
    SimulationCommandRequest,
    SimulationEvent,
    SimulationReplayRequest,
    SimulationRunRequest,
    SimulationRunResponse,
    SimulationSummaryResponse,
)

from parking_opt.api.models_layout import Layout  # noqa: E402
from parking_opt.api.models_route import RoutePreview, RoutePreviewRequest  # noqa: E402
from parking_opt.api.models_trip import DriverTripSnapshot  # noqa: E402
from parking_opt.api.models_registry import SCHEMA_MODELS  # noqa: E402
