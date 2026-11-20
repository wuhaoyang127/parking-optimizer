"""Serialization and validation at the immutable C3 policy boundary."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from parking_opt.contracts.schema_validation import SchemaCatalog
from parking_opt.contracts.semantic_validation import validate_decision_request_semantics
from parking_opt.contracts.snapshot_projection import observed_snapshot_to_mapping
from parking_opt.domain.conversion import decision_result_to_mapping
from parking_opt.domain.records import DecisionRequest, DecisionResult


def thaw_json(value: object) -> Any:
    """Copy an immutable JSON-like value into schema-validator containers."""

    if isinstance(value, Mapping):
        return {str(key): thaw_json(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(child) for child in value]
    return value


def decision_request_to_mapping(request: DecisionRequest) -> dict[str, Any]:
    """Serialize exactly the approved v1 decision-request envelope."""

    return {
        "record_type": "decision_request",
        "schema_version": "1.0.0",
        "request_id": request.request_id,
        "algorithm_id": request.algorithm_id,
        "algorithm_version": request.algorithm_version,
        "config_sha256": request.config_sha256,
        "layout_sha256": request.layout_sha256,
        "visible_snapshot_sha256": request.visible_snapshot_sha256,
        "decision_time_s": request.decision_time_s,
        "trigger_event_id": request.trigger_event_id,
        "trigger_event_type": request.trigger_event_type,
        "trigger_request_id": request.trigger_request_id,
        "trigger_anonymous_vehicle_id": request.trigger_anonymous_vehicle_id,
        "decision_target_s": request.decision_target_s,
        "decision_deadline_s": request.decision_deadline_s,
        "approved_config": thaw_json(request.approved_config),
        "layout": thaw_json(request.layout),
        "observed_snapshot": observed_snapshot_to_mapping(request.observed_snapshot),
    }


def validate_decision_request(request: DecisionRequest, catalog: SchemaCatalog) -> None:
    """Run structural, hash, trigger, and information-boundary checks."""

    mapping = decision_request_to_mapping(request)
    catalog.validate("decision.schema.json", mapping)
    validate_decision_request_semantics(mapping)


def validate_decision_request_semantics_only(request: DecisionRequest) -> None:
    """轻量校验：只跑语义检查，跳过对 4.5 万条 path_costs 的 JSON Schema 结构校验。

    结构形状由 v1 适配器构造时保证（契约模型 + assert_state_invariants），
    语义检查仍保留路径唯一性、边序列、距离一致性与信息边界等关键不变量。
    """

    validate_decision_request_semantics(decision_request_to_mapping(request))


def validate_decision_result(result: DecisionResult, catalog: SchemaCatalog) -> None:
    """Validate the frozen result envelope before it leaves the policy."""

    catalog.validate("decision.schema.json", decision_result_to_mapping(result))


class DecisionPolicy(Protocol):
    """A policy with no simulator, truth-store, or graph-object access path."""

    def decide(self, request: DecisionRequest) -> DecisionResult:
        """Return one validated candidate without mutating the request."""
        ...
