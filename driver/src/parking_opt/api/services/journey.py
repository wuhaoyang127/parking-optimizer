"""Compose M2 recommendation with M3 atomic synthetic resource claims."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from parking_opt.api.models import (
    CostSnapshot,
    DataSourceStatus,
    DriverRequest,
    Journey,
    Layout,
)
from parking_opt.api.routing import RouteCostService
from parking_opt.api.services.journey_commands import JourneyCommandsMixin
from parking_opt.api.services.journey_occupancy import JourneyOccupancyMixin
from parking_opt.api.services.journey_recommend import JourneyRecommendMixin
from parking_opt.api.services.journey_types import (
    DriverJourneyRecovery,
    JourneyRecommendationResult,
    _JourneyContext,
    _RecommendationReplay,
)
from parking_opt.api.services.online_rule import OnlineRuleServiceV2
from parking_opt.api.sessions import (
    InMemorySessionStore,
    JourneyRecord,
    SessionNamespace,
)

class JourneyRecommendationService(
    JourneyRecommendMixin,
    JourneyCommandsMixin,
    JourneyOccupancyMixin,
):
    """Evaluate visible state and create the resulting claim in one critical section."""
    def __init__(
        self,
        *,
        online_rule: OnlineRuleServiceV2,
        route_service: RouteCostService,
        session_store: InMemorySessionStore,
        eta_safety_margin_s: int,
        driver_reservation_ttl_s: int,
    ) -> None:
        if eta_safety_margin_s < 0:
            raise ValueError("eta_safety_margin_s must be non-negative")
        if driver_reservation_ttl_s <= eta_safety_margin_s:
            raise ValueError("reservation TTL must exceed ETA safety margin")
        self._online_rule = online_rule
        self._routes = route_service
        self._store = session_store
        self._max_driver_eta_s = driver_reservation_ttl_s - eta_safety_margin_s
        self._idempotency: dict[tuple[str, str], _RecommendationReplay] = {}
        self._contexts: dict[str, _JourneyContext] = {}
        self._command_idempotency: dict = {}
        self._external_idempotency: dict = {}
        self._reassignment_idempotency: dict = {}
        self._decline_idempotency: dict = {}
    def _scope_exclusions(
        self,
        *,
        session_id: str,
        namespace: SessionNamespace,
        scenario_id: str,
        parking_lot_id: str,
    ) -> dict[str, str]:
        snapshot = self._store.availability_snapshot(
            session_id=session_id,
            namespace=namespace,
            scopes=((scenario_id, parking_lot_id),),
        ).scopes[0]
        exclusions = dict(snapshot.unavailable_space_reasons)
        exclusions.update({space_id: "APPLICATION_CLAIMED" for space_id in snapshot.claimed_space_ids})
        return exclusions
    def current_driver_recovery(self, session_id: str) -> DriverJourneyRecovery | None:
        """Recover the session's current/latest attempt without renewing any deadline."""

        record = self._store.current_driver_journey(session_id)
        if record is None:
            return None
        context = self._require_context(record.journey_id)
        return DriverJourneyRecovery(
            observed_at=self._store.current_wall_time(),
            driver=context.driver,
            result=JourneyRecommendationResult(
                recommendation=context.result.recommendation,
                journey=record,
            ),
        )
    def _require_context(self, journey_id: str) -> _JourneyContext:
        try:
            return self._contexts[journey_id]
        except KeyError as exc:
            raise ValueError(f"journey recommendation context is unavailable: {journey_id}") from exc

    def visible_driver_inputs(
        self, session_id: str
    ) -> list[tuple[DriverRequest, JourneyRecord]]:
        """Return the session's recoverable (driver request, journey record) pairs."""
        pairs: list[tuple[DriverRequest, JourneyRecord]] = []
        for record in self._store.session_journeys(session_id, SessionNamespace.DRIVER):
            try:
                context = self._require_context(record.journey_id)
            except ValueError:
                continue
            pairs.append((context.driver, record))
        return pairs
    def _remember_command(
        self,
        *,
        context: _JourneyContext,
        journey_id: str,
        key: str,
        payload_hash: str,
        result: JourneyRecommendationResult,
    ) -> None:
        from parking_opt.api.services.journey_types import _CommandReplay

        self._command_idempotency[(journey_id, key)] = _CommandReplay(
            payload_sha256=payload_hash,
            result=result,
        )
        self._contexts[journey_id] = _JourneyContext(
            driver=context.driver,
            namespace=context.namespace,
            scenario_id=context.scenario_id,
            result=result,
            excluded_space_reasons=context.excluded_space_reasons,
        )
    @staticmethod
    def _command_payload_sha256(
        *,
        journey_id: str,
        expected_version: int,
        space_id: str | None,
        layout: Layout,
        costs: CostSnapshot,
    ) -> str:
        payload = {
            "journey_id": journey_id,
            "expected_version": expected_version,
            "space_id": space_id,
            "layout_version": layout.layout_version,
            "cost_version": costs.cost_version,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    @staticmethod
    def _payload_sha256(
        *,
        driver: DriverRequest,
        namespace: SessionNamespace,
        scenario_id: str,
        journey_id: str,
        attempt_id: str,
        layout: Layout,
        costs: CostSnapshot,
        additional_excluded_space_reasons: dict[str, str] | None,
    ) -> str:
        payload = {
            "driver": driver.model_dump(mode="json"),
            "namespace": namespace,
            "scenario_id": scenario_id,
            "journey_id": journey_id,
            "attempt_id": attempt_id,
            "layout_version": layout.layout_version,
            "cost_version": costs.cost_version,
            "additional_excluded_space_reasons": additional_excluded_space_reasons or {},
        }
        encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

def journey_to_contract(record: JourneyRecord, *, recommendation_id: str | None = None) -> Journey:
    legal_by_state = {
        "waiting": ("cancel", "retry_recommendation"),
        "soft_held": ("select_alternative", "confirm", "cancel"),
        "session_reserved": ("start_navigation", "cancel"),
        "navigating": (
            "replan",
            "driver_demo_replan",
            "report_external_occupancy",
            "reassign",
            "occupy",
            "cancel",
        ),
        "occupied": ("depart", "reset_demo"),
    }
    return Journey(
        journey_id=record.journey_id,
        attempt_id=record.attempt_id,
        session_id=record.session_id,
        namespace=record.namespace.value,
        scenario_id=record.scenario_id,
        parking_lot_id=record.parking_lot_id,
        state=record.state.value,
        version=record.version,
        space_id=record.space_id,
        recommendation_id=recommendation_id,
        updated_at=record.updated_at,
        expires_at=record.expires_at,
        terminal_reason=record.terminal_reason,
        legal_operations=legal_by_state.get(record.state, ()),
    )
