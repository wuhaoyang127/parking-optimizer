"""云端仿真运行（单策略；全部对比委托 compare_all_run）。"""
from ui.common import *
from ui.pages.cloud_store import _n_runs_for, _store_cloud_common_state
from ui.pages.compare_all_run import _run_compare_all_cloud


def _run_cloud_simulation(role, layout, n_spots, tandem_ratio, n_vehicles, seed, n_runs,
                          wait_policy, strategy_name, strategy_category, random_reps,
                          strat_params, env_params, tune_compare,
                          base_vehicles, demand_source_used, imported_meta):
    """云端运行仿真：全部对比（含可选最优参数组）/ 单策略。"""
    if strategy_name == "compare_all":
        _run_compare_all_cloud(role, layout, n_spots, tandem_ratio, n_vehicles, seed,
                               n_runs, wait_policy, strategy_category, random_reps,
                               strat_params, env_params, base_vehicles,
                               demand_source_used, imported_meta, tune_compare)
        return

    with st.spinner("仿真运行中..."):
        net, spots = LAYOUT_BUILDERS[layout](n_spots, tandem_ratio)
        pe = PathEngine(net)
        demand_kwargs = dict(total_vehicles=n_vehicles,
                             sim_duration=env_params["sim_duration"],
                             duration_min=env_params["duration_min"],
                             duration_max=env_params["duration_max"],
                             peak_ratio=env_params["peak_ratio"],
                             error_ratio=env_params["error_ratio"],
                             entry_ids=pe.entry_ids,
                             exit_ids=pe.exit_ids)
        eng_kwargs = dict(car_speed=env_params["car_speed"],
                          max_wait_time=env_params["max_wait_time"])
        sim_vehicles_candidate = None

        seed_metrics = []
        events_raw = None
        strategy_timed_out = False
        for r in range(_n_runs_for(strategy_name, n_runs, random_reps)):
            s = seed + r
            vehs = (list(base_vehicles) if base_vehicles is not None
                    else generate_demand(seed=s, **demand_kwargs))
            strategy = StrategyRegistry.create(strategy_name, **strat_params)
            t_seed = time.time()
            try:
                m, ev, _ = run_single(net, spots, vehs, strategy, s, wait_policy, **eng_kwargs)
            except Exception as e:
                st.error(f"❌ 仿真运行失败：{type(e).__name__}: {e}")
                if not is_local_desktop():
                    st.info("当前运行在公网云端（资源受限），车辆/车位较多时容易内存不足。\n"
                            "建议大参数改在本地运行：`py -m streamlit run app.py`（本机计算，云端只存数据）。")
                st.stop()
            if time.time() - t_seed > STRATEGY_TIME_BUDGET:
                strategy_timed_out = True
            seed_metrics.append(m)
            if r == 0:
                events_raw = [{"time": e.time, "type": e.event_type.value,
                               "vehicle_id": e.vehicle_id or "", "spot_id": e.spot_id or "",
                               "metadata": dict(e.metadata)} for e in ev]
                sim_vehicles_candidate = list(vehs)
        avg_m = _avg_metrics(seed_metrics)
        st.session_state.sim_metrics = avg_m
        st.session_state.sim_timed_out_strategies = [strategy_name] if strategy_timed_out else []
        st.session_state.sim_failed_strategies = []
        st.session_state.sim_events_raw = events_raw
        st.session_state.sim_all_metrics = None
        st.session_state.sim_tuned_metrics = None
        st.session_state.sim_tuned_params = {}
        st.session_state.sim_events_by_strategy = {strategy_name: events_raw}
        st.session_state.sim_vehicles_by_strategy = {strategy_name: sim_vehicles_candidate}

        # 记录运行历史（每策略最多保留 5 条，超出删除最旧）
        history = st.session_state.setdefault("run_history", {})
        rec = {
            "params": strat_params,
            "env": env_params,
            "metrics": avg_m,
            "time": time.strftime("%H:%M:%S"),
        }
        history.setdefault(strategy_name, []).append(rec)
        if len(history[strategy_name]) > 5:
            history[strategy_name] = history[strategy_name][-5:]
        st.session_state.run_history = history

        # 持久化最近一次参数（reboot 后自动回填该策略控件）
        persist_last_params(strategy_name, strat_params)

        # 持久化到 Supabase（登录用户跨会话保留调参历史）
        token = st.session_state.get("token")
        if token:
            try:
                auth_set_pref(token, "run_history", json.dumps(history))
            except Exception:
                pass

        _store_cloud_common_state(net, spots, pe, n_spots, n_vehicles, seed, n_runs,
                                  random_reps, strategy_name, layout, strat_params,
                                  env_params, sim_vehicles_candidate, demand_source_used,
                                  imported_meta, demand_kwargs, base_vehicles)

    st.rerun()
