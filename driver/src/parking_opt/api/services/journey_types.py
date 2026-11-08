"""Type definitions for the journey recommendation service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from parking_opt.api.models import DriverRequest, Recommendation
from parking_opt.api.sessions import JourneyRecord, SessionNamespace


@dataclass(frozen=True, slots=True)
class JourneyRecommendationResult:
    recommendation: Recommendation
    journey: JourneyRecord


@dataclass(frozen=True, slots=True)
class _RecommendationReplay:
    payload_sha256: str
    result: JourneyRecommendationResult


@dataclass(frozen=True, slots=True)
class _JourneyContext:
    driver: DriverRequest
    namespace: SessionNamespace
    scenario_id: str
    result: JourneyRecommendationResult
    excluded_space_reasons: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class _CommandReplay:
    payload_sha256: str
    result: JourneyRecommendationResult


@dataclass(frozen=True, slots=True)
class ExternalOccupancyResult:
    failed_journey: JourneyRecord
    replacement: JourneyRecommendationResult


@dataclass(frozen=True, slots=True)
class ReassignmentResult:
    ended_journey: JourneyRecord
    replacement: JourneyRecommendationResult


@dataclass(frozen=True, slots=True)
class DriverJourneyRecovery:
    observed_at: datetime
    driver: DriverRequest
    result: JourneyRecommendationResult


@dataclass(frozen=True, slots=True)
class DeclinedRecommendationResult:
    declined_journey: JourneyRecord
    replacement: JourneyRecommendationResult


@dataclass(frozen=True, slots=True)
class _ExternalOccupancyReplay:
    payload_sha256: str
    result: ExternalOccupancyResult


@dataclass(frozen=True, slots=True)
class _ReassignmentReplay:
    payload_sha256: str
    result: ReassignmentResult
