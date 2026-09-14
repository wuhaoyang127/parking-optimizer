"""云端「全部对比」运行：默认参数组 + 可选最优参数组。"""
from ui.common import *
from ui.pages.cloud_store import _n_runs_for, _store_cloud_common_state


def _tune_all_cloud(strategies, net, spots, base_vehicles, demand_kwargs, seed,
                    wait_policy, eng_kwargs):
    """对一组策略各自调参（云端进程内），返回 {name: best_params}。"""
    ranking = ranking_config_from_session()
    tunables = [(nm, cls) for nm, cls in strategies if tunable_specs(nm)]
    total_trials = len(tunables) * TUNE_TRIALS_DEFAULT
    done = 0
    tuned = {}
    if not tunables:
        return tuned
    prog = st.progress(0.0, text="🎯 自动调参（最优参数组）…")
    for nm, cls in tunables:
        vehs = (list(base_vehicles) if base_vehicles is not None
                else generate_demand(seed=seed, **demand_kwargs))
        label = getattr(cls, "label", nm)

        def cb(d, total, params, _nm=nm, _label=label):
            prog.progress((done + d) / total_trials,
                          text=f"🎯 调参 {_label}（{d}/{total}）…")

        res = run_tuning(nm, net, spots, vehs, seed, wait_policy, eng_kwargs,
                         TUNE_TRIALS_DEFAULT, ranking["mode"], ranking["weights"],
                         ranking["priority"], budget=STRATEGY_TIME_BUDGET,
                         progress_cb=cb)
        tuned[nm] = res["best_params"] or {}
        done += TUNE_TRIALS_DEFAULT
    prog.empty()
    return tuned


def _run_compare_all_cloud(role, layout, n_spots, tandem_ratio, n_vehicles, seed, n_runs,
                           wait_policy, strategy_category, random_reps, strat_params,
                           env_params, base_vehicles, demand_source_used, imported_meta,
                           tune_compare):
    """云端全部对比：默认参数组 + 最优参数组（勾选自动调参时）。"""
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
        if tune_compare:
            tuned_params = _tune_all_cloud(strategies, net, spots, base_vehicles,
                                           demand_kwargs, seed, wait_policy, eng_kwargs)

        def log_cb(idx, total, nm, cls, runs):
            prog.progress((idx - 1) / total,
                          text=f"运行策略 {idx}/{total}：{cls.label}"
                               f"（{runs} 次取平均，超过 {int(STRATEGY_TIME_BUDGET)} 秒仅标记）")

        # 默认参数组
        prog = st.progress(0.0, text="准备运行默认参数对比...")
        res = run_group(strategies, net, spots, base_vehicles, demand_kwargs, seed,
                        wait_policy, eng_kwargs,
                        lambda n: _n_runs_for(n, n_runs, random_reps),
                        params_by_strategy=None, budget=STRATEGY_TIME_BUDGET,
                        log_cb=log_cb)
        prog.empty()
        all_m = res["all_m"]
        timed_out = res["timed_out"]
        failed = res["failed"]
        events_by_strategy = res["events_by_strategy"]
        vehicles_by_strategy = {k: vehicles_from_dicts(v)
                                for k, v in res["vehicles_by_strategy"].items()}
        main_events_raw = res["main_events"]
        sim_vehicles_candidate = (vehicles_by_strategy.get("duration_greedy")
                                  or (next(iter(vehicles_by_strategy.values()))
                                      if vehicles_by_strategy else None))
        # 最优参数组
        tuned_m = []
        if tune_compare:
            res2 = run_group(strategies, net, spots, base_vehicles, demand_kwargs,
                             seed, wait_policy, eng_kwargs,
                             lambda n: _n_runs_for(n, n_runs, random_reps),
                             params_by_strategy=tuned_params,
                             budget=STRATEGY_TIME_BUDGET)
            tuned_m = res2["all_m"]

        st.session_state.sim_all_metrics = all_m
        st.session_state.sim_timed_out_strategies = timed_out
        st.session_state.sim_failed_strategies = failed
        st.session_state.sim_metrics = next((m for m in all_m if m.get("strategy") == "duration_greedy"), None)
        st.session_state.sim_events_by_strategy = events_by_strategy
        st.session_state.sim_vehicles_by_strategy = vehicles_by_strategy
        st.session_state.sim_events_raw = main_events_raw
        st.session_state.sim_tuned_metrics = tuned_m or None
        st.session_state.sim_tuned_params = tuned_params

        _store_cloud_common_state(net, spots, pe, n_spots, n_vehicles, seed, n_runs,
                                  random_reps, "compare_all", layout, strat_params,
                                  env_params, sim_vehicles_candidate, demand_source_used,
                                  imported_meta, demand_kwargs, base_vehicles)
    st.rerun()
