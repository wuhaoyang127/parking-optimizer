"""Compose M2 recommendation with M3 atomic synthetic resource claims."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from parking_opt.api.models import (
    CostSnapshot,
    DataSourceStatus,
    DriverRequest,
    Journey,
    Layout,
    Recommendation,
)
from parking_opt.api.routing import RouteCostService
from parking_opt.api.services.online_rule import OnlineRuleServiceV2
from parking_opt.api.sessions import (
    IdempotencyConflictError,
    IllegalTransitionError,
    InMemorySessionStore,
    JourneyRecord,
    JourneyState,
    SessionNamespace,
)


@dataclass(frozen=True, slots=True)
class JourneyRecommendationResult:
    recommendation: Recommendation
    journey: JourneyRecord


@dataclass(frozen=True, slots=True)
class _RecommendationReplay:
    payload_sha256: str
    result: JourneyRecommendationResult


@dataclass(frozen=True, slots=True)
class _JourneyContext:
    driver: DriverRequest
    namespace: SessionNamespace
    scenario_id: str
    result: JourneyRecommendationResult
    excluded_space_reasons: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class _CommandReplay:
    payload_sha256: str
    result: JourneyRecommendationResult


@dataclass(frozen=True, slots=True)
class ExternalOccupancyResult:
    failed_journey: JourneyRecord
    replacement: JourneyRecommendationResult


@dataclass(frozen=True, slots=True)
class ReassignmentResult:
    ended_journey: JourneyRecord
    replacement: JourneyRecommendationResult


@dataclass(frozen=True, slots=True)
class DriverJourneyRecovery:
    observed_at: datetime
    driver: DriverRequest
    result: JourneyRecommendationResult


@dataclass(frozen=True, slots=True)
class DeclinedRecommendationResult:
    declined_journey: JourneyRecord
    replacement: JourneyRecommendationResult


@dataclass(frozen=True, slots=True)
class _ExternalOccupancyReplay:
    payload_sha256: str
    result: ExternalOccupancyResult


@dataclass(frozen=True, slots=True)
class _ReassignmentReplay:
    payload_sha256: str
    result: ReassignmentResult


class JourneyRecommendationService:
    """Evaluate visible state and create the resulting claim in one critical section."""

    def visible_driver_inputs(self, session_id: str) -> tuple[tuple[DriverRequest, JourneyRecord], ...]:
        """Return only this driver's already-created request/record pairs."""
        return tuple((context.driver, record)
            for record in self._store.session_journeys(session_id, SessionNamespace.DRIVER)
            if (context := self._contexts.get(record.journey_id)) is not None)

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
        self._command_idempotency: dict[tuple[str, str], _CommandReplay] = {}
        self._external_idempotency: dict[tuple[str, str], _ExternalOccupancyReplay] = {}
        self._reassignment_idempotency: dict[
            tuple[str, str], _ReassignmentReplay
        ] = {}
        self._decline_idempotency: dict[
            tuple[str, str], tuple[str, DeclinedRecommendationResult]
        ] = {}

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
        exclusions.update(
            {space_id: "APPLICATION_CLAIMED" for space_id in snapshot.claimed_space_ids}
        )
        return exclusions

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
                    self._max_driver_eta_s
                    if namespace is SessionNamespace.DRIVER
                    else None
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
            result = JourneyRecommendationResult(
                recommendation=recommendation,
                journey=journey,
            )
            self._idempotency[(driver.session_id, idempotency_key)] = _RecommendationReplay(
                payload_sha256=payload_hash,
                result=result,
            )
            self._contexts[journey_id] = _JourneyContext(
                driver=driver,
                namespace=namespace,
                scenario_id=scenario_id,
                result=result,
                excluded_space_reasons=tuple(
                    sorted((additional_excluded_space_reasons or {}).items())
                ),
            )
            return result

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
        """Release a rejected tandem hold and create a fresh attempt excluding that space."""

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
                    raise IdempotencyConflictError(
                        "tandem decline idempotency key was reused with different input"
                    )
                return replay[1]
            context = self._require_context(journey_id)
            current = self._store.refresh_journey(journey_id)
            if current is None or current.state is not JourneyState.SOFT_HELD:
                raise IllegalTransitionError("tandem decline requires an active soft hold")
            if current.version != expected_version:
                raise IllegalTransitionError("tandem decline used a stale journey version")
            rejected_space = current.space_id
            tandem_ids = {
                space_id
                for group in layout.tandem_groups
                for space_id in group.space_ids_near_to_deep
            }
            if rejected_space is None or rejected_space not in tandem_ids:
                raise ValueError("only a tandem recommendation can use tandem decline")
            declined = self._store.confirm(
                journey_id=journey_id,
                accepted=False,
                expected_version=expected_version,
                idempotency_key=f"decline-{idempotency_key}",
            )
            replacement_driver = DriverRequest.model_validate(
                {
                    **context.driver.model_dump(),
                    "request_id": replacement_request_id,
                    "idempotency_key": idempotency_key,
                }
            )
            next_exclusions = dict(context.excluded_space_reasons)
            next_exclusions[rejected_space] = "USER_DECLINED_TANDEM"
            replacement = self.recommend_and_hold(
                driver=replacement_driver,
                namespace=context.namespace,
                scenario_id=context.scenario_id,
                journey_id=replacement_journey_id,
                attempt_id=replacement_attempt_id,
                layout=layout,
                costs=costs,
                data_source=data_source,
                idempotency_key=f"replacement-{idempotency_key}",
                additional_excluded_space_reasons=next_exclusions,
            )
            result = DeclinedRecommendationResult(declined, replacement)
            self._decline_idempotency[(journey_id, idempotency_key)] = (
                payload_hash,
                result,
            )
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
        """Atomically switch a live hold and return a route consistent with the new space."""

        payload_hash = self._command_payload_sha256(
            journey_id=journey_id,
            expected_version=expected_version,
            space_id=space_id,
            layout=layout,
            costs=costs,
        )
        with self._store.atomic():
            replay = self._command_idempotency.get(
                (journey_id, f"select-alternative:{idempotency_key}")
            )
            if replay is not None:
                if replay.payload_sha256 != payload_hash:
                    raise IdempotencyConflictError(
                        "alternative idempotency key was reused with different input"
                    )
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
                item
                for item in (current.recommended_space_id, *current.alternative_space_ids)
                if item is not None and item != space_id
            )[:1]
            recommendation = Recommendation.model_validate(
                {
                    **current.model_dump(),
                    "recommended_space_id": space_id,
                    "alternative_space_ids": alternatives,
                    "route": route,
                    "soft_lock_expires_at": journey.expires_at,
                    "explanation_codes": (
                        *current.explanation_codes,
                        "USER_SELECTED_ALTERNATIVE",
                    ),
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
        """Re-evaluate a WAITING journey only when an explicit client action calls it."""

        payload_hash = self._command_payload_sha256(
            journey_id=journey_id,
            expected_version=expected_version,
            space_id=None,
            layout=layout,
            costs=costs,
        )
        with self._store.atomic():
            replay = self._command_idempotency.get(
                (journey_id, f"retry-waiting:{idempotency_key}")
            )
            if replay is not None:
                if replay.payload_sha256 != payload_hash:
                    raise IdempotencyConflictError(
                        "waiting retry idempotency key was reused with different input"
                    )
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
            recommendation = self._online_rule.recommend(
                context.driver,
                layout,
                costs,
                data_source,
                excluded_space_reasons=exclusions,
                max_dynamic_eta_s=(
                    self._max_driver_eta_s
                    if record.namespace is SessionNamespace.DRIVER
                    else None
                ),
            )
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
                    {
                        **recommendation.model_dump(),
                        "claim_status": "soft_held",
                        "soft_lock_expires_at": journey.expires_at,
                    }
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
        """Fail the old attempt and create a replacement while excluding the occupied space."""

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
                    raise IdempotencyConflictError(
                        "external occupancy key was reused with different input"
                    )
                return replay.result
        live = self._store.refresh_journey(journey_id)
        if live is None or live.state not in {
            JourneyState.SOFT_HELD,
            JourneyState.SESSION_RESERVED,
            JourneyState.NAVIGATING,
        }:
            raise IllegalTransitionError(
                "external occupancy requires an active claimed journey"
            )
        with self._store.atomic():
            replay = self._external_idempotency.get((journey_id, idempotency_key))
            if replay is not None:
                if replay.payload_sha256 != payload_hash:
                    raise IdempotencyConflictError(
                        "external occupancy key was reused with different input"
                    )
                return replay.result
            current = self._store.get_journey(journey_id)
            if current is None or current.state not in {
                JourneyState.SOFT_HELD,
                JourneyState.SESSION_RESERVED,
                JourneyState.NAVIGATING,
            }:
                raise IllegalTransitionError(
                    "external occupancy requires an active claimed journey"
                )
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
                {
                    **context.driver.model_dump(),
                    "request_id": replacement_request_id,
                    "idempotency_key": idempotency_key,
                }
            )
            exclusions = self._scope_exclusions(
                session_id=driver.session_id,
                namespace=context.namespace,
                scenario_id=context.scenario_id,
                parking_lot_id=layout.parking_lot_id,
            )
            assert exclusions[occupied_space_id] == "EXTERNAL_SPACE_OCCUPIED"
            recommendation = self._online_rule.recommend(
                driver,
                layout,
                costs,
                data_source,
                excluded_space_reasons=exclusions,
                max_dynamic_eta_s=(
                    self._max_driver_eta_s
                    if context.namespace is SessionNamespace.DRIVER
                    else None
                ),
            )
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
                    {
                        **recommendation.model_dump(),
                        "claim_status": "soft_held",
                        "soft_lock_expires_at": replacement_journey.expires_at,
                    }
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
            replacement = JourneyRecommendationResult(
                recommendation=recommendation,
                journey=replacement_journey,
            )
            self._contexts[replacement_journey_id] = _JourneyContext(
                driver=driver,
                namespace=context.namespace,
                scenario_id=context.scenario_id,
                result=replacement,
                excluded_space_reasons=context.excluded_space_reasons,
            )
            result = ExternalOccupancyResult(
                failed_journey=failed,
                replacement=replacement,
            )
            self._external_idempotency[(journey_id, idempotency_key)] = (
                _ExternalOccupancyReplay(payload_sha256=payload_hash, result=result)
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
        """End a navigating attempt and re-recommend without a physical fault claim."""

        reason_codes = {
            "unable_to_park": "USER_UNABLE_TO_PARK",
            "eta_exceeds_reservation": "ETA_EXCEEDS_RESERVATION",
        }
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
                    raise IdempotencyConflictError(
                        "reassignment idempotency key was reused with different input"
                    )
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
                    raise IdempotencyConflictError(
                        "reassignment idempotency key was reused with different input"
                    )
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
                {
                    **context.driver.model_dump(),
                    "request_id": replacement_request_id,
                    "idempotency_key": idempotency_key,
                }
            )
            next_exclusions = dict(context.excluded_space_reasons)
            next_exclusions[old_space] = terminal_reason
            replacement = self.recommend_and_hold(
                driver=replacement_driver,
                namespace=context.namespace,
                scenario_id=context.scenario_id,
                journey_id=replacement_journey_id,
                attempt_id=replacement_attempt_id,
                layout=layout,
                costs=costs,
                data_source=data_source,
                idempotency_key=f"reassign-replace-{idempotency_key}",
                additional_excluded_space_reasons=next_exclusions,
            )
            result = ReassignmentResult(ended, replacement)
            self._reassignment_idempotency[(journey_id, idempotency_key)] = (
                _ReassignmentReplay(payload_hash, result)
            )
            return result

    def _require_context(self, journey_id: str) -> _JourneyContext:
        try:
            return self._contexts[journey_id]
        except KeyError as exc:
            raise ValueError(
                f"journey recommendation context is unavailable: {journey_id}"
            ) from exc

    def _remember_command(
        self,
        *,
        context: _JourneyContext,
        journey_id: str,
        key: str,
        payload_hash: str,
        result: JourneyRecommendationResult,
    ) -> None:
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
        encoded = json.dumps(
            payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def journey_to_contract(
    record: JourneyRecord, *, recommendation_id: str | None = None
) -> Journey:
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
