from __future__ import annotations
"""加权多指标排名：min-max 归一化 + 方向处理 + 权重加权求和。

纯函数模块，不依赖 UI。指标字段名与 evaluation/metrics.py 的输出一致。
方向 "max"=越大越好；"min"=越小越好（归一化时反向，使所有指标得分越高越好）。
"""

from typing import Iterable

# 指标方向表：字段名 -> 方向（与 ui/common.py 的 PRIORITY_METRICS 保持一致，此处不依赖 UI 层）
METRIC_DIRECTIONS: dict[str, str] = {
    "satisfaction_rate": "max",
    "spatial_utilization": "max",
    "avg_wait_time_s": "min",
    "shift_count": "min",
    "shift_distance_m": "min",
    "total_drive_distance_m": "min",
    "runtime_s": "min",
}

DEFAULT_WEIGHTS: dict[str, float] = {
    "satisfaction_rate": 30.0,
    "spatial_utilization": 25.0,
    "avg_wait_time_s": 15.0,
    "shift_count": 10.0,
    "shift_distance_m": 10.0,
    "total_drive_distance_m": 5.0,
    "runtime_s": 5.0,
}


def normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    """把权重归一化到总和为 1。

    - 只保留 METRIC_DIRECTIONS 中存在的键；
    - 负数按 0 处理；
    - 总和 <= 0 时返回 None 由调用方决定（本函数返回全 0 字典并标记 invalid）。
    """
    cleaned = {k: max(float(weights.get(k, 0.0)), 0.0) for k in METRIC_DIRECTIONS}
    total = sum(cleaned.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in cleaned.items()}


def weighted_rank(metrics_list: list[dict], weights: dict[str, float]) -> list[dict]:
    """对多个策略的指标 dict 做加权评分排名。

    参数:
        metrics_list: 每个元素至少包含 "strategy" 键和参与评分的指标字段。
        weights: 各指标权重（百分值或任意正数），内部自动按总和归一化；总和<=0 时返回原顺序且得分 None。

    返回:
        按加权得分降序排列的新列表，每个 dict 增加 "weighted_score"（保留 4 位）和 "rank"（从 1 开始）。
        当某个指标在所有策略中 max==min 时，该指标归一化值统一记 0.5（无区分度）。
    """
    if not metrics_list:
        return []

    norm_weights = normalize_weights(weights)
    if not norm_weights:
        # 权重无效：不评分，按输入顺序给 rank
        out = [dict(m) for m in metrics_list]
        for i, row in enumerate(out):
            row["weighted_score"] = None
            row["rank"] = i + 1
        return out

    fields = list(METRIC_DIRECTIONS.keys())

    # min-max 归一化（方向处理）
    norm_values: dict[str, list[float]] = {}
    for field in fields:
        direction = METRIC_DIRECTIONS[field]
        vals = [float(m.get(field, 0.0)) for m in metrics_list]
        lo, hi = min(vals), max(vals)
        if hi == lo:
            norm_values[field] = [0.5] * len(vals)
        elif direction == "min":
            norm_values[field] = [1.0 - (v - lo) / (hi - lo) for v in vals]
        else:
            norm_values[field] = [(v - lo) / (hi - lo) for v in vals]

    scored = []
    for idx, m in enumerate(metrics_list):
        score = sum(norm_values[field][idx] * norm_weights.get(field, 0.0)
                    for field in fields)
        scored.append((round(score, 4), idx, dict(m)))

    scored.sort(key=lambda x: (-x[0], x[1]))
    result = []
    for rank, (score, _, row) in enumerate(scored, start=1):
        row["weighted_score"] = score
        row["rank"] = rank
        result.append(row)
    return result


def metrics_field_names() -> list[str]:
    """返回参与评分的指标字段列表（顺序稳定）。"""
    return list(METRIC_DIRECTIONS.keys())
