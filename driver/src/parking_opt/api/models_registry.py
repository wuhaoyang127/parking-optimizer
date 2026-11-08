"""Registry mapping schema names to their frozen contract models."""

from __future__ import annotations

from parking_opt.api.models import ContractModel, DataSourceStatus, ParkingLot
from parking_opt.api.models_discovery import DiscoveryArea, ParkingSpace
from parking_opt.api.models_layout import Layout
from parking_opt.api.models_facility import (
    FacilitySourceStatus,
)
from parking_opt.api.models_facility_layout import ParkingFacilityLayout
from parking_opt.api.models_state import (
    ChannelLoadSnapshot,
    CostSnapshot,
    DriverDemoProfile,
    DriverRequest,
    ErrorResponse,
    HealthResponse,
    ParkingFacilityStateSnapshot,
    RecommendationRequest,
    Route,
    RoutePreviewRequest,
)
from parking_opt.api.models_route import RoutePreview
from parking_opt.api.models_journey import (
    DriverDemoProfileAdvanceRequest,
    DriverDemoProfileAdvanceResponse,
)
from parking_opt.api.models_recommend import (
    DriverEntrance,
    DriverJourneySnapshot,
    DriverRecommendationContext,
    Journey,
    JourneyRecommendationRequest,
    JourneyRecommendationResponse,
    Recommendation,
)
from parking_opt.api.models_journey import (
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
from parking_opt.api.models_tandem import (
    DriverTandemArrivalReplay,
    DriverTandemArrivalRequest,
    DriverTandemDepartureReplay,
    DriverTandemDepartureRequest,
)
from parking_opt.api.models_trip import DriverTripSnapshot
from parking_opt.api.models_simulation import (
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

SCHEMA_MODELS: dict[str, type[ContractModel]] = {
    "algorithm-descriptor": AlgorithmDescriptor,
    "channel-load-snapshot": ChannelLoadSnapshot,
    "cost-snapshot": CostSnapshot,
    "data-source-status": DataSourceStatus,
    "discovery-area": DiscoveryArea,
    "driver-demo-profile": DriverDemoProfile,
    "driver-demo-profile-advance-request": DriverDemoProfileAdvanceRequest,
    "driver-demo-profile-advance-response": DriverDemoProfileAdvanceResponse,
    "driver-request": DriverRequest,
    "driver-demo-replan-request": DriverDemoReplanRequest,
    "driver-trip-event": DriverTripEvent,
    "driver-trip-record": DriverTripRecord,
    "driver-trip-snapshot": DriverTripSnapshot,
    "driver-tandem-arrival-request": DriverTandemArrivalRequest,
    "driver-tandem-arrival-replay": DriverTandemArrivalReplay,
    "driver-tandem-departure-request": DriverTandemDepartureRequest,
    "driver-tandem-departure-replay": DriverTandemDepartureReplay,
    "error-response": ErrorResponse,
    "external-occupancy-request": ExternalOccupancyRequest,
    "external-occupancy-response": ExternalOccupancyResponse,
    "journey": Journey,
    "journey-alternative-request": JourneyAlternativeRequest,
    "journey-command-request": JourneyCommandRequest,
    "journey-confirm-request": JourneyConfirmRequest,
    "journey-decline-request": JourneyDeclineRequest,
    "journey-decline-response": JourneyDeclineResponse,
    "journey-recommendation-request": JourneyRecommendationRequest,
    "journey-recommendation-response": JourneyRecommendationResponse,
    "journey-reassignment-request": JourneyReassignmentRequest,
    "journey-reassignment-response": JourneyReassignmentResponse,
    "journey-replan-request": JourneyReplanRequest,
    "journey-replan-response": JourneyReplanResponse,
    "layout": Layout,
    "parking-lot": ParkingLot,
    "parking-facility-layout": ParkingFacilityLayout,
    "parking-facility-state-snapshot": ParkingFacilityStateSnapshot,
    "parking-space": ParkingSpace,
    "recommendation": Recommendation,
    "recommendation-request": RecommendationRequest,
    "driver-entrance": DriverEntrance,
    "driver-journey-snapshot": DriverJourneySnapshot,
    "driver-recommendation-context": DriverRecommendationContext,
    "replan-decision": ReplanDecision,
    "route": Route,
    "route-preview": RoutePreview,
    "route-preview-request": RoutePreviewRequest,
    "scenario-bundle": ScenarioBundle,
    "simulation-event": SimulationEvent,
    "simulation-command-request": SimulationCommandRequest,
    "simulation-replay-request": SimulationReplayRequest,
    "simulation-run-request": SimulationRunRequest,
    "simulation-run-response": SimulationRunResponse,
    "simulation-summary-response": SimulationSummaryResponse,
}
