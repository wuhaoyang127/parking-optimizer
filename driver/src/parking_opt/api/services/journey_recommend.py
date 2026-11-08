"""Recommend-and-hold mixin for the journey service."""

from __future__ import annotations

from parking_opt.api.models import (
    CostSnapshot,
    DataSourceStatus,
    DriverRequest,
    Layout,
    Recommendation,
)
from parking_opt.api.services.journey_types import (
    JourneyRecommendationResult,
    _JourneyContext,
    _RecommendationReplay,
)
from parking_opt.api.sessions import IdempotencyConflictError, SessionNamespace


class JourneyRecommendMixin:
    def recommend_and_hold(
        self,
        *,
        driver: DriverRequest,
        namespace: SessionNamespace,
        scenario_id: str,
        journey_id: str,
        attempt_id: str,
        layout: Layout,
        costs: CostSnapshot,
        data_source: DataSourceStatus,
        idempotency_key: str,
        additional_excluded_space_reasons: dict[str, str] | None = None,
    ) -> JourneyRecommendationResult:
        payload_hash = self._payload_sha256(
            driver=driver,
            namespace=namespace,
            scenario_id=scenario_id,
            journey_id=journey_id,
            attempt_id=attempt_id,
            layout=layout,
            costs=costs,
            additional_excluded_space_reasons=additional_excluded_space_reasons,
        )
        with self._store.atomic():
            replay = self._idempotency.get((driver.session_id, idempotency_key))
            if replay is not None:
                if replay.payload_sha256 != payload_hash:
                    raise IdempotencyConflictError(
                        "recommendation idempotency key was reused with different input"
                    )
                return replay.result
            exclusions = self._scope_exclusions(
                session_id=driver.session_id,
                namespace=namespace,
                scenario_id=scenario_id,
                parking_lot_id=layout.parking_lot_id,
            )
            exclusions.update(additional_excluded_space_reasons or {})
            recommendation = self._online_rule.recommend(
                driver,
                layout,
                costs,
                data_source,
                excluded_space_reasons=exclusions,
                max_dynamic_eta_s=(
                    self._max_driver_eta_s if namespace is SessionNamespace.DRIVER else None
                ),
            )
            if recommendation.solver_status == "success":
                assert recommendation.recommended_space_id is not None
                journey = self._store.soft_hold(
                    session_id=driver.session_id,
                    namespace=namespace,
                    scenario_id=scenario_id,
                    parking_lot_id=layout.parking_lot_id,
                    journey_id=journey_id,
                    attempt_id=attempt_id,
                    space_id=recommendation.recommended_space_id,
                    idempotency_key=idempotency_key,
                )
                recommendation = Recommendation.model_validate(
                    {
                        **recommendation.model_dump(),
                        "claim_status": "soft_held",
                        "soft_lock_expires_at": journey.expires_at,
                    }
                )
            else:
                journey = self._store.start_waiting(
                    session_id=driver.session_id,
                    namespace=namespace,
                    scenario_id=scenario_id,
                    parking_lot_id=layout.parking_lot_id,
                    journey_id=journey_id,
                    attempt_id=attempt_id,
                    idempotency_key=idempotency_key,
                )
            result = JourneyRecommendationResult(recommendation=recommendation, journey=journey)
            self._idempotency[(driver.session_id, idempotency_key)] = _RecommendationReplay(
                payload_sha256=payload_hash,
                result=result,
            )
            self._contexts[journey_id] = _JourneyContext(
                driver=driver,
                namespace=namespace,
                scenario_id=scenario_id,
                result=result,
                excluded_space_reasons=tuple(sorted((additional_excluded_space_reasons or {}).items())),
            )
            return result
