"""推送到车主端：最优算法选择纯函数测试（不启动 Streamlit）。"""

import sys
from pathlib import Path

# app.py 运行时会注入 src；测试环境手动注入后即可导入 ui 包
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ui.pages import _best_algo_from_runs  # noqa: E402
from parking_opt.evaluation.ranking import DEFAULT_WEIGHTS  # noqa: E402


def _metrics(strategy, *, sat=0.8, util=0.7, wait=200.0, shifts=10,
             dist=100.0, drive=1500.0, runtime=2.0):
    return {"strategy": strategy, "satisfaction_rate": sat,
            "spatial_utilization": util, "avg_wait_time_s": wait,
            "shift_count": shifts, "shift_distance_m": dist,
            "total_drive_distance_m": drive, "runtime_s": runtime}


def test_best_algo_prefers_recent_compare_all():
    """最近一次「全部对比」结果优先于任何单策略记录。"""
    runs = [
        {"strategy": "algo_b", "metrics": _metrics("algo_b", sat=0.99),
         "created_at": "2026-09-11T12:00:00+00:00"},
        {"strategy": "compare_all",
         "metrics": [_metrics("algo_a", sat=0.6), _metrics("algo_b", sat=0.9)],
         "created_at": "2026-09-10T12:00:00+00:00"},
    ]
    best, ranked, source = _best_algo_from_runs(runs, DEFAULT_WEIGHTS)
    assert best == "algo_b"
    assert source == "最近一次「全部对比」"
    assert ranked[0]["strategy"] == "algo_b"
    assert ranked[0]["rank"] == 1


def test_best_algo_falls_back_to_single_run_average():
    """无全部对比记录时，用单策略运行平均参与排名。"""
    runs = [
        {"strategy": "algo_a", "metrics": _metrics("algo_a", sat=0.9, wait=100.0),
         "created_at": "2026-09-11T10:00:00+00:00"},
        {"strategy": "algo_b", "metrics": _metrics("algo_b", sat=0.7, wait=300.0),
         "created_at": "2026-09-11T09:00:00+00:00"},
    ]
    best, ranked, source = _best_algo_from_runs(runs, DEFAULT_WEIGHTS)
    assert best == "algo_a"
    assert "平均" in source
    assert ranked[0]["strategy"] == "algo_a"


def test_best_algo_empty_when_no_usable_records():
    """无记录、metrics 为空列表、全部非 dict 时返回空。"""
    assert _best_algo_from_runs([], DEFAULT_WEIGHTS) == (None, [], "")
    assert _best_algo_from_runs(
        [{"strategy": "compare_all", "metrics": [], "created_at": "x"}],
        DEFAULT_WEIGHTS) == (None, [], "")
    assert _best_algo_from_runs(
        [{"strategy": "algo_a", "metrics": "bad", "created_at": "x"}],
        DEFAULT_WEIGHTS) == (None, [], "")


def test_best_algo_ignores_metrics_without_strategy_key():
    """compare_all 的 metrics 列表中缺 strategy 的脏数据被过滤。"""
    runs = [
        {"strategy": "compare_all",
         "metrics": [{"satisfaction_rate": 0.99},
                     _metrics("algo_a", sat=0.8)],
         "created_at": "2026-09-11T10:00:00+00:00"},
    ]
    best, ranked, source = _best_algo_from_runs(runs, DEFAULT_WEIGHTS)
    assert best == "algo_a"
    assert len(ranked) == 1
