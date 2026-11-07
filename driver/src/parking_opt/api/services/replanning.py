"""Audited navigation replanning from visible dynamic channel state."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from parking_opt.api.dynamic_costs import DynamicCostService
from parking_opt.api.models import (
    ChannelLoadSnapshot,
    Layout,
    ReplanDecision,
    Route,
)
from parking_opt.api.routing import RouteCostService, RouteNotFoundError
from parking_opt.api.sessions import (
    IdempotencyConflictError,
    IllegalTransitionError,
    InMemorySessionStore,
    JourneyNotFoundError,
    JourneyRecord,
    JourneyState,
    VersionConflictError,
)


@dataclass(frozen=True, slots=True)
class ReplanResult:
    journey: JourneyRecord
    decision: ReplanDecision


@dataclass(frozen=True, slots=True)
class NavigationRecovery:
    current_route: Route
    current_node_id: str
    last_replan: ReplanDecision | None = None


@dataclass(frozen=True, slots=True)
class _Replay:
    payload_sha256: str
    result: ReplanResult


@dataclass(frozen=True, slots=True)
class _DemoReplay:
    request_sha256: str
    result: ReplanResult


ReplanTrigger = Literal["deviation", "cost_update", "manual_refresh"]
ReplanOutcome = Literal["success", "warning", "failed"]
DriverDemoAction = Literal["simulate_deviation", "simulate_cost_update"]


class JourneyReplanService:
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

    def driver_demo_replan(
        self,
        *,
        journey_id: str,
        expected_version: int,
        action: DriverDemoAction,
        layout: Layout,
        idempotency_key: str,
    ) -> ReplanResult:
        """Derive one deterministic synthetic demo input without trusting browser domain data."""

        with self._store.atomic():
            request_sha256 = self._demo_request_hash(
                journey_id=journey_id,
                expected_version=expected_version,
                action=action,
                layout=layout,
            )
            replay = self._demo_idempotency.get((journey_id, idempotency_key))
            if replay is not None:
                if replay.request_sha256 != request_sha256:
                    raise IdempotencyConflictError(
                        "driver demo idempotency key was reused with different input"
                    )
                return replay.result
            journey = self._store.get_journey(journey_id)
            if journey is None:
                raise JourneyNotFoundError(
                    f"navigation journey is unavailable: {journey_id}"
                )
            if journey.version != expected_version:
                raise VersionConflictError("driver demo used a stale journey version")
            if journey.state is not JourneyState.NAVIGATING:
                raise IllegalTransitionError(
                    "driver demo requires an active navigating journey"
                )
            navigation = self._navigation_by_journey.get(journey_id)
            if navigation is None:
                raise IllegalTransitionError(
                    f"navigation route is unavailable: {journey_id}"
                )
            observed_at = self._store.current_wall_time()
            loads = {item.channel_zone_id: 0 for item in layout.channel_zones}
            if self._store.remaining_deadline_s(journey_id) <= 0:
                result = self.replan(
                    journey_id=journey_id,
                    expected_version=expected_version,
                    current_node_id=navigation.current_node_id,
                    trigger=(
                        "deviation"
                        if action == "simulate_deviation"
                        else "cost_update"
                    ),
                    layout=layout,
                    channel_load=ChannelLoadSnapshot(
                        parking_lot_id=layout.parking_lot_id,
                        layout_version=layout.layout_version,
                        observed_at=observed_at,
                        active_units_by_zone=loads,
                    ),
                    idempotency_key=idempotency_key,
                )
                self._demo_idempotency[(journey_id, idempotency_key)] = _DemoReplay(
                    request_sha256=request_sha256,
                    result=result,
                )
                return result
            if action == "simulate_deviation":
                current_node_id = self._deterministic_deviation_node(
                    layout=layout,
                    navigation=navigation,
                    observed_at=observed_at,
                    loads=loads,
                )
                trigger: ReplanTrigger = "deviation"
            else:
                current_node_id = navigation.current_node_id
                remaining_edges = self._remaining_route_edges(navigation)
                zones = sorted(
                    {
                        zone_id
                        for edge in layout.edges
                        if edge.edge_id in remaining_edges
                        for zone_id in edge.channel_zone_ids
                    }
                )
                if not zones:
                    raise IllegalTransitionError(
                        "current route has no channel zone for a cost-update demo"
                    )
                selected_zone = zones[0]
                capacity_by_zone = {
                    item.channel_zone_id: item.capacity for item in layout.channel_zones
                }
                loads[selected_zone] = capacity_by_zone[selected_zone]
                trigger = "cost_update"
            load = ChannelLoadSnapshot(
                parking_lot_id=layout.parking_lot_id,
                layout_version=layout.layout_version,
                observed_at=observed_at,
                active_units_by_zone=loads,
            )
            result = self.replan(
                journey_id=journey_id,
                expected_version=expected_version,
                current_node_id=current_node_id,
                trigger=trigger,
                layout=layout,
                channel_load=load,
                idempotency_key=idempotency_key,
            )
            self._demo_idempotency[(journey_id, idempotency_key)] = _DemoReplay(
                request_sha256=request_sha256,
                result=result,
            )
            return result

    def _deterministic_deviation_node(
        self,
        *,
        layout: Layout,
        navigation: NavigationRecovery,
        observed_at: datetime,
        loads: dict[str, int],
    ) -> str:
        current = next(
            (item for item in layout.nodes if item.node_id == navigation.current_node_id),
            None,
        )
        if current is None:
            raise IllegalTransitionError("current navigation node is absent from layout")
        clear_load = ChannelLoadSnapshot(
            parking_lot_id=layout.parking_lot_id,
            layout_version=layout.layout_version,
            observed_at=observed_at,
            active_units_by_zone=loads,
        )
        clear_costs = self._costs.build(layout, clear_load)
        ranked: list[tuple[float, str]] = []
        route_nodes = set(navigation.current_route.node_ids)
        target = navigation.current_route.to_node_id
        for node in layout.nodes:
            if node.node_id in route_nodes or node.node_id == target:
                continue
            try:
                self._routes.route(
                    layout,
                    clear_costs,
                    from_node_id=node.node_id,
                    to_node_id=target,
                )
            except RouteNotFoundError:
                continue
            distance_sq = (
                (node.coordinate.x_m - current.coordinate.x_m) ** 2
                + (node.coordinate.y_m - current.coordinate.y_m) ** 2
            )
            ranked.append((distance_sq, node.node_id))
        if not ranked:
            raise IllegalTransitionError("no deterministic deviation node is available")
        return min(ranked)[1]

    @staticmethod
    def _remaining_route_edges(navigation: NavigationRecovery) -> tuple[str, ...]:
        try:
            node_index = navigation.current_route.node_ids.index(
                navigation.current_node_id
            )
        except ValueError:
            return navigation.current_route.edge_ids
        return navigation.current_route.edge_ids[node_index:]

    @staticmethod
    def _demo_request_hash(
        *,
        journey_id: str,
        expected_version: int,
        action: DriverDemoAction,
        layout: Layout,
    ) -> str:
        payload = {
            "journey_id": journey_id,
            "expected_version": expected_version,
            "action": action,
            "parking_lot_id": layout.parking_lot_id,
            "layout_version": layout.layout_version,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

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
