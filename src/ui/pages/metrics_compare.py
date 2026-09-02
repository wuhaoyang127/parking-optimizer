"""指标分析页：多策略对比（加权排名 / 字典序 / 图表 / 雷达图）。"""
from ui.common import *


def _render_compare_section(all_m, can_export):
    """多策略对比：排序模式在仿真设置页配置，此处按配置展示。"""
    st.markdown("### 🏆 多策略对比")
    n_runs = st.session_state.get("sim_n_runs", 1)
    demand_source = st.session_state.get("sim_demand_source", "generated")
    src_note = ("同一导入需求序列" if demand_source in ("imported", "real_gate")
                else f"{n_runs} 次不同随机种子的平均值（降低随机波动）")
    random_reps = st.session_state.get("sim_random_reps")
    if random_reps:
        src_note += f"；random 策略单独取 {int(random_reps)} 次平均"
    st.caption(f"基于 {src_note}")

    rank_mode = st.session_state.get("rank_mode", "加权评分")

    if rank_mode == "加权评分":
        weights_by_label = st.session_state.get("rank_weights", DEFAULT_WEIGHTS_BY_LABEL)
        st.caption("当前为加权评分模式；权重在「仿真设置 → 算法排名设置」中调整")
        wdf, ranked = weighted_rank_df(all_m, weights_by_label)
        neutrals = neutralized_metric_labels(all_m)
        if neutrals:
            st.caption("⚖️ 以下指标各策略差异低于实际意义阈值，已按无区分度处理（不参与排名）："
                       + "、".join(neutrals))
        best = ranked[0]
        st.markdown(f'> 🏆 加权推荐: **{STRATEGY_LABELS.get(best["strategy"], best["strategy"])}**'
                    f' 综合得分 {best["weighted_score"]:.3f}（满分 1.0）')
        cpsat_rate = st.session_state.get("sim_cpsat_rate")
        if cpsat_rate is not None:
            gap = best["satisfaction_rate"] - cpsat_rate
            st.markdown(f'> 🎯 理论最优（CP-SAT 离线全信息）满足率 **{cpsat_rate:.1%}**，'
                        f'推荐策略距最优 {gap:.1%}')
        df = wdf
        styled = (df.style
                  .format({"综合得分": "{:.3f}", "满足率": "{:.1%}", "利用率": "{:.1%}",
                           "平均等待(s)": "{:.1f}", "移位距离(m)": "{:.1f}",
                           "行驶距离(m)": "{:.1f}", "耗时(s)": "{:.3f}"})
                  .apply(lambda row: ['background-color: #d4edda' if row.name == 0
                                      else '' for _ in row], axis=1))
        st.dataframe(styled, use_container_width=True, hide_index=True)
        if can_export:
            st.download_button("📥 下载加权排名 CSV", wdf.to_csv(index=False).encode('utf-8'),
                               "parking_weighted_ranking.csv", "text/csv")
    else:
        # 按用户定义的优先级做字典序排序（原有逻辑，保留）
        priority_order = st.session_state.get("priority_order", DEFAULT_PRIORITY)
        def sort_key(m):
            key = []
            for name in priority_order:
                if name not in PRIORITY_METRICS:
                    continue
                field, direction, _ = PRIORITY_METRICS[name]
                val = m.get(field, 0)
                key.append(-val if direction == "max" else val)
            return tuple(key)
        sorted_m = sorted(all_m, key=sort_key)
        best = sorted_m[0]
        df = pd.DataFrame(sorted_m)[["strategy", "satisfaction_rate", "spatial_utilization",
                                     "avg_wait_time_s", "shift_count", "shift_distance_m",
                                     "total_drive_distance_m", "rejected_count", "runtime_s"]]
        df.columns = ["策略", "满足率", "利用率", "平均等待(s)", "移位次数",
                      "移位距离(m)", "行驶距离(m)", "拒绝数", "耗时(s)"]
        st.markdown(f'> 🏆 推荐: **{STRATEGY_LABELS.get(best["strategy"], best["strategy"])}**'
                    f' 满足率 {best["satisfaction_rate"]:.1%}')
        cpsat_rate = st.session_state.get("sim_cpsat_rate")
        if cpsat_rate is not None:
            gap = best["satisfaction_rate"] - cpsat_rate
            st.markdown(f'> 🎯 理论最优（CP-SAT 离线全信息）满足率 **{cpsat_rate:.1%}**，'
                        f'最佳策略距最优 {gap:.1%}')
        styled = (df.style
                  .format({"满足率": "{:.1%}", "利用率": "{:.1%}", "平均等待(s)": "{:.1f}",
                           "移位距离(m)": "{:.1f}", "行驶距离(m)": "{:.1f}", "耗时(s)": "{:.3f}"})
                  .apply(lambda row: ['background-color: #d4edda' if row.name == 0
                                      else '' for _ in row], axis=1))
        st.dataframe(styled, use_container_width=True, hide_index=True)
        if can_export:
            st.download_button("📥 下载 CSV", df.to_csv(index=False).encode('utf-8'),
                               "parking_comparison.csv", "text/csv")

    c1, c2 = st.columns(2)
    with c1: st.bar_chart(df.set_index("策略")["满足率"], height=200)
    with c2: st.bar_chart(df.set_index("策略")["移位次数"], height=200)
    st.markdown("#### 📡 多维指标雷达图（外圈=更好）")
    st.plotly_chart(_plot_radar(all_m), use_container_width=True)
