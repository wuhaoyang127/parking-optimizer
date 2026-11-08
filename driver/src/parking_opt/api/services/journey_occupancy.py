"""External-occupancy and reassignment mixin for the journey service."""
from __future__ import annotations
import hashlib
import json
from parking_opt.api.models import CostSnapshot, DataSourceStatus, DriverRequest, Layout, Recommendation
from parking_opt.api.services.journey_types import (
    ExternalOccupancyResult,
    JourneyRecommendationResult,
    ReassignmentResult,
    _ExternalOccupancyReplay,
    _JourneyContext,
    _ReassignmentReplay,
)
from parking_opt.api.sessions import IdempotencyConflictError, IllegalTransitionError, JourneyState, SessionNamespace
class JourneyOccupancyMixin:
    def handle_external_occupancy(
        self,
        *,
        journey_id: str,
        expected_version: int,
        replacement_journey_id: str,
        replacement_attempt_id: str,
        replacement_request_id: str,
        layout: Layout,
        costs: CostSnapshot,
        data_source: DataSourceStatus,
        idempotency_key: str,
    ) -> ExternalOccupancyResult:
        payload = {
            "journey_id": journey_id,
            "expected_version": expected_version,
            "replacement_journey_id": replacement_journey_id,
            "replacement_attempt_id": replacement_attempt_id,
            "replacement_request_id": replacement_request_id,
            "layout_version": layout.layout_version,
            "cost_version": costs.cost_version,
        }
        payload_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        with self._store.atomic():
            replay = self._external_idempotency.get((journey_id, idempotency_key))
            if replay is not None:
                if replay.payload_sha256 != payload_hash:
                    raise IdempotencyConflictError("external occupancy key was reused with different input")
                return replay.result
        live = self._store.refresh_journey(journey_id)
        if live is None or live.state not in {JourneyState.SOFT_HELD, JourneyState.SESSION_RESERVED, JourneyState.NAVIGATING}:
            raise IllegalTransitionError("external occupancy requires an active claimed journey")
        with self._store.atomic():
            replay = self._external_idempotency.get((journey_id, idempotency_key))
            if replay is not None:
                if replay.payload_sha256 != payload_hash:
                    raise IdempotencyConflictError("external occupancy key was reused with different input")
                return replay.result
            current = self._store.get_journey(journey_id)
            if current is None or current.state not in {JourneyState.SOFT_HELD, JourneyState.SESSION_RESERVED, JourneyState.NAVIGATING}:
                raise IllegalTransitionError("external occupancy requires an active claimed journey")
            context = self._require_context(journey_id)
            if current.version != expected_version:
                raise IllegalTransitionError("external occupancy used a stale journey version")
            if current.space_id is None:
                raise IllegalTransitionError("external occupancy requires an active claimed space")
            occupied_space_id = current.space_id
            failed = self._store.report_external_occupancy(
                journey_id=journey_id,
                expected_version=expected_version,
                idempotency_key=f"external-fail-{idempotency_key}",
            )
            driver = DriverRequest.model_validate(
                {**context.driver.model_dump(), "request_id": replacement_request_id, "idempotency_key": idempotency_key}
            )
            exclusions = self._scope_exclusions(
                session_id=driver.session_id,
                namespace=context.namespace,
                scenario_id=context.scenario_id,
                parking_lot_id=layout.parking_lot_id,
            )
            assert exclusions[occupied_space_id] == "EXTERNAL_SPACE_OCCUPIED"
            recommendation = self._online_rule.recommend(driver, layout, costs, data_source, excluded_space_reasons=exclusions, max_dynamic_eta_s=(self._max_driver_eta_s if context.namespace is SessionNamespace.DRIVER else None))
            if recommendation.solver_status == "success":
                assert recommendation.recommended_space_id is not None
                replacement_journey = self._store.soft_hold(
                    session_id=driver.session_id,
                    namespace=context.namespace,
                    scenario_id=context.scenario_id,
                    parking_lot_id=layout.parking_lot_id,
                    journey_id=replacement_journey_id,
                    attempt_id=replacement_attempt_id,
                    space_id=recommendation.recommended_space_id,
                    idempotency_key=f"external-replace-{idempotency_key}",
                )
                recommendation = Recommendation.model_validate(
                    {**recommendation.model_dump(), "claim_status": "soft_held", "soft_lock_expires_at": replacement_journey.expires_at}
                )
            else:
                replacement_journey = self._store.start_waiting(
                    session_id=driver.session_id,
                    namespace=context.namespace,
                    scenario_id=context.scenario_id,
                    parking_lot_id=layout.parking_lot_id,
                    journey_id=replacement_journey_id,
                    attempt_id=replacement_attempt_id,
                    idempotency_key=f"external-wait-{idempotency_key}",
                )
            replacement = JourneyRecommendationResult(recommendation=recommendation, journey=replacement_journey)
            self._contexts[replacement_journey_id] = _JourneyContext(
                driver=driver,
                namespace=context.namespace,
                scenario_id=context.scenario_id,
                result=replacement,
                excluded_space_reasons=context.excluded_space_reasons,
            )
            result = ExternalOccupancyResult(failed_journey=failed, replacement=replacement)
            self._external_idempotency[(journey_id, idempotency_key)] = _ExternalOccupancyReplay(
                payload_sha256=payload_hash, result=result
            )
            return result
    def reassign_after_driver_issue(
        self,
        *,
        journey_id: str,
        expected_version: int,
        reason: str,
        replacement_journey_id: str,
        replacement_attempt_id: str,
        replacement_request_id: str,
        layout: Layout,
        costs: CostSnapshot,
        data_source: DataSourceStatus,
        idempotency_key: str,
    ) -> ReassignmentResult:
        reason_codes = {"unable_to_park": "USER_UNABLE_TO_PARK", "eta_exceeds_reservation": "ETA_EXCEEDS_RESERVATION"}
        try:
            terminal_reason = reason_codes[reason]
        except KeyError as exc:
            raise ValueError("unsupported reassignment reason") from exc
        payload = {
            "journey_id": journey_id,
            "expected_version": expected_version,
            "reason": reason,
            "replacement_journey_id": replacement_journey_id,
            "replacement_attempt_id": replacement_attempt_id,
            "replacement_request_id": replacement_request_id,
            "layout_version": layout.layout_version,
            "cost_version": costs.cost_version,
        }
        payload_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        with self._store.atomic():
            replay = self._reassignment_idempotency.get((journey_id, idempotency_key))
            if replay is not None:
                if replay.payload_sha256 != payload_hash:
                    raise IdempotencyConflictError("reassignment idempotency key was reused with different input")
                return replay.result
        live = self._store.refresh_journey(journey_id)
        if live is None or live.state is not JourneyState.NAVIGATING:
            raise IllegalTransitionError("reassignment requires an active navigation")
        if live.version != expected_version:
            raise IllegalTransitionError("reassignment used a stale journey version")
        with self._store.atomic():
            replay = self._reassignment_idempotency.get((journey_id, idempotency_key))
            if replay is not None:
                if replay.payload_sha256 != payload_hash:
                    raise IdempotencyConflictError("reassignment idempotency key was reused with different input")
                return replay.result
            current = self._store.get_journey(journey_id)
            if current is None or current.state is not JourneyState.NAVIGATING:
                raise IllegalTransitionError("reassignment requires an active navigation")
            if current.version != expected_version:
                raise IllegalTransitionError("reassignment used a stale journey version")
            context = self._require_context(journey_id)
            old_space = current.space_id
            if old_space is None:
                raise IllegalTransitionError("reassignment requires a claimed space")
            ended = self._store.fail(
                journey_id=journey_id,
                expected_version=expected_version,
                idempotency_key=f"reassign-end-{idempotency_key}",
                reason=terminal_reason,
            )
            replacement_driver = DriverRequest.model_validate(
                {**context.driver.model_dump(), "request_id": replacement_request_id, "idempotency_key": idempotency_key}
            )
            next_exclusions = dict(context.excluded_space_reasons)
            next_exclusions[old_space] = terminal_reason
            replacement = self.recommend_and_hold(driver=replacement_driver, namespace=context.namespace, scenario_id=context.scenario_id, journey_id=replacement_journey_id, attempt_id=replacement_attempt_id, layout=layout, costs=costs, data_source=data_source, idempotency_key=f"reassign-replace-{idempotency_key}", additional_excluded_space_reasons=next_exclusions)
            result = ReassignmentResult(ended, replacement)
            self._reassignment_idempotency[(journey_id, idempotency_key)] = _ReassignmentReplay(payload_hash, result)
            return result
