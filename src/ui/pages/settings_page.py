"""页面1：仿真设置（组装各控件区 + 运行调度）。"""
from ui.common import *
from ui.pages.demand_source import _render_demand_source
from ui.pages.layout_strategy import _render_layout_and_strategy
from ui.pages.mosa_hint import _render_mosa_hint
from ui.pages.rank_settings import _render_rank_settings, _render_compute_mode
from ui.pages.cloud_run import _run_cloud_simulation
from ui.pages.compare_all_run import _run_compare_all_cloud
from ui.pages.auto_tune import _run_auto_tune_cloud, _render_tune_summary
from ui.pages.local_task_ops import _submit_local_task_and_wait, _render_local_compute_section


def _render_run_options(disabled, strategy_name):
    """渲染「计算内容」三动作复选框，返回 (run_default, auto_tune, tune_run)。

    run_default：按当前参数跑仿真/排序；auto_tune：自动调参选最优；
    tune_run：调参完成后用最优参数跑仿真/排序（依赖 auto_tune）。
    """
    is_compare = strategy_name == "compare_all"
    tunable = bool(strategy_name and strategy_name != "compare_all"
                   and tunable_specs(strategy_name))
    if not (is_compare or tunable):
        return True, False, False
    st.markdown("#### 🧮 计算内容（可多选，可只调参）")
    run_label = "按当前参数跑排序" if is_compare else "按当前参数跑仿真"
    tune_run_label = "用最优参数跑排序" if is_compare else "用最优参数跑仿真"
    c1, c2 = st.columns(2)
    with c1:
        run_default = st.checkbox(run_label, value=True, disabled=disabled,
                                  help="用上方控件里当前填好的参数跑正式仿真/排序")
    with c2:
        auto_tune = st.checkbox("🎯 自动调参选最优", value=False, disabled=disabled,
                                help="随机试 K 组参数，按当前排名设置选最优；"
                                     "单策略回填控件，全部对比保存各算法最优参数")
        tune_run = st.checkbox(tune_run_label, value=False,
                               disabled=disabled or not auto_tune,
                               help="调参完成后，自动用选出的最优参数再跑一次"
                                    "（需先勾选「自动调参选最优」）")
    return bool(run_default), bool(auto_tune), bool(tune_run)


def render_settings(role):
    """页面1: 仿真设置"""
    ensure_custom_layouts_loaded()
    st.subheader("⚙️ 仿真参数配置")
    disabled = not role["can_configure"]
    if disabled: st.caption("⚠️ 当前角色仅可查看，不可修改参数")

    import_mode, gate_mode, imported_vehicles, imported_meta = _render_demand_source(disabled, role)

    (layout, real_layout_mode, n_spots, tandem_ratio, n_vehicles, seed,
     n_runs, wait_policy, strategy_name, strategy_category, random_reps, strat_params,
     env_params, tune_trials, compare_names) = _render_layout_and_strategy(disabled, import_mode)

    _render_mosa_hint(strategy_name, import_mode, imported_vehicles, real_layout_mode,
                      n_spots, tandem_ratio, n_vehicles, env_params, layout)

    _render_rank_settings(disabled)
    compute_mode = _render_compute_mode(role)

    # 需求来源（导入序列所有 run/策略复用同一批，保证公平；否则按种子生成）
    base_vehicles = list(imported_vehicles) if imported_vehicles else None
    if base_vehicles is not None:
        demand_source_used = ("real_gate"
                              if (imported_meta or {}).get("source") == "real_gate"
                              else "imported")
    else:
        demand_source_used = "generated"

    ctx_kwargs = dict(
        layout=layout, n_spots=n_spots, tandem_ratio=tandem_ratio,
        strategy_name=strategy_name, strat_params=strat_params, env_params=env_params,
        wait_policy=wait_policy, seed=seed, n_runs=n_runs, random_reps=random_reps,
        base_vehicles=base_vehicles, demand_source_used=demand_source_used,
        imported_meta=imported_meta, n_vehicles=n_vehicles)

    if compute_mode == "local":
        _render_local_compute_section(ctx_kwargs, role)

    # 公网云端资源受限，大参数提前提示（本地 Windows 桌面不提示）
    if (not is_local_desktop() and compute_mode == "cloud"
            and (n_vehicles >= 500 or n_spots >= 200)):
        st.info("🌐 当前在**公网云端**运行：车辆/车位较多时容易内存不足或超时。\n"
                "可切换到上面的「💻 本地计算」，并在本机运行 `py local_worker.py`。")

    run_default, auto_tune, tune_run = _render_run_options(disabled, strategy_name)

    run_label = "▶️ 下发本地计算任务" if compute_mode == "local" else "▶️ 运行仿真"
    run_allowed = role["can_local_compute"] if compute_mode == "local" else role["can_run_simulation"]
    compare_empty = (strategy_name == "compare_all" and not compare_names)
    run_disabled = (not run_allowed) or (not strategy_name) or compare_empty \
        or not (run_default or auto_tune)

    _render_tune_summary()

    if st.button(run_label, type="primary", use_container_width=True, disabled=run_disabled):
        if compute_mode == "local":
            _submit_local_task_and_wait(layout, n_spots, tandem_ratio, strategy_name,
                                        strategy_category, strat_params, env_params,
                                        wait_policy, seed, n_runs, random_reps,
                                        base_vehicles, demand_source_used, n_vehicles,
                                        ctx_kwargs, run_default=run_default,
                                        auto_tune=auto_tune, tune_run=tune_run,
                                        tune_trials=tune_trials,
                                        compare_names=compare_names)
            st.stop()
        if strategy_name == "compare_all":
            _run_compare_all_cloud(role, layout, n_spots, tandem_ratio, n_vehicles, seed,
                                   n_runs, wait_policy, strategy_category, random_reps,
                                   strat_params, env_params, base_vehicles,
                                   demand_source_used, imported_meta,
                                   run_default, auto_tune, tune_run, tune_trials,
                                   compare_names=compare_names)
        else:
            best_params = {}
            if auto_tune:
                best_params = _run_auto_tune_cloud(layout, n_spots, tandem_ratio, n_vehicles,
                                                   seed, wait_policy, strategy_name,
                                                   env_params, base_vehicles, tune_trials)
            ran = False
            if run_default:
                _run_cloud_simulation(role, layout, n_spots, tandem_ratio, n_vehicles,
                                      seed, n_runs, wait_policy, strategy_name,
                                      strategy_category, random_reps, strat_params,
                                      env_params, base_vehicles, demand_source_used,
                                      imported_meta, rerun_after=False)
                ran = True
            if tune_run and auto_tune and best_params:
                _run_cloud_simulation(role, layout, n_spots, tandem_ratio, n_vehicles,
                                      seed, n_runs, wait_policy, strategy_name,
                                      strategy_category, random_reps, best_params,
                                      env_params, base_vehicles, demand_source_used,
                                      imported_meta, rerun_after=False)
                ran = True
            if ran:
                st.rerun()
            st.success("🎯 自动调参完成，最优参数已回填上方控件。\n\n"
                       "想直接看结果：勾选「🚀 用最优参数跑仿真」后再点运行；"
                       "或点「▶️ 运行仿真」用当前参数跑。")
            st.rerun()
