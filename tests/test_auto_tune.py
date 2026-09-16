"""自动调参纯函数测试：采样、修复、选优、调参、分组运行。"""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import src.parking_opt.strategies  # noqa: F401  触发注册
from src.local_compute import (LAYOUT_BUILDERS, TUNE_TRIALS_DEFAULT, TUNE_TRIALS_MIN,
                               TUNE_BATCH_SIZE, best_trial,
                               resolve_strategy_flags, run_group, run_tuning,
                               sample_params, tunable_specs)
from src.parking_opt.simulation.arrival import generate_demand
from src.parking_opt.strategies import StrategyRegistry


def test_tunable_specs_excludes_locked():
    """locked 参数（如 MOSA 场景自动绑定）不参与调参。"""
    keys = {p["key"] for p in tunable_specs("mosa")}
    assert "scene" not in keys
    assert "pop_size" in keys


def test_sample_params_respects_ranges_and_types():
    """采样值必须在声明范围内，类型正确。"""
    rng = random.Random(7)
    for _ in range(100):
        params = sample_params("duration_greedy", rng)
        assert 600.0 <= params["threshold"] <= 7200.0
        assert 1 <= params["warmup"] <= 100
        assert isinstance(params["warmup"], int)


def test_sample_params_is_deterministic_given_rng():
    """相同随机源采样结果可复现。"""
    a = sample_params("risk_scoring", random.Random(42))
    b = sample_params("risk_scoring", random.Random(42))
    assert a == b


def test_sample_params_choice_and_strategy_types():
    """choice/strategy 类型采样自合法选项，float 在声明范围内。"""
    rng = random.Random(3)
    for _ in range(50):
        p = sample_params("peak_offpeak_fusion", rng)
        assert 0.0 <= p["peak_threshold"] <= 1.0
        assert p["peak_strategy"] in StrategyRegistry.all()
        assert p["offpeak_strategy"] in StrategyRegistry.all()


def test_sample_params_repairs_rho_thresholds():
    """RHO 采样后 mild_threshold 不得大于 severe_threshold。"""
    rng = random.Random(11)
    for _ in range(200):
        p = sample_params("rho_rolling", rng)
        assert p["mild_threshold"] <= p["severe_threshold"]


def test_best_trial_weighted_prefers_higher_satisfaction():
    """加权模式（满足率权重拉满）应选满足率更高的组。"""
    trials = [({"a": 1}, {"strategy": "x", "satisfaction_rate": 0.8}),
              ({"b": 2}, {"strategy": "x", "satisfaction_rate": 0.9})]
    weights = {"satisfaction_rate": 100.0}
    params, metrics = best_trial(trials, "加权评分", weights=weights)
    assert params == {"b": 2}
    assert metrics["satisfaction_rate"] == 0.9


def test_best_trial_lexicographic_priority():
    """字典序模式按 priority 字段比较（满足率越大越好）。"""
    trials = [({"a": 1}, {"strategy": "x", "satisfaction_rate": 0.8,
                          "shift_count": 0}),
              ({"b": 2}, {"strategy": "x", "satisfaction_rate": 0.9,
                          "shift_count": 99})]
    params, _metrics = best_trial(trials, "字典序",
                                  priority=["satisfaction_rate"])
    assert params == {"b": 2}


def test_run_tuning_returns_best_params_for_duration_greedy():
    """小布局上调参：返回最优参数与全部试跑记录。"""
    net, spots = LAYOUT_BUILDERS["linear"](6, 0.5)
    vehs = generate_demand(total_vehicles=8, seed=5)
    res = run_tuning("duration_greedy", net, spots, vehs, seed=5,
                     wait_policy="fifo",
                     eng_kwargs=dict(car_speed=1.39, max_wait_time=600),
                     trials=3)
    assert set(res["best_params"].keys()) == {"threshold", "warmup"}
    assert len(res["trials"]) == 3


def test_run_group_runs_default_and_tuned_groups():
    """分组运行：默认参数组与指定参数组都能产出每个策略的平均指标。"""
    net, spots = LAYOUT_BUILDERS["linear"](6, 0.5)
    demand_kwargs = dict(total_vehicles=8, sim_duration=3600,
                         duration_min=600, duration_max=1800,
                         peak_ratio=0.3, error_ratio=0.1)
    strategies = [("fcfs", StrategyRegistry.get("fcfs")),
                  ("duration_greedy", StrategyRegistry.get("duration_greedy"))]
    res = run_group(strategies, net, spots, None, demand_kwargs, seed=5,
                    wait_policy="fifo", eng_kwargs=dict(car_speed=1.39, max_wait_time=600),
                    n_runs_for=lambda n: 1)
    assert [m["strategy"] for m in res["all_m"]] == ["fcfs", "duration_greedy"]
    tuned = run_group(strategies, net, spots, None, demand_kwargs, seed=5,
                      wait_policy="fifo", eng_kwargs=dict(car_speed=1.39, max_wait_time=600),
                      n_runs_for=lambda n: 1,
                      params_by_strategy={"duration_greedy": {"threshold": 1200.0, "warmup": 5}})
    assert [m["strategy"] for m in tuned["all_m"]] == ["fcfs", "duration_greedy"]


def test_tune_trials_default_is_ten():
    """用户确认的 K=10 常量。"""
    assert TUNE_TRIALS_DEFAULT == 10


def test_tune_trials_min_is_five():
    """调参组数最少 5。"""
    assert TUNE_TRIALS_MIN == 5
    assert TUNE_BATCH_SIZE == 20


def test_run_tuning_batches_over_20():
    """K>20 时每 20 个一批：全部组照跑，批内选优后比批间最优。"""
    net, spots = LAYOUT_BUILDERS["linear"](6, 0.5)
    vehs = generate_demand(total_vehicles=8, seed=5)
    res = run_tuning("duration_greedy", net, spots, vehs, seed=5,
                     wait_policy="fifo",
                     eng_kwargs=dict(car_speed=1.39, max_wait_time=600),
                     trials=25)
    assert len(res["trials"]) == 25
    assert set(res["best_params"].keys()) == {"threshold", "warmup"}
    assert 600.0 <= res["best_params"]["threshold"] <= 7200.0


def test_resolve_strategy_flags_new_fields():
    """新任务三动作开关直接读字段。"""
    s = {"name": "duration_greedy", "run_default": False, "auto_tune": True,
         "tune_run": False, "tune_trials": 15}
    assert resolve_strategy_flags(s) == (False, True, False, 15)


def test_resolve_strategy_flags_legacy_tune_compare():
    """旧 compare_all 任务 tune_compare=True 兼容为 默认组+调参+最优组。"""
    s = {"name": "compare_all", "tune_compare": True, "tune_trials": 10}
    assert resolve_strategy_flags(s) == (True, True, True, 10)


def test_resolve_strategy_flags_legacy_auto_tune():
    """旧单策略任务 auto_tune=True 兼容为 调参+最优跑（不跑默认）。"""
    s = {"name": "duration_greedy", "auto_tune": True}
    assert resolve_strategy_flags(s) == (False, True, True, 10)


def test_resolve_strategy_flags_legacy_plain_run():
    """旧普通任务无任何开关 → 只按当前参数跑。"""
    assert resolve_strategy_flags({"name": "fcfs"}) == (True, False, False, 10)
