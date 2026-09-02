"""本地计算：结果载入 session_state、上下文重建、载入最近结果。"""
from ui.common import *


def _apply_sim_state(result, ctx):
    """把仿真结果写入 session_state 并跳转指标分析页（本地计算/载入历史共用）。"""
    if not isinstance(result, dict) or not result:
        st.error("结果为空，无法载入")
        st.stop()
    if ctx.get("custom_layout"):
        st.session_state.setdefault("custom_layouts", {}).update(ctx["custom_layout"])
        _sync_custom_layouts_to_globals()
    st.session_state.sim_net = ctx["net"]
    st.session_state.sim_spots = ctx["spots"]
    st.session_state.sim_pe = ctx["pe"]
    st.session_state.sim_n_spots = int(ctx["n_spots"])
    st.session_state.sim_seed = int(ctx["seed"])
    st.session_state.sim_strategy_name = ctx["strategy_name"]
    st.session_state.sim_strategy_params = ctx["strat_params"]
    st.session_state.sim_env_params = ctx["env_params"]
    st.session_state.sim_layout = ctx["layout"]
    if ctx.get("layout_category") == "builtin":
        st.session_state.last_builtin_sim = {
            "layout": ctx["layout"], "net": ctx["net"], "spots": ctx["spots"]}
        st.session_state.sim_layout_category = "builtin"
    else:
        st.session_state.last_real_sim = {
            "layout": ctx["layout"], "net": ctx["net"], "spots": ctx["spots"]}
        st.session_state.sim_layout_category = "real"
    st.session_state.sim_metrics = result.get("metrics")
    st.session_state.sim_all_metrics = result.get("all_m")
    st.session_state.sim_timed_out_strategies = result.get("timed_out") or []
    st.session_state.sim_failed_strategies = result.get("failed") or []
    st.session_state.sim_cpsat_rate = result.get("cpsat_rate")
    evs = result.get("events_by_strategy") or {}
    vehs_raw = result.get("vehicles_by_strategy") or {}
    st.session_state.sim_events_by_strategy = evs
    st.session_state.sim_vehicles_by_strategy = {
        k: vehicles_from_dicts(v) for k, v in vehs_raw.items()}
    st.session_state.sim_events_raw = result.get("main_events")
    demand_source_used = ctx.get("demand_source") or "generated"
    st.session_state.sim_demand_source = demand_source_used
    if demand_source_used in ("imported", "real_gate"):
        st.session_state.sim_demand_meta = ctx.get("imported_meta") or {}
    else:
        st.session_state.sim_demand_meta = {"seed": ctx["seed"], "generator_params": {
            "total_vehicles": int(ctx["n_vehicles"]),
            "sim_duration": ctx["env_params"]["sim_duration"],
            "duration_min": ctx["env_params"]["duration_min"],
            "duration_max": ctx["env_params"]["duration_max"],
            "peak_ratio": ctx["env_params"]["peak_ratio"],
            "error_ratio": ctx["env_params"]["error_ratio"]}}
    strategy_name_used = ctx["strategy_name"]
    if strategy_name_used != "compare_all":
        st.session_state.sim_vehicles = (st.session_state.sim_vehicles_by_strategy
                                         .get(strategy_name_used) or [])
    else:
        st.session_state.sim_vehicles = (
            st.session_state.sim_vehicles_by_strategy.get("duration_greedy")
            or (next(iter(st.session_state.sim_vehicles_by_strategy.values()))
                if st.session_state.sim_vehicles_by_strategy else []))
    st.session_state.sim_n_vehicles = len(st.session_state.sim_vehicles) or int(ctx["n_vehicles"])
    st.session_state.sim_n_runs = int(ctx["n_runs"])
    st.session_state.sim_random_reps = int(ctx["random_reps"])
    st.session_state.sim_has_run = True
    st.session_state.replay_time = 0.0
    st.session_state.replay_playing = False
    st.session_state.selected_vehicle = None
    st.session_state.page = "📊 指标分析"
    st.rerun()


def _build_settings_ctx(layout, n_spots, tandem_ratio, strategy_name, strat_params,
                        env_params, wait_policy, seed, n_runs, random_reps,
                        base_vehicles, demand_source_used, imported_meta, n_vehicles):
    """从仿真设置页当前控件值构建 ctx（供本地计算结果载入复用）。"""
    net, spots = LAYOUT_BUILDERS[layout](n_spots, tandem_ratio)
    pe = PathEngine(net)
    return {
        "layout": layout,
        "layout_category": "builtin" if layout in BUILTIN_LAYOUT_KEYS else "real",
        "custom_layout": None,
        "n_spots": int(n_spots),
        "tandem_ratio": float(tandem_ratio),
        "net": net,
        "spots": spots,
        "pe": pe,
        "strategy_name": strategy_name,
        "strat_params": strat_params,
        "env_params": env_params,
        "wait_policy": wait_policy,
        "seed": int(seed),
        "n_runs": int(n_runs),
        "random_reps": int(random_reps),
        "base_vehicles": base_vehicles,
        "demand_source": demand_source_used,
        "imported_meta": imported_meta if demand_source_used in ("imported", "real_gate") else None,
        "n_vehicles": int(n_vehicles),
    }


def _apply_local_result(result, ctx):
    """把本机 worker 返回的结果载入 session_state，等同云端跑完一次仿真。"""
    _apply_sim_state(result, ctx)


def _load_latest_local_task():
    """载入该用户最近一次已完成的本地计算任务（session 丢失 task_id 后找回）。"""
    token = st.session_state.get("token")
    if not token:
        st.error("未登录，无法载入本地计算任务")
        st.stop()
    res = auth_get_latest_compute_task(token)
    if not (isinstance(res, dict) and res.get("success")):
        st.error(f"❌ 载入失败：{(res or {}).get('error', '未知错误')}\n\n"
                 "请确认 Supabase 已执行 migrations/10_latest_task_load.sql。")
        st.stop()
    task = res.get("task")
    if not isinstance(task, dict) or not task.get("result"):
        st.info("暂无已完成的本地计算任务。先在下方「▶️ 下发本地计算任务」跑一次，"
                "完成后即可在这里一键载入。")
        return
    try:
        ctx = build_local_task_context(task.get("payload") or {})
    except Exception as e:
        st.error(f"❌ 任务参数解析失败：{type(e).__name__}: {e}")
        st.stop()
    _apply_sim_state(task.get("result") or {}, ctx)
