"""云端仿真运行（单策略 / 全部对比）。"""
from ui.common import *
from ui.pages.cloud_store import _n_runs_for, _store_cloud_common_state


def _run_cloud_simulation(role, layout, n_spots, tandem_ratio, n_vehicles, seed, n_runs,
                          wait_policy, strategy_name, random_reps, strat_params, env_params,
                          base_vehicles, demand_source_used, imported_meta):
    """云端运行仿真：全部对比 / 单策略，结果写入 session_state 并跳指标页。"""
    with st.spinner("仿真运行中..."):
        net, spots = LAYOUT_BUILDERS[layout](n_spots, tandem_ratio)
        pe = PathEngine(net)

        # 需求生成 / 引擎公共参数（多入口/多出口：把布局的口列表传给生成器，
        # 由随机种子独立分配；内置布局均为单入口且无出口，行为与旧版一致）
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

        if strategy_name == "compare_all":
            all_m = []
            timed_out_strategies = []
            failed_strategies = []
            main_events_raw = None
            events_by_strategy = {}
            vehicles_by_strategy = {}
            all_strategies = list(StrategyRegistry.all().items())
            total = len(all_strategies)
            prog = st.progress(0.0, text="准备运行全部策略对比...")
            for i, (nm, cls) in enumerate(all_strategies):
                runs_for_this = _n_runs_for(nm, n_runs, random_reps)
                prog.progress((i + 1) / total,
                              text=f"运行策略 {i + 1}/{total}：{cls.label}（{runs_for_this} 次取平均，超过 {int(STRATEGY_TIME_BUDGET)} 秒仅标记）")
                seed_metrics = []
                strategy_timed_out = False
                strategy_error = None
                for r in range(runs_for_this):
                    s = seed + r
                    vehs = (list(base_vehicles) if base_vehicles is not None
                            else generate_demand(seed=s, **demand_kwargs))
                    t_seed = time.time()
                    try:
                        m, ev, _ = run_single(net, spots, vehs, cls(), s, wait_policy, **eng_kwargs)
                    except Exception as e:
                        # 单个策略崩溃不拖垮整个对比（公网云端大参数易 OOM）
                        strategy_error = f"{type(e).__name__}: {e}"
                        break
                    # 60 秒仅作标记：超时种子结果仍保留、全部展示，可在指标页选择隐藏
                    if time.time() - t_seed > STRATEGY_TIME_BUDGET:
                        strategy_timed_out = True
                    seed_metrics.append(m)
                    # 每个策略都保留第一个种子的事件日志，供指标页「需求时序/车辆明细」切换查看；
                    # 主方法（时长感知贪心）的事件日志额外供「车辆动态路径」页展示
                    if r == 0:
                        ev_raw = [{"time": e.time, "type": e.event_type.value,
                                   "vehicle_id": e.vehicle_id or "", "spot_id": e.spot_id or "",
                                   "metadata": dict(e.metadata)} for e in ev]
                        events_by_strategy[nm] = ev_raw
                        vehicles_by_strategy[nm] = list(vehs)
                        if nm == "duration_greedy":
                            main_events_raw = ev_raw
                            sim_vehicles_candidate = list(vehs)
                if strategy_error:
                    failed_strategies.append((nm, strategy_error))
                if strategy_timed_out:
                    timed_out_strategies.append(nm)
                # 有已完成种子就取平均参与对比；全部种子失败则该策略无数据
                if seed_metrics:
                    all_m.append(_avg_metrics(seed_metrics))
            prog.empty()
            st.session_state.sim_all_metrics = all_m
            st.session_state.sim_timed_out_strategies = timed_out_strategies
            st.session_state.sim_failed_strategies = failed_strategies
            st.session_state.sim_metrics = next((m for m in all_m if m.get("strategy") == "duration_greedy"), None)
            # 主方法若首种子超时没有事件日志，回退到第一个成功策略的事件
            # （动态路径页依赖 sim_events_raw，不能为 None）
            if main_events_raw is None and events_by_strategy:
                first_nm = next(iter(events_by_strategy))
                main_events_raw = events_by_strategy[first_nm]
                sim_vehicles_candidate = vehicles_by_strategy.get(first_nm, sim_vehicles_candidate)
            st.session_state.sim_events_by_strategy = events_by_strategy
            st.session_state.sim_vehicles_by_strategy = vehicles_by_strategy
            st.session_state.sim_events_raw = main_events_raw
        else:
            seed_metrics = []
            events_raw = None
            strategy_timed_out = False
            for r in range(_n_runs_for(strategy_name, n_runs, random_reps)):
                s = seed + r
                vehs = (list(base_vehicles) if base_vehicles is not None
                        else generate_demand(seed=s, **demand_kwargs))
                # 每次新建策略实例（避免有状态策略跨 run 污染）
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
                # 60 秒仅作标记：超时种子结果仍保留、全部展示
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
