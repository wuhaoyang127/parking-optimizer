"""本地计算任务 payload → 页面上下文重建（载入最近结果用）。"""
from ui.common._imports import *


def build_local_task_context(payload: dict) -> dict:
    """从本地计算任务 payload 重建仿真页面上下文。

    供「载入最近一次本地计算结果」使用：把任务的布局/需求/策略/引擎参数
    与结果一起恢复，使指标分析、布局图、动态路径页与当时跑完直接看一致。
    返回 dict 直接交给 pages._apply_sim_state(result, ctx) 使用。
    """
    payload = payload or {}
    layout = payload.get("layout") or {}
    demand = payload.get("demand") or {}
    strategy = payload.get("strategy") or {}
    eng = payload.get("engine") or {}

    custom_layout = None
    if layout.get("source") == "custom":
        data = layout.get("custom_data") or {}
        net, spots = build_layout_from_json(data)
        name = data.get("name") or "导入布局"
        lid = str(name).lower().replace(" ", "_")
        custom_layout = {lid: {"name": name, "data": data, "net": net, "spots": spots}}
        layout_key = lid
        layout_category = "real"
        n_spots = len(spots)
        tandem_ratio = 0.0
    else:
        layout_key = layout.get("builtin_key") or "linear"
        if layout_key not in LAYOUT_BUILDERS:
            layout_key = "linear"
        n_spots = int(layout.get("n_spots", 15))
        tandem_ratio = float(layout.get("tandem_ratio", 0.5))
        net, spots = LAYOUT_BUILDERS[layout_key](n_spots, tandem_ratio)
        layout_category = "builtin"

    pe = PathEngine(net)

    base_vehicles = None
    imported_meta = None
    demand_source = "generated"
    gen = demand.get("generator") or {}
    n_vehicles = int(gen.get("total_vehicles", 0))
    if demand.get("source") in ("imported", "real_gate"):
        vehs, meta = parse_demand_json(demand.get("json_str", ""))
        base_vehicles = list(vehs)
        demand_source = ("real_gate" if (meta or {}).get("source") == "real_gate"
                         else "imported")
        imported_meta = meta or {}
        n_vehicles = len(base_vehicles)

    strategy_name = strategy.get("name") or "duration_greedy"
    strat_params = dict(strategy.get("params") or {})

    env_params = {
        "car_speed": float(eng.get("car_speed", CAR_SPEED)),
        "max_wait_time": float(eng.get("max_wait_time", MAX_WAIT_TIME)),
        "sim_duration": int(gen.get("sim_duration", int(SIM_DURATION))),
        "duration_min": int(gen.get("duration_min", int(DURATION_MIN))),
        "duration_max": int(gen.get("duration_max", int(DURATION_MAX))),
        "peak_ratio": float(gen.get("peak_ratio", PEAK_RATIO)),
        "error_ratio": float(gen.get("error_ratio", ERROR_RATIO)),
    }

    return {
        "layout": layout_key,
        "layout_category": layout_category,
        "custom_layout": custom_layout,
        "n_spots": n_spots,
        "tandem_ratio": tandem_ratio,
        "net": net,
        "spots": spots,
        "pe": pe,
        "strategy_name": strategy_name,
        "strat_params": strat_params,
        "env_params": env_params,
        "wait_policy": eng.get("wait_policy") or "fifo",
        "seed": int(eng.get("seed", 42)),
        "n_runs": int(eng.get("n_runs", 1)),
        "random_reps": int(eng.get("random_reps", 100)),
        "base_vehicles": base_vehicles,
        "demand_source": demand_source,
        "imported_meta": imported_meta,
        "n_vehicles": n_vehicles,
    }
