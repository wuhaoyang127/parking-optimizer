"""Deterministic driver-demo replanning inputs for the replan service."""

from __future__ import annotations
import hashlib
import json
from datetime import datetime
from parking_opt.api.models import ChannelLoadSnapshot, Layout
from parking_opt.api.routing import RouteNotFoundError
from parking_opt.api.services.replanning_types import (
    DriverDemoAction,
    NavigationRecovery,
    ReplanResult,
    ReplanTrigger,
    _DemoReplay,
)
from parking_opt.api.sessions import (
    IdempotencyConflictError,
    IllegalTransitionError,
    JourneyNotFoundError,
    JourneyState,
    VersionConflictError,
)

class ReplanDemoMixin:
    def driver_demo_replan(
        self,
        *,
        journey_id: str,
        expected_version: int,
        action: DriverDemoAction,
        layout: Layout,
        idempotency_key: str,
    ) -> ReplanResult:
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
                    raise IdempotencyConflictError("driver demo idempotency key was reused with different input")
                return replay.result
            journey = self._store.get_journey(journey_id)
            if journey is None:
                raise JourneyNotFoundError(f"navigation journey is unavailable: {journey_id}")
            if journey.version != expected_version:
                raise VersionConflictError("driver demo used a stale journey version")
            if journey.state is not JourneyState.NAVIGATING:
                raise IllegalTransitionError("driver demo requires an active navigating journey")
            navigation = self._navigation_by_journey.get(journey_id)
            if navigation is None:
                raise IllegalTransitionError(f"navigation route is unavailable: {journey_id}")
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
                    raise IllegalTransitionError("current route has no channel zone for a cost-update demo")
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
