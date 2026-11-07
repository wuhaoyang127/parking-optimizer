"""Explicit algorithm registry: only implemented services are selectable."""

from __future__ import annotations

from parking_opt.api.models import AlgorithmDescriptor, AlgorithmStatus


def algorithm_registry() -> tuple[AlgorithmDescriptor, ...]:
    return (
        AlgorithmDescriptor(
            algorithm_id="online-rule-v2",
            version="2.0.0",
            display_name="在线规则推荐",
            category="rule",
            status=AlgorithmStatus.ONLINE,
            required_inputs=("layout", "space_status", "current_edge_costs"),
        ),
        AlgorithmDescriptor(
            algorithm_id="simulated-annealing",
            version="pending",
            display_name="模拟退火",
            category="metaheuristic",
            status=AlgorithmStatus.PENDING,
            required_inputs=("frozen_model", "calibrated_parameters"),
            pending_reason="尚未完成与在线信息边界一致的实现和验收",
        ),
        AlgorithmDescriptor(
            algorithm_id="random-forest",
            version="pending",
            display_name="随机森林",
            category="machine_learning",
            status=AlgorithmStatus.PENDING,
            required_inputs=("training_data", "feature_contract", "model_lineage"),
            pending_reason="尚无经过验证的训练数据、特征契约和模型产物",
        ),
    )


def require_online_algorithm(algorithm_id: str) -> AlgorithmDescriptor:
    descriptor = next(
        (item for item in algorithm_registry() if item.algorithm_id == algorithm_id), None
    )
    if descriptor is None:
        raise ValueError(f"unknown algorithm_id: {algorithm_id}")
    if descriptor.status is not AlgorithmStatus.ONLINE:
        raise ValueError(f"algorithm {algorithm_id} is pending and cannot be selected")
    return descriptor
