"""Build an immutable v1 request and reuse its exact arrival feasibility logic."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from time import monotonic
from typing import Any

from parking_opt.api.models import CostSnapshot, DriverRequest, Layout, SpaceStatus
from parking_opt.api.routing import RouteCostService, RouteNotFoundError
from parking_opt.contracts.canonical import canonical_sha256
from parking_opt.contracts.schema_validation import SchemaCatalog
from parking_opt.contracts.snapshot_projection import project_observed_snapshot
from parking_opt.domain.enums import (
    ArrivalStatus,
    DepartureInformationSource,
    DepartureStatus,
    LocationKind,
    ManualStatus,
    PositionKind,
    ReservationStatus,
)
from parking_opt.domain.invariants import assert_state_invariants
from parking_opt.domain.records import (
    DecisionRequest,
    DepartureInformation,
    LocationState,
    PendingRequest,
    PositionState,
    VehicleState,
)
from parking_opt.domain.state import (
    PathCostReference,
    PositionMetadata,
    empty_authoritative_state,
)
from parking_opt.strategies._selection import ArrivalCandidateAssessment
from parking_opt.strategies.online_rule import OnlineRulePolicy


@dataclass(frozen=True, slots=True)
class V1AssessmentBundle:
    """Exact v1 assessments plus the immutable request used to obtain them."""

    request: DecisionRequest
    assessments: tuple[ArrivalCandidateAssessment, ...]


class V1AssessmentError(RuntimeError):
    """The protected v1 boundary could not produce a complete assessment."""


class V1AssessmentTimeoutError(V1AssessmentError):
    """The protected v1 policy returned before assessing every v2 space."""


class V1OnlineRuleAdapter:
    """Translate v2 visible values without modifying any frozen v1 asset."""

    def __init__(
        self,
        *,
        schema_dir: Path,
        route_service: RouteCostService,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._policy = OnlineRulePolicy(
            schema_catalog=SchemaCatalog(schema_dir),
            clock=monotonic if clock is None else clock,
        )
        self._route_service = route_service

    def assess(
        self,
        driver: DriverRequest,
        layout: Layout,
        costs: CostSnapshot,
    ) -> V1AssessmentBundle:
        request = self._decision_request(driver, layout, costs)
        try:
            assessments = self._policy.explain_arrival_candidates(request)
        except V1AssessmentError:
            raise
        except Exception as exc:
            raise V1AssessmentError("v1 arrival assessment failed") from exc
        expected_ids = {item.space_id for item in layout.spaces}
        assessed_ids = {item.position_id for item in assessments}
        if len(assessments) < len(layout.spaces) and assessed_ids < expected_ids:
            raise V1AssessmentTimeoutError(
                "v1 arrival assessment timed out before all spaces were assessed"
            )
        if assessed_ids != expected_ids or len(assessments) != len(layout.spaces):
            raise V1AssessmentError("v1 arrival assessment returned an invalid space domain")
        return V1AssessmentBundle(request=request, assessments=assessments)

    def _decision_request(
        self,
        driver: DriverRequest,
        layout: Layout,
        costs: CostSnapshot,
    ) -> DecisionRequest:
        if driver.parking_lot_id != layout.parking_lot_id:
            raise ValueError("driver request and layout parking_lot_id mismatch")
        if driver.entrance_node_id not in layout.entrance_node_ids:
            raise ValueError("driver entrance is not an entrance of the selected parking lot")
        v1_layout = self._v1_layout(layout, costs)
        sim_time_s = int(driver.requested_at.timestamp())
        positions = tuple(
            PositionState(
                position_id=item.space_id,
                position_kind=PositionKind.NORMAL,
                physically_available=item.status is SpaceStatus.AVAILABLE,
                assignable=item.assignable,
                planned_closure=False,
                occupant_vehicle_id=(
                    f"occupant-{item.space_id}" if item.status is SpaceStatus.OCCUPIED else None
                ),
            )
            for item in layout.spaces
        ) + tuple(
            PositionState(
                position_id=item.buffer_id,
                position_kind=PositionKind.BUFFER,
                physically_available=item.available,
                assignable=False,
                planned_closure=False,
                occupant_vehicle_id=None,
            )
            for item in layout.buffers
        )
        unknown_departure = DepartureInformation(
            expected_departure_time_s=None,
            source=DepartureInformationSource.UNKNOWN,
            known_at_time_s=sim_time_s,
        )
        occupants = tuple(
            VehicleState(
                anonymous_vehicle_id=f"occupant-{item.space_id}",
                location_state=LocationState(LocationKind.AT_POSITION, item.space_id),
                arrival_status=ArrivalStatus.ENTRY_COMPLETED,
                departure_status=DepartureStatus.NONE,
                manual_status=ManualStatus.NONE,
                ever_admitted=True,
                admitted_at_s=sim_time_s,
                waiting_since_s=None,
                action_context_id=None,
                active_transaction_id=None,
                reservation_status=ReservationStatus.NONE,
                departure_information=unknown_departure,
            )
            for item in layout.spaces
            if item.status is SpaceStatus.OCCUPIED
        )
        expected_departure = (
            DepartureInformation(
                expected_departure_time_s=int(driver.expected_departure_at.timestamp()),
                source=DepartureInformationSource.USER_ESTIMATE,
                known_at_time_s=sim_time_s,
                source_record_id=driver.request_id,
            )
            if driver.expected_departure_at is not None
            else unknown_departure
        )
        driver_vehicle = VehicleState(
            anonymous_vehicle_id=f"driver-{driver.session_id}",
            location_state=LocationState(LocationKind.ENTRY_QUEUE),
            arrival_status=ArrivalStatus.PENDING,
            departure_status=DepartureStatus.NONE,
            manual_status=ManualStatus.NONE,
            ever_admitted=False,
            admitted_at_s=None,
            waiting_since_s=sim_time_s,
            action_context_id=None,
            active_transaction_id=None,
            reservation_status=ReservationStatus.NONE,
            departure_information=expected_departure,
        )
        path_refs = tuple(
            PathCostReference(
                from_node_id=item["from_node_id"],
                to_node_id=item["to_node_id"],
                distance_m=float(item["distance_m"]),
                travel_time_s=int(item["travel_time_s"]),
                channel_zone_ids=tuple(item["channel_zone_ids"]),
            )
            for item in v1_layout["path_costs"]
        )
        metadata = tuple(
            PositionMetadata(
                position_id=item.space_id,
                position_kind=PositionKind.NORMAL,
                access_node_id=item.access_node_id,
                stack_group_id=item.stack_group_id,
                depth=item.depth,
                channel_zone_ids=(),
            )
            for item in layout.spaces
        ) + tuple(
            PositionMetadata(
                position_id=item.buffer_id,
                position_kind=PositionKind.BUFFER,
                access_node_id=item.access_node_id,
                stack_group_id=None,
                depth=None,
                channel_zone_ids=item.channel_zone_ids,
            )
            for item in layout.buffers
        )
        state = empty_authoritative_state(
            run_id=f"web-v2-{driver.session_id}",
            scenario_id=layout.parking_lot_id,
            layout_id=str(v1_layout["layout_id"]),
            position_metadata=metadata,
            exit_node_ids=layout.exit_node_ids,
            path_costs=path_refs,
            positions=positions,
            executor_capacity=1,
            channel_zone_capacities=tuple(
                (item.channel_zone_id, item.capacity) for item in layout.channel_zones
            ),
            active_buffer_position_ids=tuple(
                item.buffer_id for item in layout.buffers if item.available
            ),
            arrival_wait_capacity=8,
            max_arrival_wait_s=30,
        )
        state = replace(
            state,
            sim_time_s=sim_time_s,
            vehicles=(*occupants, driver_vehicle),
            pending_requests=(
                PendingRequest(
                    request_id=driver.request_id,
                    anonymous_vehicle_id=driver_vehicle.anonymous_vehicle_id,
                    request_type="ARRIVAL",
                    requested_at_s=sim_time_s,
                    event_sequence_no=1,
                    entrance_node_id=driver.entrance_node_id,
                ),
            ),
        )
        assert_state_invariants(state)
        snapshot = project_observed_snapshot(
            state,
            snapshot_id=f"snapshot-{driver.request_id}",
            decision_time_s=sim_time_s,
        )
        config = self._approved_config(layout)
        return DecisionRequest(
            request_id=f"v1-{driver.request_id}",
            algorithm_id="online-rule-v1",
            algorithm_version="1.0.0",
            trigger_event_id=f"arrival-{driver.request_id}",
            trigger_event_type="ARRIVAL_REQUESTED",
            trigger_request_id=driver.request_id,
            trigger_anonymous_vehicle_id=driver_vehicle.anonymous_vehicle_id,
            decision_time_s=sim_time_s,
            layout=v1_layout,
            approved_config=config,
            observed_snapshot=snapshot,
            config_sha256=canonical_sha256(config),
            layout_sha256=canonical_sha256(v1_layout),
            visible_snapshot_sha256=snapshot.snapshot_content_sha256,
            decision_target_s=1.0,
            decision_deadline_s=3.0,
        )

    def _v1_layout(self, layout: Layout, costs: CostSnapshot) -> dict[str, Any]:
        relevant_nodes = sorted(
            {
                *layout.entrance_node_ids,
                *layout.exit_node_ids,
                *(item.access_node_id for item in layout.spaces),
                *(item.access_node_id for item in layout.buffers),
            }
        )
        path_costs: list[dict[str, Any]] = []
        for from_node in relevant_nodes:
            for to_node in relevant_nodes:
                try:
                    route = self._route_service.route(
                        layout, costs, from_node_id=from_node, to_node_id=to_node
                    )
                except RouteNotFoundError:
                    continue
                zones = tuple(
                    dict.fromkeys(
                        zone
                        for edge_id in route.edge_ids
                        for zone in next(
                            item for item in layout.edges if item.edge_id == edge_id
                        ).channel_zone_ids
                    )
                )
                path_costs.append(
                    {
                        "path_cost_id": f"path-{from_node}-{to_node}",
                        "from_node_id": from_node,
                        "to_node_id": to_node,
                        "distance_m": route.distance_m,
                        "travel_time_s": max(0, round(route.dynamic_eta_s)),
                        "road_edge_ids": list(route.edge_ids),
                        "channel_zone_ids": list(zones),
                    }
                )
        return {
            "schema_version": "1.0.0",
            "layout_id": f"v1-{layout.parking_lot_id}-{layout.layout_version}",
            "coordinate_system": {
                "kind": "local_meters",
                "origin_note": layout.coordinate_origin_note,
            },
            "road_nodes": [
                {
                    "road_node_id": item.node_id,
                    "x_m": item.coordinate.x_m,
                    "y_m": item.coordinate.y_m,
                    "node_kind": "position_access"
                    if item.kind in {"space_access", "buffer_access"}
                    else item.kind,
                }
                for item in layout.nodes
            ],
            "road_edges": [
                {
                    "road_edge_id": item.edge_id,
                    "from_node_id": item.from_node_id,
                    "to_node_id": item.to_node_id,
                    "distance_m": item.distance_m,
                    "travel_time_s": max(0, round(costs.edge_travel_time_s[item.edge_id])),
                    "directed": item.directed,
                    "channel_zone_ids": list(item.channel_zone_ids),
                }
                for item in layout.edges
            ],
            "path_costs": path_costs,
            "slots": [
                {
                    "position_id": item.space_id,
                    "x_m": item.coordinate.x_m,
                    "y_m": item.coordinate.y_m,
                    "access_node_id": item.access_node_id,
                    "stack_group_id": item.stack_group_id,
                    "depth": item.depth,
                    "channel_zone_ids": [],
                }
                for item in layout.spaces
            ],
            "buffer_slots": [
                {
                    "position_id": item.buffer_id,
                    "x_m": item.coordinate.x_m,
                    "y_m": item.coordinate.y_m,
                    "access_node_id": item.access_node_id,
                    "channel_zone_ids": list(item.channel_zone_ids),
                }
                for item in layout.buffers
            ],
            "channel_zones": [
                {"channel_zone_id": item.channel_zone_id, "capacity": item.capacity}
                for item in layout.channel_zones
            ],
        }

    @staticmethod
    def _approved_config(layout: Layout) -> dict[str, Any]:
        active_buffers = [item.buffer_id for item in layout.buffers if item.available]
        return {
            "recoverability_policy": "strict_recoverable",
            "rolling_enabled": False,
            "arrival_wait_capacity": 8,
            "max_arrival_wait_s": 30,
            "max_departure_wait_s": 300,
            "use_soft_departure_information": False,
            "rolling_window_s": 900,
            "optimization_budget_s": 1.0,
            "fallback_target_s": 0.1,
            "minimum_logging_reserve_s": 0.02,
            "max_requests_per_solve": 12,
            "max_positions_per_arrival": max(1, len(layout.spaces)),
            "max_buffer_matchings_per_departure": 4,
            "max_action_plans_total": 64,
            "max_soft_future_records": 20,
            "buffer_count": len(active_buffers),
            "relocation_executor_capacity": 1,
            "executor_type": "simulation_only",
            "relocation_setup_s": 5.0,
            "relocation_speed_mps": 1.0,
            "active_buffer_position_ids": active_buffers,
        }
