"""指标分析页：需求时序分布与车辆明细（跟随所选策略）。"""
from ui.common import *


def _render_demand_section(visible_all_m, can_export):
    """需求时序分布 + 车辆明细 + 需求序列导出。"""
    st.markdown("---")
    st.markdown("### 🕒 需求时序分布与车辆明细")
    demand_source = st.session_state.get("sim_demand_source", "generated")
    events_by_strategy = st.session_state.get("sim_events_by_strategy") or {}
    vehicles_by_strategy = st.session_state.get("sim_vehicles_by_strategy") or {}

    view_strategy = None
    if visible_all_m:
        view_options = [m.get("strategy") for m in visible_all_m
                        if m.get("strategy") in events_by_strategy]
        if view_options:
            default_idx = view_options.index("duration_greedy") if "duration_greedy" in view_options else 0
            if st.session_state.get("demand_view_strategy") not in view_options:
                st.session_state.demand_view_strategy = view_options[default_idx]
            view_strategy = st.selectbox(
                "选择要查看的策略",
                view_options,
                format_func=lambda n: STRATEGY_LABELS.get(n, n),
                key="demand_view_strategy",
                help="「全部对比」模式下可切换查看各策略的需求时序与车辆明细",
            )
            events_raw = events_by_strategy.get(view_strategy)
            vehs = vehicles_by_strategy.get(view_strategy)
        else:
            events_raw = None
            vehs = None
        if demand_source in ("imported", "real_gate"):
            src_label = "真实道闸流水" if demand_source == "real_gate" else "导入的需求序列"
            st.caption(f"事件日志来自{src_label}；当前展示策略："
                       f"**{STRATEGY_LABELS.get(view_strategy, view_strategy) if view_strategy else '—'}**。")
        else:
            st.caption("事件日志来自最近一次仿真；当前展示策略："
                       f"**{STRATEGY_LABELS.get(view_strategy, view_strategy) if view_strategy else '—'}**。")
    else:
        events_raw = st.session_state.get("sim_events_raw")
        vehs = st.session_state.get("sim_vehicles")
        if demand_source in ("imported", "real_gate"):
            src_label = "真实道闸流水" if demand_source == "real_gate" else "导入的需求序列"
            st.caption(f"事件日志来自{src_label}（所选策略）。")
        else:
            st.caption("事件日志来自最近一次仿真（所选策略）。")

    if not events_raw:
        st.info("暂无事件日志（请先运行仿真）")
        return

    hist = build_demand_histogram(events_raw)
    if hist is not None:
        st.plotly_chart(hist, use_container_width=True)
    else:
        st.info("暂无到达/离场事件")
    rows = build_vehicle_detail_rows(events_raw)
    if rows:
        vdf = pd.DataFrame(rows)
        st.dataframe(vdf, use_container_width=True, hide_index=True)
        if can_export:
            st.download_button("📥 下载车辆明细 CSV",
                               vdf.to_csv(index=False).encode('utf-8-sig'),
                               "parking_vehicle_details.csv", "text/csv")
    if not vehs:
        return
    meta = st.session_state.get("sim_demand_meta") or {}
    json_str = export_demand_json(
        vehs,
        seed=meta.get("seed"),
        source=demand_source,
        generator_params=meta.get("generator_params"),
        generated_at=meta.get("generated_at"),
    )
    default_name = f"demand_{demand_source}_{time.strftime('%Y%m%d_%H%M%S')}.json"
    download_name = f"parking_demand_{time.strftime('%Y%m%d_%H%M%S')}.json"
    if can_export:
        cdl, csave = st.columns(2)
        with cdl:
            st.download_button("📥 浏览器下载",
                               json_str.encode("utf-8"),
                               download_name, "application/json")
            st.caption("每次下载文件名带时间戳，不会重名")
        with csave:
            render_save_as_button(json_str, download_name)
        if is_local_desktop():
            if st.button("💾 下载到项目文件夹（仅本机运行可用）",
                         use_container_width=True, key="save_demand_project",
                         help="一键保存到本机项目的 data/demand_exports/（自动命名），"
                              "回仿真设置页可从下拉直接导入，方便快速测试复现性"):
                saved = save_demand_to_project(
                    vehs, seed=meta.get("seed"), source=demand_source,
                    generator_params=meta.get("generator_params"),
                    generated_at=meta.get("generated_at"))
                st.success(f"✅ 已保存：{saved.name}")
                st.caption("回「仿真设置 → 导入需求序列 JSON → 从项目文件夹选择」即可快速导入")
        with st.expander("💾 保存到指定位置（长期保留：自选目录与文件名）", expanded=False):
            cdir, cfile = st.columns(2)
            with cdir:
                save_dir = st.text_input(
                    "保存目录", str(DEMAND_EXPORT_DIR), key="save_dir_input",
                    help="绝对路径，或相对项目根目录的路径（默认 data/demand_exports/）")
            with cfile:
                save_name = st.text_input(
                    "文件名", default_name, key="save_name_input",
                    help="不含 .json 后缀会自动补上；填完整路径则忽略左侧目录")
            if st.button("💾 保存到该位置", key="save_demand_manual"):
                try:
                    name_p = Path(save_name)
                    if name_p.is_absolute():
                        target = name_p
                    else:
                        base = Path(save_dir)
                        if not base.is_absolute():
                            base = PROJECT_ROOT / base
                        target = base / save_name
                    saved_path = save_demand_to_path(
                        vehs, target,
                        seed=meta.get("seed"),
                        source=demand_source,
                        generator_params=meta.get("generator_params"),
                        generated_at=meta.get("generated_at"),
                    )
                    st.success(f"✅ 已保存：{saved_path}")
                except OSError as exc:
                    st.error(f"❌ 保存失败：{exc}")
