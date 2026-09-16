"""worker_compute.run_local_task 三动作组合回归测试。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import src.parking_opt.strategies  # noqa: F401  触发注册
import worker_compute  # noqa: E402


def _payload(strategy, n_vehicles=8):
    return {
        "layout": {"source": "builtin", "builtin_key": "linear",
                   "n_spots": 6, "tandem_ratio": 0.5},
        "demand": {"source": "generated", "generator": {
            "total_vehicles": n_vehicles, "sim_duration": 3600,
            "duration_min": 600, "duration_max": 1800,
            "peak_ratio": 0.3, "error_ratio": 0.1}},
        "strategy": strategy,
        "ranking": {"mode": "加权评分", "weights": {}, "priority": []},
        "engine": {"wait_policy": "fifo", "car_speed": 1.39,
                   "max_wait_time": 600, "seed": 5, "n_runs": 1,
                   "random_reps": 100, "budget": 60.0},
    }


def _single_strategy(**flags):
    return {"name": "duration_greedy", "params": {}, "category": "classic", **flags}


def test_run_default_single_produces_metrics():
    """只勾「按当前参数跑仿真」：跑正式仿真并返回指标。"""
    res = worker_compute.run_local_task(_payload(_single_strategy(run_default=True)))
    assert res["mode"] == "single"
    assert res["metrics"] and res["metrics"]["strategy"] == "duration_greedy"
    assert res.get("tuned_params") in (None, {})


def test_tune_only_single_returns_best_params_without_metrics():
    """只勾「自动调参选最优」：回传最优参数，不跑正式仿真。"""
    res = worker_compute.run_local_task(
        _payload(_single_strategy(run_default=False, auto_tune=True,
                                  tune_run=False, tune_trials=5)))
    assert res["mode"] == "single"
    assert res["metrics"] is None
    assert "duration_greedy" in res["tuned_params"]
    assert res["tune_trials_count"] == 5
    assert len(res["tune_trials"]) == 5


def test_tune_then_run_single_uses_best_params():
    """勾「自动调参 + 用最优参数跑仿真」：调参后跑正式仿真。"""
    res = worker_compute.run_local_task(
        _payload(_single_strategy(run_default=False, auto_tune=True,
                                  tune_run=True, tune_trials=5)))
    assert res["mode"] == "single"
    assert res["metrics"] and res["metrics"]["strategy"] == "duration_greedy"
    assert "duration_greedy" in res["tuned_params"]


def test_compare_all_default_only():
    """全部对比只勾「按当前参数跑排序」：只跑默认参数组。"""
    strategy = {"name": "compare_all", "params": {}, "category": "classic",
                "run_default": True, "auto_tune": False, "tune_run": False}
    res = worker_compute.run_local_task(_payload(strategy, n_vehicles=6))
    assert res["mode"] == "compare_all"
    assert len(res["all_m"]) >= 2
    assert res["tuned_m"] == []


def test_compare_all_tune_only_saves_best_params():
    """全部对比只勾「自动调参选最优」：只调参保存各算法最优参数。"""
    strategy = {"name": "compare_all", "params": {}, "category": "classic",
                "run_default": False, "auto_tune": True, "tune_run": False,
                "tune_trials": 5}
    res = worker_compute.run_local_task(_payload(strategy, n_vehicles=6))
    assert res["mode"] == "compare_all"
    assert res["metrics"] is None
    assert len(res["tuned_params"]) >= 1
    assert res["tune_trials_count"] == 5
