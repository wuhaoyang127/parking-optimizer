"""单策略自动调参：云端进程内运行 / 本地任务结果应用 / 调参摘要展示。"""
from ui.common import *


def _tune_vehicles(base_vehicles, n_vehicles, env_params, pe, seed):
    """构造调参用车辆序列（导入需求复用，否则按当前种子生成一次）。"""
    if base_vehicles is not None:
        return list(base_vehicles)
    demand_kwargs = dict(total_vehicles=n_vehicles,
                         sim_duration=env_params["sim_duration"],
                         duration_min=env_params["duration_min"],
                         duration_max=env_params["duration_max"],
                         peak_ratio=env_params["peak_ratio"],
                         error_ratio=env_params["error_ratio"],
                         entry_ids=pe.entry_ids,
                         exit_ids=pe.exit_ids)
    return generate_demand(seed=seed, **demand_kwargs)


def _run_auto_tune_cloud(layout, n_spots, tandem_ratio, n_vehicles, seed, wait_policy,
                         strategy_name, env_params, base_vehicles, tune_trials) -> dict:
    """云端进程内自动调参：跑 K 组单种子仿真，选最优回填参数控件并返回最优参数。

    不在此处跑正式仿真（由调用方决定是否用最优参数继续跑）。
    """
    net, spots = LAYOUT_BUILDERS[layout](n_spots, tandem_ratio)
    pe = PathEngine(net)
    vehs = _tune_vehicles(base_vehicles, n_vehicles, env_params, pe, seed)
    ranking = ranking_config_from_session()
    eng_kwargs = dict(car_speed=env_params["car_speed"],
                      max_wait_time=env_params["max_wait_time"],
                      buffer_w_distance=env_params.get("buffer_w_distance", 1.0),
                      buffer_w_idle=env_params.get("buffer_w_idle", 1.0),
                      buffer_w_secondary=env_params.get("buffer_w_secondary", 2.0),
                      buffer_idle_half_life=env_params.get("buffer_idle_half_life", 300.0))
    label = STRATEGY_LABELS.get(strategy_name, strategy_name)
    prog = st.progress(0.0, text=f"🎯 自动调参：{label}（0/{tune_trials}）…")

    def cb(done, total, params):
        prog.progress(done / total,
                      text=f"🎯 自动调参：{label}（{done}/{total}）…")

    try:
        res = run_tuning(strategy_name, net, spots, vehs, seed, wait_policy,
                         eng_kwargs, tune_trials, ranking["mode"],
                         ranking["weights"], ranking["priority"],
                         budget=STRATEGY_TIME_BUDGET, progress_cb=cb)
    except Exception as exc:
        prog.empty()
        st.error(f"❌ 自动调参失败：{type(exc).__name__}: {exc}")
        st.stop()
    prog.empty()
    best_params = res["best_params"] or {}
    if not best_params:
        st.info("该算法没有可调参数，无需调参。")
        return {}
    persist_last_params(strategy_name, best_params)
    st.session_state.last_tune_summary = {
        "strategy": strategy_name, "best_params": best_params,
        "trials": res["trials"], "failed": res.get("failed", 0)}
    return best_params


def _render_tune_summary():
    """设置页展示最近一次自动调参摘要（单策略：最优参数已回填；全部对比：各算法最优参数）。"""
    summary = st.session_state.get("last_tune_summary")
    if not summary:
        return
    if summary.get("strategy") == "compare_all":
        tuned_params = summary.get("tuned_params") or {}
        with st.expander("🎯 上次自动调参摘要（全部对比）", expanded=True):
            st.caption(f"每个算法试 {summary.get('trials_per_algo', '')} 组，"
                       "最优参数已保存；勾选「🚀 用最优参数跑排序」可再次运行。")
            if tuned_params:
                rows = [{"策略": STRATEGY_LABELS.get(n, n),
                         "最优参数": ", ".join(f"{k}={v:.4g}" if isinstance(v, float)
                                             else f"{k}={v}"
                                             for k, v in params.items())}
                        for n, params in tuned_params.items() if params]
                if rows:
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        return
    trials = summary.get("trials") or []
    best_params = summary.get("best_params") or {}
    with st.expander("🎯 上次自动调参摘要", expanded=True):
        st.caption(f"策略：{STRATEGY_LABELS.get(summary.get('strategy', ''), summary.get('strategy'))}"
                   f"；共 {len(trials)} 组，最优参数已自动填入上方控件。")
        if best_params:
            best_txt = ", ".join(f"**{k}** = {v:.4g}" if isinstance(v, float) else f"**{k}** = {v}"
                                 for k, v in best_params.items())
            st.markdown(f"✅ **最优参数**：{best_txt}")
        if trials:
            rows = []
            for i, t in enumerate(trials, 1):
                m = t.get("metrics") or {}
                rows.append({
                    "组": i,
                    "参数": ", ".join(f"{k}={v:.4g}" if isinstance(v, float)
                                    else f"{k}={v}" for k, v in (t.get("params") or {}).items()),
                    "满足率": m.get("satisfaction_rate"),
                    "移位次数": m.get("shift_count"),
                    "平均等待(s)": m.get("avg_wait_time_s"),
                    "超60s": "是" if t.get("timed_out") else "",
                })
            tdf = pd.DataFrame(rows)
            st.dataframe(tdf.style.format({
                "满足率": "{:.1%}", "平均等待(s)": "{:.1f}",
            }), use_container_width=True, hide_index=True)
