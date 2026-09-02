"""worker 计算层：按任务 payload 在本机执行仿真。"""
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


def run_local_task(payload: dict) -> dict:
    """按任务参数在本机执行仿真，返回可 JSON 序列化的结果 dict。"""
    from local_compute import (LAYOUT_BUILDERS, BUILTIN_LAYOUT_KEYS,
                               build_layout_from_json, run_single,
                               _avg_metrics, _vehicle_to_dict)
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
    strategy_name = (payload.get("strategy") or {}).get("name", "duration_greedy")
    strat_params = (payload.get("strategy") or {}).get("params") or {}
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

    result = {"mode": strategy_name == "compare_all" and "compare_all" or "single"}

    if strategy_name == "compare_all":
        all_m, timed_out, failed = [], [], []
        events_by_strategy, vehicles_by_strategy = {}, {}
        main_events_raw = None
        all_strategies = StrategyRegistry.all()
        total = len(all_strategies)
        for idx, (nm, cls) in enumerate(all_strategies.items(), 1):
            label = getattr(cls, "label", nm)
            print(f"[⚙️] 算法 {idx}/{total}：{label}（{nm}）…", flush=True)
            seed_metrics = []
            strategy_timed_out = False
            strategy_error = None
            total_runs = _n_runs_for(nm)
            for r in range(total_runs):
                s = seed + r
                vehs = (list(base_vehicles) if base_vehicles is not None
                        else generate_demand(seed=s, **demand_kwargs))
                t0 = time.time()
                try:
                    m, ev, _ = run_single(net, spots, vehs, cls(), s, wait_policy, **eng_kwargs)
                except Exception as e:
                    strategy_error = f"{type(e).__name__}: {e}"
                    break
                if time.time() - t0 > budget:
                    strategy_timed_out = True
                seed_metrics.append(m)
                if total_runs > 1 and (total_runs <= 10 or (r + 1) % 10 == 0):
                    print(f"    ├─ {label}：第 {r + 1}/{total_runs} 次…", flush=True)
                if r == 0:
                    ev_raw = [{"time": e.time, "type": e.event_type.value,
                               "vehicle_id": e.vehicle_id or "", "spot_id": e.spot_id or "",
                               "metadata": dict(e.metadata)} for e in ev]
                    events_by_strategy[nm] = ev_raw
                    vehicles_by_strategy[nm] = [_vehicle_to_dict(v) for v in vehs]
                    if nm == "duration_greedy":
                        main_events_raw = ev_raw
            if strategy_error:
                failed.append([nm, strategy_error])
            if strategy_timed_out:
                timed_out.append(nm)
            if seed_metrics:
                all_m.append(_avg_metrics(seed_metrics))
        result.update({
            "all_m": all_m,
            "metrics": next((m for m in all_m if m.get("strategy") == "duration_greedy"), None),
            "timed_out": timed_out,
            "failed": failed,
            "events_by_strategy": events_by_strategy,
            "vehicles_by_strategy": vehicles_by_strategy,
            "main_events": main_events_raw,
            "cpsat_rate": _cpsat_rate(net, spots, pe, base_vehicles, seed, demand_kwargs),
        })
    else:
        cls = StrategyRegistry.get(strategy_name)
        if cls is None:
            raise ValueError(f"未知策略：{strategy_name}")
        label = getattr(cls, "label", strategy_name)
        print(f"[⚙️] 运行策略：{label}（{strategy_name}）…", flush=True)
        seed_metrics = []
        events_raw = None
        timed_out = False
        total_runs = _n_runs_for(strategy_name)
        for r in range(total_runs):
            s = seed + r
            vehs = (list(base_vehicles) if base_vehicles is not None
                    else generate_demand(seed=s, **demand_kwargs))
            strategy = StrategyRegistry.create(strategy_name, **strat_params)
            t0 = time.time()
            m, ev, _ = run_single(net, spots, vehs, strategy, s, wait_policy, **eng_kwargs)
            if time.time() - t0 > budget:
                timed_out = True
            seed_metrics.append(m)
            if total_runs > 1 and (total_runs <= 10 or (r + 1) % 10 == 0):
                print(f"    ├─ {label}：第 {r + 1}/{total_runs} 次…", flush=True)
            if r == 0:
                events_raw = [{"time": e.time, "type": e.event_type.value,
                               "vehicle_id": e.vehicle_id or "", "spot_id": e.spot_id or "",
                               "metadata": dict(e.metadata)} for e in ev]
                vehs_serialized = [_vehicle_to_dict(v) for v in vehs]
        result.update({
            "metrics": _avg_metrics(seed_metrics),
            "timed_out": [strategy_name] if timed_out else [],
            "failed": [],
            "events_by_strategy": {strategy_name: events_raw},
            "vehicles_by_strategy": {strategy_name: vehs_serialized},
            "main_events": events_raw,
            "cpsat_rate": _cpsat_rate(net, spots, pe, base_vehicles, seed, demand_kwargs),
        })
    return result
