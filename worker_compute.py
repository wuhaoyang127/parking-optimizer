"""worker 计算层：按任务 payload 在本机执行仿真/自动调参。"""
import time


def _cpsat_rate(net, spots, pe, base_vehicles, seed, demand_kwargs):
    from parking_opt.simulation.parking_lot import ParkingLot
    from parking_opt.optimization.cpsat_baseline import CPSatBaseline
    from parking_opt.simulation.arrival import generate_demand
    try:
        cps_vehs = (list(base_vehicles) if base_vehicles is not None
                    else generate_demand(seed=seed, **demand_kwargs))
        cps_lot = ParkingLot(spots)
        cps_res = CPSatBaseline(cps_lot, pe).solve(cps_vehs)
        if cps_res is not None:
            return round(len(cps_res) / len(cps_vehs), 6)
    except Exception:
        pass
    return None


def _tune_all(strategies, net, spots, base_vehicles, demand_kwargs, seed, wait_policy,
              eng_kwargs, trials, rank_mode, rank_weights, rank_priority, budget):
    """对一组策略各自调参，返回 {name: best_params}。"""
    from local_compute import run_tuning, tunable_specs
    from parking_opt.simulation.arrival import generate_demand
    tuned = {}
    for nm, cls in strategies:
        if not tunable_specs(nm):
            continue

        def cb(done, total, params, _nm=nm, _cls=cls):
            print(f"[🎯] 调参 {getattr(_cls, 'label', _nm)}：第 {done}/{total} 组…", flush=True)

        vehs = (list(base_vehicles) if base_vehicles is not None
                else generate_demand(seed=seed, **demand_kwargs))
        res = run_tuning(nm, net, spots, vehs, seed, wait_policy, eng_kwargs,
                         trials, rank_mode, rank_weights, rank_priority,
                         budget=budget, progress_cb=cb)
        tuned[nm] = res["best_params"]
    return tuned


def run_local_task(payload: dict) -> dict:
    """按任务参数在本机执行仿真/自动调参，返回可 JSON 序列化的结果 dict。"""
    from local_compute import (LAYOUT_BUILDERS, BUILTIN_LAYOUT_KEYS,
                               build_layout_from_json, run_group,
                               run_tuning, TUNE_TRIALS_DEFAULT)
    from parking_opt.routing.path_engine import PathEngine
    from parking_opt.simulation.arrival import generate_demand
    from parking_opt.io.demand_io import parse_demand_json
    from parking_opt.strategies import StrategyRegistry
    from parking_opt.strategies.registry import CATEGORY_CLASSIC, CATEGORY_ML

    # 1. 布局
    layout = payload.get("layout") or {}
    if layout.get("source") == "custom":
        net, spots = build_layout_from_json(layout["custom_data"])
    else:
        key = layout.get("builtin_key") or "linear"
        net, spots = LAYOUT_BUILDERS[key](int(layout.get("n_spots", 15)),
                                          float(layout.get("tandem_ratio", 0.5)))
    pe = PathEngine(net)

    # 2. 需求
    demand = payload.get("demand") or {}
    base_vehicles = None
    demand_kwargs = {}
    demand_source = "generated"
    if demand.get("source") in ("imported", "real_gate"):
        vehs, meta = parse_demand_json(demand.get("json_str", ""))
        base_vehicles = list(vehs)
        demand_source = "real_gate" if (meta or {}).get("source") == "real_gate" else "imported"
    else:
        demand_kwargs = dict(demand.get("generator") or {})
        demand_kwargs["entry_ids"] = pe.entry_ids
        demand_kwargs["exit_ids"] = pe.exit_ids

    # 3. 策略与引擎参数
    strategy = payload.get("strategy") or {}
    strategy_name = strategy.get("name", "duration_greedy")
    strat_params = strategy.get("params") or {}
    auto_tune = bool(strategy.get("auto_tune"))
    tune_compare = bool(strategy.get("tune_compare"))
    tune_trials = int(strategy.get("tune_trials", TUNE_TRIALS_DEFAULT) or TUNE_TRIALS_DEFAULT)
    ranking_cfg = payload.get("ranking") or {}
    rank_mode = ranking_cfg.get("mode") or "加权评分"
    rank_weights = ranking_cfg.get("weights") or {}
    rank_priority = ranking_cfg.get("priority") or []
    eng = payload.get("engine") or {}
    wait_policy = eng.get("wait_policy", "fifo")
    car_speed = float(eng.get("car_speed", 1.39))
    max_wait_time = float(eng.get("max_wait_time", 1800))
    seed = int(eng.get("seed", 42))
    n_runs = int(eng.get("n_runs", 1))
    random_reps = int(eng.get("random_reps", 100))
    budget = float(eng.get("budget", 60.0))
    eng_kwargs = dict(car_speed=car_speed, max_wait_time=max_wait_time)

    def _n_runs_for(name: str) -> int:
        return random_reps if name == "random" else n_runs

    def _log(idx, total, nm, cls, runs):
        print(f"[⚙️] 算法 {idx}/{total}：{getattr(cls, 'label', nm)}（{nm}）…", flush=True)

    def _seed_cb(r, total_runs, nm):
        if total_runs > 1 and (total_runs <= 10 or r % 10 == 0):
            print(f"    ├─ {nm}：第 {r}/{total_runs} 次…", flush=True)

    result = {"mode": "compare_all" if strategy_name == "compare_all" else "single"}

    if strategy_name == "compare_all":
        category = strategy.get("category")
        if category in (CATEGORY_CLASSIC, CATEGORY_ML):
            strategies = StrategyRegistry.items_in_category(category)
        else:
            strategies = list(StrategyRegistry.all().items())
        tuned_params = {}
        if tune_compare:
            tuned_params = _tune_all(strategies, net, spots, base_vehicles,
                                     demand_kwargs, seed, wait_policy, eng_kwargs,
                                     tune_trials, rank_mode, rank_weights,
                                     rank_priority, budget)
        res = run_group(strategies, net, spots, base_vehicles, demand_kwargs, seed,
                        wait_policy, eng_kwargs, _n_runs_for,
                        params_by_strategy=None, budget=budget,
                        log_cb=_log, seed_cb=_seed_cb)
        all_m = res["all_m"]
        tuned_m = []
        if tune_compare:
            res2 = run_group(strategies, net, spots, base_vehicles, demand_kwargs,
                             seed, wait_policy, eng_kwargs, _n_runs_for,
                             params_by_strategy=tuned_params, budget=budget,
                             log_cb=_log, seed_cb=_seed_cb)
            tuned_m = res2["all_m"]
        result.update({
            "all_m": all_m,
            "metrics": next((m for m in all_m if m.get("strategy") == "duration_greedy"), None),
            "timed_out": res["timed_out"], "failed": res["failed"],
            "events_by_strategy": res["events_by_strategy"],
            "vehicles_by_strategy": res["vehicles_by_strategy"],
            "main_events": res["main_events"],
            "tuned_m": tuned_m, "tuned_params": tuned_params,
            "cpsat_rate": _cpsat_rate(net, spots, pe, base_vehicles, seed, demand_kwargs),
        })
    else:
        cls = StrategyRegistry.get(strategy_name)
        if cls is None:
            raise ValueError(f"未知策略：{strategy_name}")
        if auto_tune:
            vehs = (list(base_vehicles) if base_vehicles is not None
                    else generate_demand(seed=seed, **demand_kwargs))
            tune_res = run_tuning(strategy_name, net, spots, vehs, seed, wait_policy,
                                  eng_kwargs, tune_trials, rank_mode, rank_weights,
                                  rank_priority, budget=budget)
            strat_params = tune_res["best_params"] or {}
            result["tuned_params"] = {strategy_name: strat_params}
            result["tune_trials"] = tune_res["trials"]
            print(f"[🎯] 调参完成，用最优参数运行正式仿真（{strategy_name}）…", flush=True)
        print(f"[⚙️] 运行策略：{getattr(cls, 'label', strategy_name)}（{strategy_name}）…", flush=True)
        res = run_group([(strategy_name, cls)], net, spots, base_vehicles, demand_kwargs,
                        seed, wait_policy, eng_kwargs, _n_runs_for,
                        params_by_strategy={strategy_name: strat_params}, budget=budget,
                        log_cb=_log, seed_cb=_seed_cb)
        result.update({
            "metrics": res["all_m"][0] if res["all_m"] else None,
            "timed_out": res["timed_out"], "failed": res["failed"],
            "events_by_strategy": res["events_by_strategy"],
            "vehicles_by_strategy": res["vehicles_by_strategy"],
            "main_events": res["main_events"],
            "cpsat_rate": _cpsat_rate(net, spots, pe, base_vehicles, seed, demand_kwargs),
        })
    return result
