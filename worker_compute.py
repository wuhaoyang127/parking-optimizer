"""worker 计算层：按任务 payload 在本机执行仿真/自动调参。"""
import time

try:
    from local_compute import resolve_strategy_flags
    from local_compute._groups import tune_all_strategies
except Exception:  # pragma: no cover
    def resolve_strategy_flags(strategy, default_trials=10):
        return True, False, False, default_trials

    def tune_all_strategies(*_a, **_k):
        return {}


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


def run_local_task(payload: dict) -> dict:
    """按任务参数在本机执行仿真/自动调参，返回可 JSON 序列化的结果 dict。"""
    from local_compute import (LAYOUT_BUILDERS, BUILTIN_LAYOUT_KEYS,
                               build_layout_from_json, run_group,
                               run_tuning, TUNE_TRIALS_DEFAULT)
    from parking_opt.routing.path_engine import PathEngine
    from parking_opt.simulation.arrival import generate_demand
    from parking_opt.io.demand_io import parse_demand_json
    from parking_opt.strategies import StrategyRegistry

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
    run_default, auto_tune, tune_run, tune_trials = resolve_strategy_flags(strategy)
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
    eng_kwargs = dict(car_speed=car_speed, max_wait_time=max_wait_time,
                      buffer_w_distance=float(eng.get("buffer_w_distance", 1.0)),
                      buffer_w_idle=float(eng.get("buffer_w_idle", 1.0)),
                      buffer_w_secondary=float(eng.get("buffer_w_secondary", 2.0)),
                      buffer_idle_half_life=float(eng.get("buffer_idle_half_life", 300.0)))

    def _n_runs_for(name: str) -> int:
        return random_reps if name == "random" else n_runs

    def _log(idx, total, nm, cls, runs):
        print(f"[⚙️] 算法 {idx}/{total}：{getattr(cls, 'label', nm)}（{nm}）…", flush=True)

    def _seed_cb(r, total_runs, nm):
        if total_runs > 1 and (total_runs <= 10 or r % 10 == 0):
            print(f"    ├─ {nm}：第 {r}/{total_runs} 次…", flush=True)

    result = {"mode": "compare_all" if strategy_name == "compare_all" else "single",
              "metrics": None}

    if strategy_name == "compare_all":
        strategies = StrategyRegistry.items_filtered(strategy.get("names"),
                                                     strategy.get("category"))
        tuned_params = {}
        if auto_tune:
            def _tune_cb(done, total, params, _nm="", _cls=None):
                label = getattr(_cls, "label", _nm) if _cls is not None else _nm
                print(f"[🎯] 调参 {label}：第 {done}/{total} 组…", flush=True)

            tuned_params = tune_all_strategies(strategies, net, spots, base_vehicles,
                                     demand_kwargs, seed, wait_policy, eng_kwargs,
                                     tune_trials, rank_mode, rank_weights,
                                     rank_priority, budget, progress_cb=_tune_cb)
            result["tune_trials_count"] = tune_trials
        all_m, tuned_m = [], []
        ev_by, veh_by, main_ev = {}, {}, None
        timed_out, failed = [], []
        if run_default:
            res = run_group(strategies, net, spots, base_vehicles, demand_kwargs, seed,
                            wait_policy, eng_kwargs, _n_runs_for,
                            params_by_strategy=None, budget=budget,
                            log_cb=_log, seed_cb=_seed_cb)
            all_m = res["all_m"]
            ev_by, veh_by, main_ev = (res["events_by_strategy"],
                                      res["vehicles_by_strategy"], res["main_events"])
            timed_out, failed = res["timed_out"], res["failed"]
        if tune_run and tuned_params:
            res2 = run_group(strategies, net, spots, base_vehicles, demand_kwargs,
                             seed, wait_policy, eng_kwargs, _n_runs_for,
                             params_by_strategy=tuned_params, budget=budget,
                             log_cb=_log, seed_cb=_seed_cb)
            tuned_m = res2["all_m"]
            if not ev_by:
                ev_by, veh_by, main_ev = (res2["events_by_strategy"],
                                          res2["vehicles_by_strategy"], res2["main_events"])
            timed_out = sorted(set(timed_out) | set(res2["timed_out"]))
            failed = failed + [f for f in res2["failed"] if f not in failed]
        metrics = (next((m for m in all_m if m.get("strategy") == "duration_greedy"), None)
                   or next((m for m in tuned_m if m.get("strategy") == "duration_greedy"), None))
        result.update({
            "all_m": all_m,
            "metrics": metrics,
            "timed_out": timed_out, "failed": failed,
            "events_by_strategy": ev_by,
            "vehicles_by_strategy": veh_by,
            "main_events": main_ev,
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
            result["tune_trials_count"] = tune_trials
            result["tune_failed"] = tune_res["failed"]
            print(f"[🎯] 调参完成：{getattr(cls, 'label', strategy_name)}（{strategy_name}）"
                  f"共 {len(tune_res['trials'])} 组，最优参数 {strat_params}",
                  flush=True)
        if run_default or (tune_run and auto_tune):
            groups = []
            if run_default:
                groups.append(("default", strat_params if not auto_tune else strategy.get("params") or {}))
            if tune_run and auto_tune:
                groups.append(("tuned", strat_params))
            for tag, params in groups:
                print(f"[⚙️] 运行策略：{getattr(cls, 'label', strategy_name)}（{strategy_name}，"
                      f"{'最优参数' if tag == 'tuned' else '当前参数'}）…", flush=True)
                res = run_group([(strategy_name, cls)], net, spots, base_vehicles,
                                demand_kwargs, seed, wait_policy, eng_kwargs, _n_runs_for,
                                params_by_strategy={strategy_name: params}, budget=budget,
                                log_cb=_log, seed_cb=_seed_cb)
                m = res["all_m"][0] if res["all_m"] else None
                result["metrics"] = m
                result["timed_out"] = res["timed_out"]
                result["failed"] = res["failed"]
                result["events_by_strategy"] = res["events_by_strategy"]
                result["vehicles_by_strategy"] = res["vehicles_by_strategy"]
                result["main_events"] = res["main_events"]
                if tag == "default":
                    result["default_metrics"] = m
            result["cpsat_rate"] = _cpsat_rate(net, spots, pe, base_vehicles, seed, demand_kwargs)
    return result
