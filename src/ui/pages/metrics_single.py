"""指标分析页：单策略详情（指标卡片 + 理论最优对比）。"""
from ui.common import *
from ui.pages.metric_card import _metric


def _render_single_strategy(can_export):
    """单策略模式：展示该策略各指标卡片。"""
    m = st.session_state.get("sim_metrics")
    if not m:
        return
    st.markdown(f"### 📈 策略: {STRATEGY_LABELS.get(m['strategy'], m['strategy'])}")
    if st.session_state.get("rank_mode", "加权评分") == "加权评分":
        st.caption("当前为加权评分模式（权重见上方表格）；单策略无对比基准，此处展示该策略各指标，"
                   "加权排名请运行「全部对比」。")
    else:
        st.caption("当前为字典序优先级模式（优先级见上方表格）。")
    c1, c2, c3, c4 = st.columns(4)
    with c1: _metric("满足率", f"{m['satisfaction_rate']:.1%}", "good" if m['satisfaction_rate']>0.5 else "bad")
    with c2: _metric("空间利用率", f"{m['spatial_utilization']:.1%}")
    with c3: _metric("移位次数", str(m['shift_count']), "warn" if m['shift_count']>0 else "")
    with c4: _metric("拒绝数", str(m['rejected_count']), "bad" if m['rejected_count']>0 else "")
    c5, c6, c7, c8 = st.columns(4)
    with c5: _metric("行驶距离", f"{m['total_drive_distance_m']:.0f}m")
    with c6: _metric("移位距离", f"{m['shift_distance_m']:.0f}m")
    with c7: _metric("平均等待", f"{m['avg_wait_time_s']:.1f}s")
    with c8: _metric("运行耗时", f"{m['runtime_s']:.3f}s")
    cpsat_rate = st.session_state.get("sim_cpsat_rate")
    if cpsat_rate is not None:
        gap = m["satisfaction_rate"] - cpsat_rate
        st.markdown(f'> 🎯 理论最优（CP-SAT）满足率 **{cpsat_rate:.1%}**，当前策略距最优 {gap:.1%}')
    buffers = m.get('buffer_failed_count', 0)
    rejs = m.get('rejected_count', 0)
    if buffers or rejs:
        st.warning(f"⚠️ 降级: {buffers} 缓冲失败, {rejs} 拒绝")
    if can_export:
        st.download_button("📥 下载指标", pd.DataFrame([m]).to_csv(index=False).encode('utf-8'),
                           f"parking_{m.get('strategy','result')}.csv", "text/csv")
