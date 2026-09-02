"""页面5：指标分析（主流程：提示/排名设置/对比/明细/需求/调优历史）。"""
from ui.common import *
from ui.pages.metric_card import _metric
from ui.pages.metrics_compare import _render_compare_section
from ui.pages.metrics_single import _render_single_strategy
from ui.pages.metrics_demand import _render_demand_section


def render_metrics_page(role):
    """页面5: 指标分析"""
    st.subheader("📊 指标分析")
    can_export = role.get("can_export", False)
    if not st.session_state.get("sim_has_run"):
        st.info("👈 请先在 **仿真设置** 中运行仿真")
        return

    # 超时仅作标记：结果全部展示，可勾选隐藏含超时种子的策略
    timed_out = st.session_state.get("sim_timed_out_strategies") or []
    sim_all_metrics = st.session_state.get("sim_all_metrics") or []
    hide_timed_out = False
    if timed_out:
        names = "、".join(STRATEGY_LABELS.get(n, n) for n in timed_out)
        st.warning(f"⏱ 以下策略有种子单次运行超过 {int(STRATEGY_TIME_BUDGET)} 秒（结果仍全部展示）：{names}")
        if sim_all_metrics:
            hide_timed_out = st.checkbox(
                "隐藏超时策略", value=False,
                help="勾选后，含超时种子的策略不参与排名、表格与图表展示")

    # 运行失败策略（单个策略崩溃不拖垮全部对比）
    failed = st.session_state.get("sim_failed_strategies") or []
    if failed:
        names = "、".join(f"{STRATEGY_LABELS.get(n, n)}（{err}）" for n, err in failed)
        st.error(f"⚠️ 以下策略运行失败、未参与对比：{names}")
        if not is_local_desktop():
            st.info("公网云端资源受限（内存/CPU），大参数容易失败。\n"
                    "建议改在本地运行：`py -m streamlit run app.py`（本机计算，云端只存数据）。")

    # 排名设置展示：与仿真设置页一致（权重 / 优先级）
    rank_mode = st.session_state.get("rank_mode", "加权评分")
    if rank_mode == "加权评分":
        st.markdown("### 🎚️ 指标权重（在仿真设置页调整）")
        weights_show = st.session_state.get("rank_weights", DEFAULT_WEIGHTS_BY_LABEL)
        wsum = sum(weights_show.values())
        wtab = pd.DataFrame([
            [name, weights_show.get(name, 0),
             "越高越好" if PRIORITY_METRICS[name][1] == "max" else "越低越好",
             PRIORITY_METRICS[name][2]]
            for name in list(PRIORITY_METRICS.keys())
        ], columns=["指标", "权重", "方向", "说明"])
        st.dataframe(wtab, use_container_width=True, hide_index=True)
        st.caption(f"权重总和 {wsum}{'（≠100，排名时按比例归一化）' if wsum != 100 else ' = 100 ✅'}")
    else:
        st.markdown("### 🎯 算法筛选优先级（字典序）")
        st.caption("按以下顺序逐项比较：先比第一项，相同再比下一项")
        priority_order = st.session_state.get("priority_order", DEFAULT_PRIORITY)
        prio = pd.DataFrame([
            [i + 1, name,
             "越高越好" if PRIORITY_METRICS[name][1] == "max" else "越低越好",
             PRIORITY_METRICS[name][2]]
            for i, name in enumerate(priority_order)
        ], columns=["优先级", "评估指标", "方向", "说明"])
        st.dataframe(prio, use_container_width=True, hide_index=True)
    st.markdown("---")

    # 多策略对比 / 单策略详情
    timed_out_set = set(timed_out)
    visible_all_m = [m for m in sim_all_metrics
                     if not (hide_timed_out and m.get("strategy") in timed_out_set)]
    if visible_all_m:
        _render_compare_section(visible_all_m, can_export)
    elif sim_all_metrics:
        st.info("所有策略均含超时种子且已被隐藏。取消勾选「隐藏超时策略」即可查看。")
    else:
        _render_single_strategy(can_export)

    # 需求时序分布与车辆明细（跟随所选策略）
    _render_demand_section(visible_all_m, can_export)

    # ── 参数调优历史（每策略最近 5 次）──
    history = st.session_state.get("run_history", {})
    if history:
        st.markdown("---")
        st.markdown("### 🧪 参数调优历史（每策略最近5次）")
        strat_names = list(history.keys())
        sel = st.selectbox("选择策略查看调参历史", strat_names,
                           format_func=lambda n: STRATEGY_LABELS.get(n, n))
        records = history.get(sel, [])
        if records:
            rows = []
            for i, rec in enumerate(records):
                m = rec.get("metrics", {})
                params_str = ", ".join(f"{k}={v}" for k, v in rec.get("params", {}).items()) or "默认"
                rows.append({
                    "序号": f"#{i + 1}",
                    "时间": rec.get("time", ""),
                    "参数": params_str,
                    "满足率": m.get("satisfaction_rate"),
                    "利用率": m.get("spatial_utilization"),
                    "移位次数": m.get("shift_count"),
                    "移位距离(m)": m.get("shift_distance_m"),
                    "平均等待(s)": m.get("avg_wait_time_s"),
                    "拒绝数": m.get("rejected_count"),
                })
            hdf = pd.DataFrame(rows)
            st.dataframe(hdf.style.format({
                "满足率": "{:.1%}", "利用率": "{:.1%}",
                "移位距离(m)": "{:.1f}", "平均等待(s)": "{:.1f}",
            }), use_container_width=True, hide_index=True)
            if len(records) > 1:
                st.bar_chart(hdf.set_index("序号")["满足率"], height=200)
        else:
            st.info("该策略暂无运行历史")
        if st.button("🗑 清空全部历史", key="clear_history"):
            st.session_state.run_history = {}
            st.rerun()
