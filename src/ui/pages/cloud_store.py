"""云端仿真结果写入 session_state + 持久化运行记录 + CP-SAT 理论最优。"""
from ui.common import *


def _n_runs_for(name, n_runs, random_reps):
    """random 策略用独立的重复次数（≥100），其余策略用「仿真次数」滑杆。"""
    return int(random_reps) if name == "random" else int(n_runs)


def _store_cloud_common_state(net, spots, pe, n_spots, n_vehicles, seed, n_runs, random_reps,
                              strategy_name, layout, strat_params, env_params,
                              sim_vehicles_candidate, demand_source_used, imported_meta,
                              demand_kwargs, base_vehicles):
    """把云端运行结果写入 session_state 公共字段，并持久化运行记录/理论最优。"""
    st.session_state.sim_net = net
    st.session_state.sim_spots = spots
    st.session_state.sim_pe = pe
    st.session_state.sim_n_spots = n_spots
    st.session_state.sim_n_vehicles = (len(sim_vehicles_candidate)
                                       if sim_vehicles_candidate else n_vehicles)
    st.session_state.sim_seed = seed
    st.session_state.sim_n_runs = (_n_runs_for(strategy_name, n_runs, random_reps)
                                   if strategy_name != "compare_all" else n_runs)
    st.session_state.sim_random_reps = int(random_reps)
    st.session_state.sim_strategy_name = strategy_name
    st.session_state.sim_layout = layout
    # 记录最近一次仿真使用的内置/真实布局（布局图页按视图模式回显）
    if layout in BUILTIN_LAYOUT_KEYS:
        st.session_state.last_builtin_sim = {"layout": layout, "net": net, "spots": spots}
        st.session_state.sim_layout_category = "builtin"
    else:
        st.session_state.last_real_sim = {"layout": layout, "net": net, "spots": spots}
        st.session_state.sim_layout_category = "real"
    st.session_state.sim_strategy_params = strat_params
    st.session_state.sim_env_params = env_params
    st.session_state.sim_vehicles = sim_vehicles_candidate
    st.session_state.sim_demand_source = demand_source_used
    st.session_state.sim_demand_meta = (imported_meta or {}
                                        if demand_source_used in ("imported", "real_gate")
                                        else {"seed": seed, "generator_params": demand_kwargs})

    # 持久化运行记录到 Supabase sim_runs（跨会话/跨用户可查，支持导出与对比）
    try:
        if strategy_name == "compare_all":
            persist_sim_run("compare_all", strat_params, env_params,
                            st.session_state.sim_all_metrics,
                            layout, demand_source_used)
        else:
            persist_sim_run(strategy_name, strat_params, env_params,
                            st.session_state.sim_metrics,
                            layout, demand_source_used)
    except Exception:
        pass

    # 计算理论最优（CP-SAT 离线全信息上界，最多约 10 秒）
    cpsat_rate = None
    with st.spinner("计算 CP-SAT 理论最优（最多约 10 秒）..."):
        try:
            cps_vehs = (list(base_vehicles) if base_vehicles is not None
                        else generate_demand(seed=seed, **demand_kwargs))
            cps_lot = ParkingLot(spots)
            cps_res = CPSatBaseline(cps_lot, pe).solve(cps_vehs)
            if cps_res is not None:
                cpsat_rate = len(cps_res) / len(cps_vehs)
        except Exception:
            cpsat_rate = None
    st.session_state.sim_cpsat_rate = cpsat_rate

    st.session_state.sim_has_run = True
    # 重置回放状态
    st.session_state.replay_time = 0.0
    st.session_state.replay_playing = False
    st.session_state.selected_vehicle = None
    # 跳到指标分析页面（调参后直接看结果）
    st.session_state.page = "📊 指标分析"
