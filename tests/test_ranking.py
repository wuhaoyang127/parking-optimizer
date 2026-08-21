"""加权多指标排名测试"""

import pytest

from src.parking_opt.evaluation.ranking import (DEFAULT_WEIGHTS, METRIC_DIRECTIONS,
                                                normalize_weights, weighted_rank)


def base_metrics():
    """两个策略：A 在 max 指标上更好，B 在 min 指标上更好。"""
    return [
        {"strategy": "A", "satisfaction_rate": 0.9, "spatial_utilization": 0.8,
         "avg_wait_time_s": 300.0, "shift_count": 5, "shift_distance_m": 50.0,
         "total_drive_distance_m": 1000.0, "runtime_s": 0.5},
        {"strategy": "B", "satisfaction_rate": 0.7, "spatial_utilization": 0.6,
         "avg_wait_time_s": 100.0, "shift_count": 1, "shift_distance_m": 10.0,
         "total_drive_distance_m": 800.0, "runtime_s": 0.2},
    ]


class TestNormalizeWeights:
    def test_sum_to_one(self):
        w = normalize_weights({"satisfaction_rate": 30, "spatial_utilization": 70})
        assert sum(w.values()) == pytest.approx(1.0)

    def test_negative_clipped_to_zero(self):
        w = normalize_weights({"satisfaction_rate": -5, "spatial_utilization": 10})
        assert w["satisfaction_rate"] == 0.0
        assert sum(w.values()) == pytest.approx(1.0)

    def test_unknown_keys_ignored(self):
        w = normalize_weights({"satisfaction_rate": 10, "not_a_metric": 90})
        assert "not_a_metric" not in w
        assert w["satisfaction_rate"] == pytest.approx(1.0)

    def test_all_zero_returns_empty(self):
        assert normalize_weights({"satisfaction_rate": 0}) == {}

    def test_default_weights_sum_to_100(self):
        assert sum(DEFAULT_WEIGHTS.values()) == pytest.approx(100.0)


class TestWeightedRank:
    def test_max_direction_higher_better(self):
        metrics = base_metrics()
        result = weighted_rank(metrics, {"satisfaction_rate": 100})
        assert result[0]["strategy"] == "A"
        assert result[0]["rank"] == 1
        assert result[1]["rank"] == 2

    def test_min_direction_lower_better(self):
        metrics = base_metrics()
        result = weighted_rank(metrics, {"avg_wait_time_s": 100})
        assert result[0]["strategy"] == "B"

    def test_score_in_0_to_1(self):
        result = weighted_rank(base_metrics(), DEFAULT_WEIGHTS)
        for row in result:
            assert 0.0 <= row["weighted_score"] <= 1.0

    def test_no_discrimination_metric_gets_neutral(self):
        # shift_count 两策略相同 → 归一化记 0.5；只给该指标权重时两人得分相同
        metrics = base_metrics()
        metrics[1]["shift_count"] = metrics[0]["shift_count"]
        result = weighted_rank(metrics, {"shift_count": 100})
        assert result[0]["weighted_score"] == pytest.approx(result[1]["weighted_score"])
        assert result[0]["weighted_score"] == pytest.approx(0.5)

    def test_invalid_weights_keep_input_order(self):
        result = weighted_rank(base_metrics(), {"satisfaction_rate": 0})
        assert [r["strategy"] for r in result] == ["A", "B"]
        assert all(r["weighted_score"] is None for r in result)

    def test_empty_input(self):
        assert weighted_rank([], DEFAULT_WEIGHTS) == []

    def test_does_not_mutate_input(self):
        metrics = base_metrics()
        snapshot = [dict(m) for m in metrics]
        weighted_rank(metrics, DEFAULT_WEIGHTS)
        assert metrics == snapshot

    def test_metric_directions_match_expected(self):
        # 方向表与 UI 常量一致性由本测试锁定（防止单边修改）
        assert METRIC_DIRECTIONS["satisfaction_rate"] == "max"
        assert METRIC_DIRECTIONS["avg_wait_time_s"] == "min"
        assert set(METRIC_DIRECTIONS) == {
            "satisfaction_rate", "spatial_utilization", "avg_wait_time_s",
            "shift_count", "shift_distance_m", "total_drive_distance_m", "runtime_s",
        }
