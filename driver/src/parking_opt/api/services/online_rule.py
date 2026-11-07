"""Version-2 recommendation service composed from v1 feasibility and v2 route costs."""

from __future__ import annotations

from collections.abc import Mapping

from parking_opt.api.adapters.v1 import (
    V1AssessmentError,
    V1AssessmentTimeoutError,
    V1OnlineRuleAdapter,
)
from parking_opt.api.models import (
    CandidateAssessment,
    CostSnapshot,
    DataSourceStatus,
    DriverRequest,
    Layout,
    Recommendation,
    Route,
)
from parking_opt.api.routing import RouteCostService, RouteNotFoundError


class OnlineRuleServiceV2:
    """Recommend a space without creating reservations, claims, or mutable state."""

    algorithm_id = "online-rule-v2"
    algorithm_version = "2.0.0"

    def __init__(
        self,
        *,
        v1_adapter: V1OnlineRuleAdapter,
        route_service: RouteCostService,
    ) -> None:
        self._v1_adapter = v1_adapter
        self._route_service = route_service

    def recommend(
        self,
        driver: DriverRequest,
        layout: Layout,
        costs: CostSnapshot,
        data_source: DataSourceStatus,
        excluded_space_reasons: Mapping[str, str] | None = None,
        max_dynamic_eta_s: float | None = None,
    ) -> Recommendation:
        if driver.parking_lot_id != layout.parking_lot_id:
            raise ValueError("driver request and layout parking_lot_id mismatch")
        if costs.parking_lot_id != layout.parking_lot_id:
            raise ValueError("cost snapshot and layout parking_lot_id mismatch")
        if data_source.parking_lot_id != layout.parking_lot_id:
            raise ValueError("data source and layout parking_lot_id mismatch")
        recommendation_id = f"recommendation-{driver.request_id}"
        try:
            v1 = self._v1_adapter.assess(driver, layout, costs)
        except V1AssessmentTimeoutError:
            return Recommendation(
                recommendation_id=recommendation_id,
                request_id=driver.request_id,
                parking_lot_id=driver.parking_lot_id,
                algorithm_id=self.algorithm_id,
                algorithm_version=self.algorithm_version,
                data_source=data_source,
                solver_status="failed",
                failure_code="V1_ASSESSMENT_TIMEOUT",
                assessments=(),
                explanation_codes=("V1_ASSESSMENT_TIMEOUT",),
            )
        except V1AssessmentError:
            return Recommendation(
                recommendation_id=recommendation_id,
                request_id=driver.request_id,
                parking_lot_id=driver.parking_lot_id,
                algorithm_id=self.algorithm_id,
                algorithm_version=self.algorithm_version,
                data_source=data_source,
                solver_status="failed",
                failure_code="V1_ASSESSMENT_FAILED",
                assessments=(),
                explanation_codes=("V1_ASSESSMENT_FAILED",),
            )
        spaces = {item.space_id: item for item in layout.spaces}
        exclusions = {} if excluded_space_reasons is None else excluded_space_reasons
        unknown_exclusions = set(exclusions) - set(spaces)
        if unknown_exclusions:
            raise ValueError(
                f"excluded spaces are not in layout: {sorted(unknown_exclusions)}"
            )
        if max_dynamic_eta_s is not None and max_dynamic_eta_s < 0:
            raise ValueError("max_dynamic_eta_s must be non-negative")
        assessments: list[CandidateAssessment] = []
        ranked: list[tuple[tuple[int, float, float, int, str], str, Route]] = []
        for item in v1.assessments:
            space = spaces[item.position_id]
            reasons = list(item.reason_codes)
            if space.space_id in exclusions:
                reasons.append(exclusions[space.space_id])
            if driver.requires_charging and not space.charging:
                reasons.append("CHARGING_REQUIRED")
            route = None
            if item.feasible and not reasons:
                try:
                    route = self._route_service.route(
                        layout,
                        costs,
                        from_node_id=driver.entrance_node_id,
                        to_node_id=space.access_node_id,
                    )
                except RouteNotFoundError:
                    reasons.append("DYNAMIC_ROUTE_UNREACHABLE")
            if (
                route is not None
                and max_dynamic_eta_s is not None
                and route.dynamic_eta_s > max_dynamic_eta_s
            ):
                reasons.append("ETA_EXCEEDS_RESERVATION")
            feasible = item.feasible and not reasons and route is not None
            assessment = CandidateAssessment(
                space_id=space.space_id,
                feasible=feasible,
                reason_codes=tuple(dict.fromkeys(reasons)),
                recoverability_rank=item.incremental_unrecoverable_exposure,
                dynamic_eta_s=None if route is None else route.dynamic_eta_s,
                distance_m=None if route is None else route.distance_m,
                depth=space.depth,
            )
            assessments.append(assessment)
            if feasible:
                assert route is not None
                # Hard feasibility precedes this key. Lower exposure/ETA/distance/depth/ID wins.
                score = (
                    item.incremental_unrecoverable_exposure or 0,
                    route.dynamic_eta_s,
                    route.distance_m,
                    space.depth,
                    space.space_id,
                )
                ranked.append((score, space.space_id, route))
        ranked.sort(key=lambda item: item[0])
        assessment_order = {item.space_id: index for index, item in enumerate(assessments)}
        assessments.sort(key=lambda item: assessment_order[item.space_id])
        if not ranked:
            return Recommendation(
                recommendation_id=recommendation_id,
                request_id=driver.request_id,
                parking_lot_id=driver.parking_lot_id,
                algorithm_id=self.algorithm_id,
                algorithm_version=self.algorithm_version,
                data_source=data_source,
                solver_status="no_feasible_space",
                assessments=tuple(assessments),
                explanation_codes=("NO_FEASIBLE_SPACE",),
            )
        _, selected_space, selected_route = ranked[0]
        tandem_space_ids = {
            space_id
            for group in layout.tandem_groups
            for space_id in group.space_ids_near_to_deep
        }
        if selected_space in tandem_space_ids:
            alternative = next(
                (item[1] for item in ranked[1:] if item[1] not in tandem_space_ids),
                None,
            )
        else:
            alternative = ranked[1][1] if len(ranked) > 1 else None
        return Recommendation(
            recommendation_id=recommendation_id,
            request_id=driver.request_id,
            parking_lot_id=driver.parking_lot_id,
            algorithm_id=self.algorithm_id,
            algorithm_version=self.algorithm_version,
            data_source=data_source,
            solver_status="success",
            recommended_space_id=selected_space,
            alternative_space_ids=() if alternative is None else (alternative,),
            assessments=tuple(assessments),
            route=selected_route,
            explanation_codes=(
                "V1_FEASIBILITY_REUSED",
                "CURRENT_COST_SNAPSHOT_RANKING",
                "NO_CLAIM_CREATED_M2",
            ),
        )
