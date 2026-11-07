"""Build an immutable v1 request and reuse its exact arrival feasibility logic."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

from parking_opt.api.adapters.v1_mapping import approved_config, v1_layout_mapping
from parking_opt.api.adapters.v1_state import build_v1_state
from parking_opt.api.models import CostSnapshot, DriverRequest, Layout
from parking_opt.api.routing import RouteCostService
from parking_opt.contracts.canonical import canonical_sha256
from parking_opt.contracts.schema_validation import SchemaCatalog
from parking_opt.contracts.snapshot_projection import project_observed_snapshot
from parking_opt.domain.invariants import assert_state_invariants
from parking_opt.domain.records import DecisionRequest
from parking_opt.strategies._selection import ArrivalCandidateAssessment
from parking_opt.strategies.online_rule import OnlineRulePolicy


@dataclass(frozen=True, slots=True)
class V1AssessmentBundle:
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
        v1_layout = v1_layout_mapping(self._route_service, layout, costs)
        sim_time_s = int(driver.requested_at.timestamp())
        state = build_v1_state(driver, layout, v1_layout, sim_time_s)
        assert_state_invariants(state)
        snapshot = project_observed_snapshot(
            state,
            snapshot_id=f"snapshot-{driver.request_id}",
            decision_time_s=sim_time_s,
        )
        config = approved_config(layout)
        driver_vehicle_id = f"driver-{driver.session_id}"
        return DecisionRequest(
            request_id=f"v1-{driver.request_id}",
            algorithm_id="online-rule-v1",
            algorithm_version="1.0.0",
            trigger_event_id=f"arrival-{driver.request_id}",
            trigger_event_type="ARRIVAL_REQUESTED",
            trigger_request_id=driver.request_id,
            trigger_anonymous_vehicle_id=driver_vehicle_id,
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
