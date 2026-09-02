"""页面1：仿真设置（组装各控件区 + 运行调度）。"""
from ui.common import *
from ui.pages.demand_source import _render_demand_source
from ui.pages.layout_strategy import _render_layout_and_strategy
from ui.pages.mosa_hint import _render_mosa_hint
from ui.pages.rank_settings import _render_rank_settings, _render_compute_mode
from ui.pages.cloud_run import _run_cloud_simulation
from ui.pages.local_task_ops import _submit_local_task_and_wait, _render_local_compute_section


def render_settings(role):
    """页面1: 仿真设置"""
    ensure_custom_layouts_loaded()
    st.subheader("⚙️ 仿真参数配置")
    disabled = not role["can_configure"]
    if disabled: st.caption("⚠️ 当前角色仅可查看，不可修改参数")

    import_mode, gate_mode, imported_vehicles, imported_meta = _render_demand_source(disabled, role)

    (layout, real_layout_mode, n_spots, tandem_ratio, n_vehicles, seed,
     n_runs, wait_policy, strategy_name, random_reps, strat_params,
     env_params) = _render_layout_and_strategy(disabled, import_mode)

    _render_mosa_hint(strategy_name, import_mode, imported_vehicles, real_layout_mode,
                      n_spots, tandem_ratio, n_vehicles, env_params, layout)

    _render_rank_settings(disabled)
    compute_mode = _render_compute_mode()

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
        _render_local_compute_section(ctx_kwargs)

    # 公网云端资源受限，大参数提前提示（本地 Windows 桌面不提示）
    if (not is_local_desktop() and compute_mode == "cloud"
            and (n_vehicles >= 500 or n_spots >= 200)):
        st.info("🌐 当前在**公网云端**运行：车辆/车位较多时容易内存不足或超时。\n"
                "可切换到上面的「💻 本地计算」，并在本机运行 `py local_worker.py`。")

    run_label = "▶️ 下发本地计算任务" if compute_mode == "local" else "▶️ 运行仿真"
    if st.button(run_label, type="primary", use_container_width=True,
                 disabled=not role["can_run_simulation"]):
        if compute_mode == "local":
            _submit_local_task_and_wait(layout, n_spots, tandem_ratio, strategy_name,
                                        strat_params, env_params, wait_policy, seed,
                                        n_runs, random_reps, base_vehicles,
                                        demand_source_used, n_vehicles, ctx_kwargs)
            st.stop()
        _run_cloud_simulation(role, layout, n_spots, tandem_ratio, n_vehicles, seed,
                              n_runs, wait_policy, strategy_name, random_reps,
                              strat_params, env_params, base_vehicles,
                              demand_source_used, imported_meta)
