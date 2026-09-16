"""云端「全部对比」运行：默认参数组 + 可选最优参数组 + 可选自动调参。"""
from ui.common import *
from ui.pages.cloud_store import _n_runs_for, _store_cloud_common_state


def _tune_all_cloud(strategies, net, spots, base_vehicles, demand_kwargs, seed,
                    wait_policy, eng_kwargs, tune_trials):
    """对一组策略各自调参（云端进程内），返回 {name: best_params}。"""
    ranking = ranking_config_from_session()
    tunables = [(nm, cls) for nm, cls in strategies if tunable_specs(nm)]
    total_trials = len(tunables) * tune_trials
    done = 0
    tuned = {}
    if not tunables:
        return tuned
    prog = st.progress(0.0, text="🎯 自动调参（选最优参数）…")
    for nm, cls in tunables:
        vehs = (list(base_vehicles) if base_vehicles is not None
                else generate_demand(seed=seed, **demand_kwargs))
        label = getattr(cls, "label", nm)

        def cb(d, total, params, _nm=nm, _label=label):
            prog.progress((done + d) / total_trials,
                          text=f"🎯 调参 {_label}（{d}/{total}）…")

        res = run_tuning(nm, net, spots, vehs, seed, wait_policy, eng_kwargs,
                         tune_trials, ranking["mode"], ranking["weights"],
                         ranking["priority"], budget=STRATEGY_TIME_BUDGET,
                         progress_cb=cb)
        tuned[nm] = res["best_params"] or {}
        done += tune_trials
    prog.empty()
    return tuned


def _run_compare_all_cloud(role, layout, n_spots, tandem_ratio, n_vehicles, seed, n_runs,
                           wait_policy, strategy_category, random_reps, strat_params,
                           env_params, base_vehicles, demand_source_used, imported_meta,
                           run_default, auto_tune, tune_run, tune_trials):
    """云端全部对比：按当前参数跑排序 / 自动调参选最优 / 用最优参数跑排序。

    三动作可独立勾选：run_default=默认参数对比组；auto_tune=每个算法试 K 组；
    tune_run=额外用调出的最优参数跑一组对比。
    """
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
        strategies = (StrategyRegistry.items_in_category(strategy_category)
                      if strategy_category in (CATEGORY_CLASSIC, CATEGORY_ML)
                      else list(StrategyRegistry.all().items()))
        tuned_params = {}
        if auto_tune:
            tuned_params = _tune_all_cloud(strategies, net, spots, base_vehicles,
                                           demand_kwargs, seed, wait_policy, eng_kwargs,
                                           tune_trials)

        def log_cb(idx, total, nm, cls, runs):
            prog.progress((idx - 1) / total,
                          text=f"运行策略 {idx}/{total}：{cls.label}"
                               f"（{runs} 次取平均，超过 {int(STRATEGY_TIME_BUDGET)} 秒仅标记）")

        all_m, tuned_m = [], []
        ev_by, veh_by, main_ev = {}, {}, None
        timed_out, failed = [], []
        if run_default:
            prog = st.progress(0.0, text="准备运行默认参数对比...")
            res = run_group(strategies, net, spots, base_vehicles, demand_kwargs, seed,
                            wait_policy, eng_kwargs,
                            lambda n: _n_runs_for(n, n_runs, random_reps),
                            params_by_strategy=None, budget=STRATEGY_TIME_BUDGET,
                            log_cb=log_cb)
            prog.empty()
            all_m = res["all_m"]
            ev_by = res["events_by_strategy"]
            veh_by = res["vehicles_by_strategy"]
            main_ev = res["main_events"]
            timed_out, failed = res["timed_out"], res["failed"]
        if tune_run and tuned_params:
            prog = st.progress(0.0, text="准备运行最优参数对比...")
            res2 = run_group(strategies, net, spots, base_vehicles, demand_kwargs,
                             seed, wait_policy, eng_kwargs,
                             lambda n: _n_runs_for(n, n_runs, random_reps),
                             params_by_strategy=tuned_params,
                             budget=STRATEGY_TIME_BUDGET, log_cb=log_cb)
            prog.empty()
            tuned_m = res2["all_m"]
            if not ev_by:
                ev_by = res2["events_by_strategy"]
                veh_by = res2["vehicles_by_strategy"]
                main_ev = res2["main_events"]
            timed_out = sorted(set(timed_out) | set(res2["timed_out"]))
            failed = failed + [f for f in res2["failed"] if f not in failed]

        st.session_state.sim_timed_out_strategies = timed_out
        st.session_state.sim_failed_strategies = failed
        st.session_state.sim_tuned_params = tuned_params
        if all_m:
            st.session_state.sim_all_metrics = all_m
            st.session_state.sim_tuned_metrics = tuned_m or None
            st.session_state.sim_metrics = next(
                (m for m in all_m if m.get("strategy") == "duration_greedy"), None)
        elif tuned_m:
            st.session_state.sim_all_metrics = tuned_m
            st.session_state.sim_tuned_metrics = None
            st.session_state.sim_metrics = next(
                (m for m in tuned_m if m.get("strategy") == "duration_greedy"), None)
        else:
            st.session_state.sim_all_metrics = None
            st.session_state.sim_tuned_metrics = None
            st.session_state.sim_metrics = None

        if not (all_m or tuned_m):
            st.session_state.last_tune_summary = {
                "strategy": "compare_all", "tuned_params": tuned_params,
                "trials_per_algo": tune_trials}
            st.success(f"🎯 自动调参完成（每个算法试 {tune_trials} 组），最优参数已保存。"
                       "可勾选「🚀 用最优参数跑排序」后再次运行。")
            st.rerun()

        vehicles_by_strategy = {k: vehicles_from_dicts(v)
                                for k, v in veh_by.items()}
        sim_vehicles_candidate = (vehicles_by_strategy.get("duration_greedy")
                                  or (next(iter(vehicles_by_strategy.values()))
                                      if vehicles_by_strategy else None))
        st.session_state.sim_events_by_strategy = ev_by
        st.session_state.sim_vehicles_by_strategy = vehicles_by_strategy
        st.session_state.sim_events_raw = main_ev

        _store_cloud_common_state(net, spots, pe, n_spots, n_vehicles, seed, n_runs,
                                  random_reps, "compare_all", layout, strat_params,
                                  env_params, sim_vehicles_candidate, demand_source_used,
                                  imported_meta, demand_kwargs, base_vehicles)
    st.rerun()
