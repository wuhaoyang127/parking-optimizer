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
                         strategy_name, env_params, base_vehicles):
    """云端进程内自动调参：跑 K 组单种子仿真，选最优回填参数控件。"""
    net, spots = LAYOUT_BUILDERS[layout](n_spots, tandem_ratio)
    pe = PathEngine(net)
    vehs = _tune_vehicles(base_vehicles, n_vehicles, env_params, pe, seed)
    ranking = ranking_config_from_session()
    eng_kwargs = dict(car_speed=env_params["car_speed"],
                      max_wait_time=env_params["max_wait_time"])
    label = STRATEGY_LABELS.get(strategy_name, strategy_name)
    prog = st.progress(0.0, text=f"🎯 自动调参：{label}（0/{TUNE_TRIALS_DEFAULT}）…")

    def cb(done, total, params):
        prog.progress(done / total,
                      text=f"🎯 自动调参：{label}（{done}/{total}）…")

    try:
        res = run_tuning(strategy_name, net, spots, vehs, seed, wait_policy,
                         eng_kwargs, TUNE_TRIALS_DEFAULT, ranking["mode"],
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
        return
    persist_last_params(strategy_name, best_params)
    st.session_state.last_tune_summary = {
        "strategy": strategy_name, "trials": res["trials"],
        "failed": res.get("failed", 0)}
    st.rerun()


def _apply_tune_result(result):
    """把本地调参任务结果回填参数控件并刷新设置页。"""
    if not isinstance(result, dict):
        st.error("调参结果为空，无法应用")
        st.stop()
    tuned = result.get("tuned_params") or {}
    trials = result.get("tune_trials") or []
    if not tuned:
        st.info("该算法没有可调参数，无需调参。")
        return
    for name, params in tuned.items():
        if isinstance(params, dict) and params:
            persist_last_params(name, params)
    st.session_state.last_tune_summary = {
        "strategy": next(iter(tuned), ""), "trials": trials,
        "failed": result.get("failed", 0)}
    st.rerun()


def _render_tune_summary():
    """设置页展示最近一次自动调参摘要（最优参数已回填控件）。"""
    summary = st.session_state.get("last_tune_summary")
    if not summary:
        return
    trials = summary.get("trials") or []
    with st.expander("🎯 上次自动调参摘要", expanded=True):
        st.caption(f"策略：{STRATEGY_LABELS.get(summary.get('strategy', ''), summary.get('strategy'))}"
                   f"；共 {len(trials)} 组，最优参数已自动填入上方控件。")
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
