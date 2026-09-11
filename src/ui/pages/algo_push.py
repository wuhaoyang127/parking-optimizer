"""页面区块：推送到车主端（仅管理员或已开启 can_push_algo 的自定义角色）。"""
from ui.common import *


def _owner_app_connected(value) -> bool:
    """解析车主端接入开关：'1'/'true'/'yes'/'on' 视为已接入，其余视为未接入。"""
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


# 车主端接入开关：车主端 FastAPI 接入前，推送按钮仅备用（点击只提示，不写库）。
# 车主端接入后设置环境变量 OWNER_APP_CONNECTED=1（或 true/yes/on）并重新部署即可启用。
OWNER_APP_CONNECTED = _owner_app_connected(os.environ.get("OWNER_APP_CONNECTED", "0"))


def _best_algo_from_runs(runs, weights):
    """从 sim_runs 记录计算当前测试最优算法。

    runs: list[dict]，每项至少含 strategy / metrics / created_at
          （auth_list_sim_runs 的输出格式）。
    weights: 指标字段名权重（ranking.DEFAULT_WEIGHTS 或用户自定义权重）。

    优先用最近一次「全部对比」（strategy == compare_all）的 metrics 列表参与
    加权排名；否则把各策略的单次运行指标按策略平均后参与排名。
    返回 (best_name, ranked_list, source)；无可用记录返回 (None, [], "")。
    """
    if not runs:
        return None, [], ""
    ordered = sorted(runs, key=lambda r: str(r.get("created_at") or ""),
                     reverse=True)

    # 1) 最近一次「全部对比」结果
    for run in ordered:
        if run.get("strategy") != "compare_all":
            continue
        metrics = run.get("metrics")
        if isinstance(metrics, list) and metrics:
            cleaned = [m for m in metrics
                       if isinstance(m, dict) and m.get("strategy")]
            if cleaned:
                ranked = weighted_rank(cleaned, weights)
                if ranked:
                    return ranked[0].get("strategy"), ranked, "最近一次「全部对比」"

    # 2) 单策略运行记录按策略平均
    by_strategy = {}
    for run in ordered:
        metrics = run.get("metrics")
        if run.get("strategy") == "compare_all" or not isinstance(metrics, dict):
            continue
        name = metrics.get("strategy")
        if name:
            by_strategy.setdefault(name, []).append(metrics)
    if by_strategy:
        averaged = []
        for name, metrics_list in by_strategy.items():
            avg = _avg_metrics(metrics_list)
            if isinstance(avg, dict):
                avg["strategy"] = name
                averaged.append(avg)
        if averaged:
            ranked = weighted_rank(averaged, weights)
            if ranked:
                return ranked[0].get("strategy"), ranked, "历史单策略运行平均"
    return None, [], ""


def render_algo_push_section(role):
    """在「新算法接入」页内渲染推送到车主端区块。"""
    if not role.get("can_push_algo"):
        st.info("🚀 推送到车主端：仅管理员或已开启「推送到车主端」权限的自定义角色可操作。")
        return

    st.divider()
    st.subheader("🚀 推送到车主端")
    st.caption("把研发端测试完成的算法发布为快照；车主端 FastAPI 读取最新发布记录进入实验。")
    if not OWNER_APP_CONNECTED:
        st.info("📡 当前状态：**车主端未接入** —— 推送按钮仅备用，点击只提示、不会真正推送。"
                "车主端接入后设置环境变量 `OWNER_APP_CONNECTED=1` 并重新部署即可启用。")

    registry = StrategyRegistry.all()
    label_to_name = {cls.label: name for name, cls in registry.items()}
    labels = {name: cls.label for name, cls in registry.items()}

    tab_manual, tab_auto, tab_history = st.tabs(
        ["🎯 选定算法推送", "🧠 自动推送当前最优", "📜 发布与实验"])

    # ── 手动选定算法推送 ──
    with tab_manual:
        if not label_to_name:
            st.warning("暂无可推送的算法（策略注册表为空）")
        else:
            label = st.selectbox("选择算法", list(label_to_name.keys()),
                                 key="push_algo_label")
            algo = label_to_name[label]
            params = (st.session_state.get("last_params", {}).get(algo)
                      or StrategyRegistry.default_params(algo))
            st.caption(f"将发布参数：`{json.dumps(params, ensure_ascii=False)}`")
            note = st.text_input("备注（可选）", key="push_algo_note",
                                 placeholder="如：算法三 RHO 默认参数")
            confirm = st.checkbox("我确认推送到车主端（车主端将读取该版本进入实验）",
                                  key="push_algo_confirm")
            if st.button("📤 推送到车主端", type="primary",
                         disabled=not confirm, key="push_algo_btn"):
                if not OWNER_APP_CONNECTED:
                    st.warning("🚫 车主端未接入，该按钮仅备用：当前点击不会真正推送到车主端。")
                else:
                    res = auth_publish_algorithm(st.session_state.token, algo, params,
                                                 note or None)
                    if res.get("success"):
                        st.success(f"✅ 已发布「{label}」（{algo}）到车主端")
                        st.session_state.push_algo_confirm = False
                    else:
                        st.error(res.get("error") or
                                 "发布失败：请确认已在 Supabase 执行迁移 15")

    # ── 自动推送当前测试最优 ──
    with tab_auto:
        st.caption("自动从历史运行记录中选出当前测试最优的算法（优先最近一次「全部对比」）。")
        if st.button("🚀 自动推送当前测试最优", type="primary",
                     key="auto_push_btn"):
            runs = auth_list_sim_runs(st.session_state.token,
                                      all_users=True, limit=100)
            best, ranked, source = _best_algo_from_runs(runs, RANK_DEFAULT_WEIGHTS)
            if not best:
                st.warning("暂无可用的测试记录：请先运行一次「全部对比」或单策略仿真。")
            else:
                st.session_state.auto_push_best = best
                st.session_state.auto_push_ranked = ranked
                st.session_state.auto_push_source = source

        best = st.session_state.get("auto_push_best")
        if best:
            ranked = st.session_state.get("auto_push_ranked") or []
            source = st.session_state.get("auto_push_source") or ""
            st.success(f"🧠 当前测试最优：**{labels.get(best, best)}**（来源：{source}）")
            if ranked:
                df = pd.DataFrame(ranked)
                show_cols = [c for c in ["rank", "strategy", "weighted_score",
                                         "satisfaction_rate", "spatial_utilization",
                                         "avg_wait_time_s", "shift_count",
                                         "shift_distance_m", "runtime_s"]
                             if c in df.columns]
                st.dataframe(df[show_cols])
            params = (st.session_state.get("last_params", {}).get(best)
                      or StrategyRegistry.default_params(best))
            confirm2 = st.checkbox("我确认推送该最优算法", key="auto_push_confirm")
            if st.button("📤 确认推送", type="primary",
                         disabled=not confirm2, key="auto_push_ok"):
                if not OWNER_APP_CONNECTED:
                    st.warning("🚫 车主端未接入，该按钮仅备用：当前点击不会真正推送到车主端。")
                else:
                    res = auth_publish_algorithm(st.session_state.token, best, params,
                                                 f"自动推送：{source}")
                    if res.get("success"):
                        st.success(f"✅ 已发布「{labels.get(best, best)}」（{best}）到车主端")
                        st.session_state.auto_push_confirm = False
                    else:
                        st.error(res.get("error") or
                                 "发布失败：请确认已在 Supabase 执行迁移 15")

    # ── 发布与实验记录 ──
    with tab_history:
        releases = auth_list_algorithm_releases(st.session_state.token, limit=50)
        if releases:
            st.caption(f"📤 最近发布（{len(releases)} 条，最新在前）")
            for r in releases[:10]:
                p = r.get("params") or {}
                st.markdown(
                    f"- `{r.get('algo_name')}` @ {str(r.get('created_at') or '')[:19]}"
                    f" — 参数 {json.dumps(p, ensure_ascii=False)[:80]}"
                    f"（by {r.get('created_by')}）")
        else:
            st.caption("暂无发布记录")

        st.divider()
        experiments = auth_list_experiments(st.session_state.token, limit=20)
        if experiments:
            st.caption("🧪 当前实验（车主端读取）")
            for e in experiments[:5]:
                st.markdown(f"- `{e.get('name')}`：{e.get('algo_default')}"
                            f" → {e.get('algo_new')}"
                            f"（流量 {e.get('traffic_pct')}%，状态 {e.get('status')}）")
        else:
            st.caption("暂无实验记录（车主端 FastAPI 接入后写入）")
