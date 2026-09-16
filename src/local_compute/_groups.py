"""多种子分组运行纯函数：对一组策略按统一口径跑仿真并聚合指标。

云端 UI 与本地 worker 共用，避免两处口径不一致。
"""
from __future__ import annotations

import time

from local_compute._run import run_single, _avg_metrics, _vehicle_to_dict
from local_compute._tuning import run_tuning, tunable_specs
from parking_opt.simulation.arrival import generate_demand
from parking_opt.strategies import StrategyRegistry


def tune_all_strategies(strategies, net, spots, base_vehicles, demand_kwargs, seed,
                        wait_policy, eng_kwargs, trials, rank_mode, rank_weights,
                        rank_priority, budget, progress_cb=None):
    """对一组策略各自调参，返回 {name: best_params}（worker 与云端共用）。"""
    tuned = {}
    for nm, cls in strategies:
        if not tunable_specs(nm):
            continue
        vehs = (list(base_vehicles) if base_vehicles is not None
                else generate_demand(seed=seed, **demand_kwargs))

        def cb(done, total, params, _nm=nm, _cls=cls, _base=progress_cb):
            if _base is not None:
                _base(done, total, params, _nm, _cls)

        res = run_tuning(nm, net, spots, vehs, seed, wait_policy, eng_kwargs,
                         trials, rank_mode, rank_weights, rank_priority, budget=budget,
                         progress_cb=cb)
        tuned[nm] = res["best_params"] or {}
    return tuned


def _events_raw(events) -> list:
    """仿真事件 → 可 JSON 序列化的 raw dict 列表。"""
    return [{"time": e.time, "type": e.event_type.value,
             "vehicle_id": e.vehicle_id or "", "spot_id": e.spot_id or "",
             "metadata": dict(e.metadata)} for e in events]


def run_group(strategies: list, net, spots, base_vehicles, demand_kwargs: dict,
              seed: int, wait_policy: str, eng_kwargs: dict, n_runs_for,
              params_by_strategy: dict | None = None, budget: float = 60.0,
              log_cb=None, seed_cb=None) -> dict:
    """按统一口径跑一组策略（每个策略 n_runs_for(name) 个种子）。

    strategies: [(name, cls), ...]
    params_by_strategy: {name: params}，缺省用默认参数。
    返回 all_m / timed_out / failed / events_by_strategy / vehicles_by_strategy /
         main_events（duration_greedy 的事件，否则回退第一个成功策略）。
    """
    params_by_strategy = params_by_strategy or {}
    all_m, timed_out, failed = [], [], []
    events_by_strategy, vehicles_by_strategy = {}, {}
    main_events = None
    total = len(strategies)
    for idx, (nm, cls) in enumerate(strategies, 1):
        runs = n_runs_for(nm)
        if log_cb:
            log_cb(idx, total, nm, cls, runs)
        seed_metrics, strategy_timed_out, strategy_error = [], False, None
        for r in range(runs):
            s = seed + r
            vehs = (list(base_vehicles) if base_vehicles is not None
                    else generate_demand(seed=s, **demand_kwargs))
            t0 = time.time()
            try:
                m, ev, _lot = run_single(net, spots, vehs,
                                         StrategyRegistry.create(nm, **params_by_strategy.get(nm, {})),
                                         s, wait_policy, **eng_kwargs)
            except Exception as e:
                strategy_error = f"{type(e).__name__}: {e}"
                break
            if time.time() - t0 > budget:
                strategy_timed_out = True
            seed_metrics.append(m)
            if seed_cb:
                seed_cb(r + 1, runs, nm)
            if r == 0:
                ev_raw = _events_raw(ev)
                events_by_strategy[nm] = ev_raw
                vehicles_by_strategy[nm] = [_vehicle_to_dict(v) for v in vehs]
                if nm == "duration_greedy":
                    main_events = ev_raw
        if strategy_error:
            failed.append([nm, strategy_error])
        if strategy_timed_out:
            timed_out.append(nm)
        if seed_metrics:
            all_m.append(_avg_metrics(seed_metrics))
    if main_events is None and events_by_strategy:
        first_nm = next(iter(events_by_strategy))
        main_events = events_by_strategy[first_nm]
    return {"all_m": all_m, "timed_out": timed_out, "failed": failed,
            "events_by_strategy": events_by_strategy,
            "vehicles_by_strategy": vehicles_by_strategy,
            "main_events": main_events}
