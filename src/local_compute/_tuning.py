"""自动调参纯函数：按 PARAMS 声明随机采样参数，跑单种子仿真，按排名口径选最优。

不依赖 Streamlit/Pandas/Plotly，worker 与云端 UI 共用。
"""
from __future__ import annotations

import random
import time

from local_compute._run import run_single
from parking_opt.evaluation.ranking import METRIC_DIRECTIONS, weighted_rank
from parking_opt.strategies import StrategyRegistry

TUNE_TRIALS_DEFAULT = 10
TUNE_SEED_OFFSET = 900001  # 调参专用随机流，不污染仿真主随机流


def tunable_specs(name: str) -> list:
    """返回某策略可调参数声明（locked 参数由系统绑定，不参与调参）。"""
    return [p for p in StrategyRegistry.specs(name) if not p.get("locked")]


def sample_params(name: str, rng: random.Random) -> dict:
    """按 PARAMS 声明随机采样一组参数。

    int 按 step 粒度采样；float 均匀采样；choice/strategy 均匀抽选项；bool 随机。
    """
    params = {}
    for p in tunable_specs(name):
        key = p["key"]
        ptype = p.get("type", "float")
        if ptype == "int":
            lo, hi, step = int(p.get("min", 0)), int(p.get("max", 100)), int(p.get("step", 1) or 1)
            n = max(0, (hi - lo) // step)
            params[key] = lo + rng.randint(0, n) * step
        elif ptype == "float":
            params[key] = rng.uniform(float(p.get("min", 0.0)), float(p.get("max", 1.0)))
        elif ptype == "choice":
            opts = [o[0] for o in p.get("options", [])]
            params[key] = rng.choice(opts) if opts else p.get("default")
        elif ptype == "strategy":
            names = list(StrategyRegistry.all().keys())
            params[key] = rng.choice(names) if names else p.get("default")
        elif ptype == "bool":
            params[key] = bool(rng.randint(0, 1))
    _repair_params(name, params)
    return params


def _repair_params(name: str, params: dict) -> None:
    """修复采样产生的非法组合（如 RHO 轻微阈值 > 重度阈值）。"""
    if name == "rho_rolling":
        mild = params.get("mild_threshold")
        severe = params.get("severe_threshold")
        if mild is not None and severe is not None and mild > severe:
            params["mild_threshold"], params["severe_threshold"] = severe, mild


def best_trial(trials: list, rank_mode: str, weights=None, priority=None):
    """从 [(params, metrics), ...] 中按排名口径选出最优，返回 (best_params, best_metrics)。

    rank_mode == "加权评分"：用 weighted_rank（相对 K 组归一化）；
    否则按 priority 字段字典序比较（方向来自 METRIC_DIRECTIONS）。
    """
    if not trials:
        return None, None
    if rank_mode == "加权评分":
        tagged = []
        for i, (_params, m) in enumerate(trials):
            mm = dict(m)
            mm["_trial_idx"] = i
            tagged.append(mm)
        ranked = weighted_rank(tagged, weights or {})
        idx = int(ranked[0].get("_trial_idx", 0))
        return trials[idx][0], trials[idx][1]
    directions = METRIC_DIRECTIONS
    prio = [f for f in (priority or []) if f in directions]

    def key(item):
        m = item[1]
        return tuple(-float(m.get(f, 0.0)) if directions[f] == "max"
                     else float(m.get(f, 0.0)) for f in prio)

    best_params, best_metrics = min(trials, key=key)
    return best_params, best_metrics


def run_tuning(strategy_name: str, net, spots, vehicles, seed, wait_policy,
               eng_kwargs: dict, trials: int = TUNE_TRIALS_DEFAULT,
               rank_mode: str = "加权评分", weights=None, priority=None,
               budget: float = 60.0, progress_cb=None) -> dict:
    """对单个策略随机采样 trials 组参数，跑单种子仿真并选最优。

    返回 {"best_params": {...}, "best_metrics": {...},
          "trials": [{"params":..., "metrics":..., "timed_out": bool}, ...],
          "failed": int}
    """
    if not tunable_specs(strategy_name):
        return {"best_params": {}, "best_metrics": None, "trials": [], "failed": 0}
    rng = random.Random(int(seed) + TUNE_SEED_OFFSET)
    trials_out = []
    failed = 0
    for i in range(int(trials)):
        params = sample_params(strategy_name, rng)
        t0 = time.time()
        try:
            m, _ev, _lot = run_single(net, spots, list(vehicles),
                                      StrategyRegistry.create(strategy_name, **params),
                                      seed, wait_policy, **eng_kwargs)
        except Exception:
            failed += 1
            continue
        trials_out.append({"params": params, "metrics": m,
                           "timed_out": bool(time.time() - t0 > budget)})
        if progress_cb:
            progress_cb(i + 1, int(trials), params)
    best_params, best_metrics = best_trial(
        [(t["params"], t["metrics"]) for t in trials_out],
        rank_mode, weights, priority)
    return {"best_params": best_params or {}, "best_metrics": best_metrics,
            "trials": trials_out, "failed": failed}
