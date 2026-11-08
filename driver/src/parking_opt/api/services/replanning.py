"""Audited navigation replanning from visible dynamic channel state."""

from __future__ import annotations
import hashlib
import json

from parking_opt.api.dynamic_costs import DynamicCostService
from parking_opt.api.models import ChannelLoadSnapshot, Layout, ReplanDecision, Route
from parking_opt.api.routing import RouteCostService, RouteNotFoundError
from parking_opt.api.services.replanning_demo import ReplanDemoMixin
from parking_opt.api.services.replanning_types import (
    NavigationRecovery,
    ReplanOutcome,
    ReplanResult,
    ReplanTrigger,
    _DemoReplay,
    _Replay,
)
from parking_opt.api.sessions import (
    IdempotencyConflictError,
    IllegalTransitionError,
    InMemorySessionStore,
    JourneyNotFoundError,
    JourneyState,
    VersionConflictError,
)

class JourneyReplanService(ReplanDemoMixin):
    """Replan to the existing target without extending its reservation deadline."""
    def __init__(
        self,
        *,
        route_service: RouteCostService,
        cost_service: DynamicCostService,
        session_store: InMemorySessionStore,
        eta_safety_margin_s: int,
    ) -> None:
        self._routes = route_service
        self._costs = cost_service
        self._store = session_store
        self._margin_s = eta_safety_margin_s
        self._routes_by_journey: dict[str, Route] = {}
        self._navigation_by_journey: dict[str, NavigationRecovery] = {}
        self._idempotency: dict[tuple[str, str], _Replay] = {}
        self._demo_idempotency: dict[tuple[str, str], _DemoReplay] = {}
    def register_route(self, journey_id: str, route: Route) -> None:
        with self._store.atomic():
            self._routes_by_journey[journey_id] = route
            self._navigation_by_journey[journey_id] = NavigationRecovery(
                current_route=route,
                current_node_id=route.from_node_id,
            )
    def recover_navigation(self, journey_id: str) -> NavigationRecovery | None:
        return self._navigation_by_journey.get(journey_id)
    def replan(
        self,
        *,
        journey_id: str,
        expected_version: int,
        current_node_id: str,
        trigger: ReplanTrigger,
        layout: Layout,
        channel_load: ChannelLoadSnapshot,
        idempotency_key: str,
    ) -> ReplanResult:
        payload_hash = self._payload_hash(
            journey_id=journey_id,
            expected_version=expected_version,
            current_node_id=current_node_id,
            trigger=trigger,
            channel_load=channel_load,
        )
        with self._store.atomic():
            replay = self._idempotency.get((journey_id, idempotency_key))
            if replay is not None:
                if replay.payload_sha256 != payload_hash:
                    raise IdempotencyConflictError(
                        "replan idempotency key was reused with different input"
                    )
                return replay.result
            initial = self._store.get_journey(journey_id)
            if initial is None:
                raise JourneyNotFoundError(
                    f"navigation journey is unavailable: {journey_id}"
                )
            if initial.version != expected_version:
                raise VersionConflictError("replan used a stale journey version")
            if initial.state is not JourneyState.NAVIGATING:
                raise IllegalTransitionError(
                    "replan requires an active navigating journey"
                )
            try:
                previous = self._routes_by_journey[journey_id]
            except KeyError as exc:
                raise IllegalTransitionError(
                    f"navigation route is unavailable: {journey_id}"
                ) from exc
            if channel_load.observed_at > self._store.current_wall_time():
                raise IllegalTransitionError(
                    "channel load observed_at cannot be in the future"
                )
            live = self._store.refresh_journey(journey_id)
            assert live is not None
            remaining = self._store.remaining_deadline_s(journey_id)
            costs = self._costs.build(layout, channel_load)
            if live.state is JourneyState.EXPIRED:
                decision = ReplanDecision(
                    status="failed",
                    trigger=trigger,
                    cost_snapshot=costs,
                    previous_route=previous,
                    route=None,
                    remaining_reservation_s=0,
                    eta_with_safety_margin_s=None,
                    reason_codes=("RESERVATION_EXPIRED",),
                )
                result = ReplanResult(journey=live, decision=decision)
                self._idempotency[(journey_id, idempotency_key)] = _Replay(
                    payload_sha256=payload_hash,
                    result=result,
                )
                return result
            route = None
            reason_codes: tuple[str, ...]
            outcome: ReplanOutcome
            try:
                route = self._routes.route(
                    layout,
                    costs,
                    from_node_id=current_node_id,
                    to_node_id=previous.to_node_id,
                )
            except RouteNotFoundError:
                outcome = "failed"
                reason_codes = ("DYNAMIC_ROUTE_UNREACHABLE",)
            else:
                if route.dynamic_eta_s + self._margin_s > remaining:
                    outcome = "warning"
                    reason_codes = ("ETA_EXCEEDS_RESERVATION",)
                else:
                    outcome = "success"
                    reason_codes = ("ROUTE_REPLANNED",)
            journey = self._store.record_replan(
                journey_id=journey_id,
                expected_version=expected_version,
                outcome=outcome,
                reason=reason_codes[0],
                idempotency_key=idempotency_key,
            )
            assert journey.state is JourneyState.NAVIGATING
            decision = ReplanDecision(
                status=outcome,
                trigger=trigger,
                cost_snapshot=costs,
                previous_route=previous,
                route=route,
                remaining_reservation_s=remaining,
                eta_with_safety_margin_s=(
                    None if route is None else route.dynamic_eta_s + self._margin_s
                ),
                reason_codes=reason_codes,
            )
            result = ReplanResult(journey=journey, decision=decision)
            self._idempotency[(journey_id, idempotency_key)] = _Replay(
                payload_sha256=payload_hash,
                result=result,
            )
            if route is not None:
                self._routes_by_journey[journey_id] = route
                self._navigation_by_journey[journey_id] = NavigationRecovery(
                    current_route=route,
                    current_node_id=current_node_id,
                    last_replan=decision,
                )
            else:
                self._navigation_by_journey[journey_id] = NavigationRecovery(
                    current_route=previous,
                    current_node_id=current_node_id,
                    last_replan=decision,
                )
            return result
    @staticmethod
    def _payload_hash(
        *,
        journey_id: str,
        expected_version: int,
        current_node_id: str,
        trigger: ReplanTrigger,
        channel_load: ChannelLoadSnapshot,
    ) -> str:
        payload = {
            "journey_id": journey_id,
            "expected_version": expected_version,
            "current_node_id": current_node_id,
            "trigger": trigger,
            "channel_load": channel_load.model_dump(mode="json"),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
