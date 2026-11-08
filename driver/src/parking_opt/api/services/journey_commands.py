"""Decline, alternative, and waiting-retry mixin for the journey service."""
from __future__ import annotations
import hashlib
import json
from parking_opt.api.models import CostSnapshot, DataSourceStatus, DriverRequest, Layout, Recommendation
from parking_opt.api.services.journey_types import (
    DeclinedRecommendationResult,
    JourneyRecommendationResult,
)
from parking_opt.api.sessions import IdempotencyConflictError, IllegalTransitionError, JourneyState, SessionNamespace
class JourneyCommandsMixin:
    def decline_tandem_and_recommend(
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
    ) -> DeclinedRecommendationResult:
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
            replay = self._decline_idempotency.get((journey_id, idempotency_key))
            if replay is not None:
                if replay[0] != payload_hash:
                    raise IdempotencyConflictError("tandem decline idempotency key was reused with different input")
                return replay[1]
            context = self._require_context(journey_id)
            current = self._store.refresh_journey(journey_id)
            if current is None or current.state is not JourneyState.SOFT_HELD:
                raise IllegalTransitionError("tandem decline requires an active soft hold")
            if current.version != expected_version:
                raise IllegalTransitionError("tandem decline used a stale journey version")
            rejected_space = current.space_id
            tandem_ids = {space_id for group in layout.tandem_groups for space_id in group.space_ids_near_to_deep}
            if rejected_space is None or rejected_space not in tandem_ids:
                raise ValueError("only a tandem recommendation can use tandem decline")
            declined = self._store.confirm(
                journey_id=journey_id,
                accepted=False,
                expected_version=expected_version,
                idempotency_key=f"decline-{idempotency_key}",
            )
            replacement_driver = DriverRequest.model_validate(
                {**context.driver.model_dump(), "request_id": replacement_request_id, "idempotency_key": idempotency_key}
            )
            next_exclusions = dict(context.excluded_space_reasons)
            next_exclusions[rejected_space] = "USER_DECLINED_TANDEM"
            replacement = self.recommend_and_hold(driver=replacement_driver, namespace=context.namespace, scenario_id=context.scenario_id, journey_id=replacement_journey_id, attempt_id=replacement_attempt_id, layout=layout, costs=costs, data_source=data_source, idempotency_key=f"replacement-{idempotency_key}", additional_excluded_space_reasons=next_exclusions)
            result = DeclinedRecommendationResult(declined, replacement)
            self._decline_idempotency[(journey_id, idempotency_key)] = (payload_hash, result)
            return result
    def select_alternative(
        self,
        *,
        journey_id: str,
        space_id: str,
        expected_version: int,
        layout: Layout,
        costs: CostSnapshot,
        idempotency_key: str,
    ) -> JourneyRecommendationResult:
        payload_hash = self._command_payload_sha256(
            journey_id=journey_id,
            expected_version=expected_version,
            space_id=space_id,
            layout=layout,
            costs=costs,
        )
        with self._store.atomic():
            replay = self._command_idempotency.get((journey_id, f"select-alternative:{idempotency_key}"))
            if replay is not None:
                if replay.payload_sha256 != payload_hash:
                    raise IdempotencyConflictError("alternative idempotency key was reused with different input")
                return replay.result
            context = self._require_context(journey_id)
            current = context.result.recommendation
            if space_id not in current.alternative_space_ids:
                raise ValueError("space_id is not an available recommendation alternative")
            spaces = {item.space_id: item for item in layout.spaces}
            if space_id not in spaces:
                raise ValueError("alternative space is not present in the current layout")
            if current.route is None:
                raise IllegalTransitionError("waiting recommendation has no alternative route")
            route = self._routes.route(
                layout,
                costs,
                from_node_id=current.route.from_node_id,
                to_node_id=spaces[space_id].access_node_id,
            )
            journey = self._store.switch_soft_hold(
                journey_id=journey_id,
                expected_version=expected_version,
                space_id=space_id,
                idempotency_key=idempotency_key,
            )
            alternatives = tuple(
                item for item in (current.recommended_space_id, *current.alternative_space_ids)
                if item is not None and item != space_id
            )[:1]
            recommendation = Recommendation.model_validate(
                {
                    **current.model_dump(),
                    "recommended_space_id": space_id,
                    "alternative_space_ids": alternatives,
                    "route": route,
                    "soft_lock_expires_at": journey.expires_at,
                    "explanation_codes": (*current.explanation_codes, "USER_SELECTED_ALTERNATIVE"),
                }
            )
            result = JourneyRecommendationResult(recommendation, journey)
            self._remember_command(
                context=context,
                journey_id=journey_id,
                key=f"select-alternative:{idempotency_key}",
                payload_hash=payload_hash,
                result=result,
            )
            return result
    def retry_waiting(
        self,
        *,
        journey_id: str,
        expected_version: int,
        layout: Layout,
        costs: CostSnapshot,
        data_source: DataSourceStatus,
        idempotency_key: str,
    ) -> JourneyRecommendationResult:
        payload_hash = self._command_payload_sha256(
            journey_id=journey_id,
            expected_version=expected_version,
            space_id=None,
            layout=layout,
            costs=costs,
        )
        with self._store.atomic():
            replay = self._command_idempotency.get((journey_id, f"retry-waiting:{idempotency_key}"))
            if replay is not None:
                if replay.payload_sha256 != payload_hash:
                    raise IdempotencyConflictError("waiting retry idempotency key was reused with different input")
                return replay.result
            context = self._require_context(journey_id)
            record = self._store.get_journey(journey_id)
            if record is None or record.state is not JourneyState.WAITING:
                raise IllegalTransitionError("only a waiting journey can be retried")
            exclusions = self._scope_exclusions(
                session_id=record.session_id,
                namespace=record.namespace,
                scenario_id=record.scenario_id,
                parking_lot_id=record.parking_lot_id,
            )
            exclusions.update(dict(context.excluded_space_reasons))
            recommendation = self._online_rule.recommend(context.driver, layout, costs, data_source, excluded_space_reasons=exclusions, max_dynamic_eta_s=(self._max_driver_eta_s if record.namespace is SessionNamespace.DRIVER else None))
            selected = (
                recommendation.recommended_space_id
                if recommendation.solver_status == "success"
                else None
            )
            journey = self._store.retry_waiting(
                journey_id=journey_id,
                expected_version=expected_version,
                space_id=selected,
                idempotency_key=idempotency_key,
            )
            if selected is not None:
                recommendation = Recommendation.model_validate(
                    {**recommendation.model_dump(), "claim_status": "soft_held", "soft_lock_expires_at": journey.expires_at}
                )
            result = JourneyRecommendationResult(recommendation, journey)
            self._remember_command(
                context=context,
                journey_id=journey_id,
                key=f"retry-waiting:{idempotency_key}",
                payload_hash=payload_hash,
                result=result,
            )
            return result
