"""页面：历史运行记录（sim_runs 持久化，跨会话/跨用户可查）。"""
from ui.common import *
from ui.pages.history_helpers import (_fmt_run_time, _run_summary, _num, _fmt_metric,
                                      _compare_radar, COMPARE_FIELDS)


def render_history_page(role):
    """页面: 历史运行记录（sim_runs 持久化，跨会话/跨用户可查）"""
    st.subheader("📜 历史运行")
    is_admin = bool(role.get("can_manage_users"))
    can_export = bool(role.get("can_export_results"))
    can_delete = bool(role.get("can_delete_history"))
    token = st.session_state.get("token")
    if not token:
        st.info("未登录")
        return

    st.caption("运行仿真后自动保存；管理员可查看全部用户记录，普通用户仅查看自己的。")
    runs = auth_list_sim_runs(token, all_users=is_admin)
    if not runs:
        st.info("暂无运行记录。请在「仿真设置」运行一次仿真，记录会自动保存到这里。")
        return

    rows = []
    for r in runs:
        rep, note = _run_summary(r.get("metrics"))
        rows.append({
            "id": r.get("id"),
            "时间": _fmt_run_time(r.get("created_at")),
            "用户": r.get("username", ""),
            "策略": STRATEGY_LABELS.get(r.get("strategy"), r.get("strategy")),
            "布局": r.get("layout_key") or "",
            "需求": "导入序列" if r.get("demand_source") == "imported" else "自动生成",
            "满足率": rep.get("satisfaction_rate"),
            "利用率": rep.get("spatial_utilization"),
            "移位次数": rep.get("shift_count"),
            "平均等待(s)": rep.get("avg_wait_time_s"),
            "说明": note,
        })

    df = pd.DataFrame(rows)
    strategies = sorted({x for x in df["策略"] if x})
    if strategies:
        sel_strategy = st.selectbox("按策略筛选", ["全部"] + strategies)
        if sel_strategy != "全部":
            df = df[df["策略"] == sel_strategy]

    show_cols = ["时间", "策略", "布局", "需求", "满足率", "利用率", "移位次数",
                 "平均等待(s)", "说明"]
    if is_admin:
        show_cols = ["时间", "用户"] + show_cols[1:]

    st.dataframe(
        df[show_cols].style.format({
            "满足率": "{:.1%}", "利用率": "{:.1%}",
            "平均等待(s)": "{:.1f}", "移位次数": "{:.0f}",
        }, na_rep="—"),
        use_container_width=True, hide_index=True,
    )

    if can_export:
        st.download_button(
            "📥 下载历史运行 CSV",
            df.to_csv(index=False).encode("utf-8-sig"),
            "parking_sim_runs.csv", "text/csv",
        )

    # 运行标签（对比 / 删除共用）
    labels = [f"{_fmt_run_time(r.get('created_at'))} · {r.get('username','')} · "
              f"{STRATEGY_LABELS.get(r.get('strategy'), r.get('strategy'))}"
              for r in runs]

    # ── 两次运行对比 ──
    st.markdown("---")
    st.markdown("### ⚖️ 两次运行对比")
    if len(runs) < 2:
        st.caption("至少需要两条运行记录才能对比（再跑一次仿真即可）。")
    else:
        ca, cb = st.columns(2)
        with ca:
            sel_a = st.selectbox("运行 A", labels, key="hist_cmp_a")
        with cb:
            sel_b = st.selectbox("运行 B", labels, key="hist_cmp_b",
                                 index=min(1, len(labels) - 1))
        if sel_a == sel_b:
            st.warning("请选择两条不同的运行记录")
        else:
            run_a = runs[labels.index(sel_a)]
            run_b = runs[labels.index(sel_b)]
            rep_a, note_a = _run_summary(run_a.get("metrics"))
            rep_b, note_b = _run_summary(run_b.get("metrics"))
            if not rep_a or not rep_b:
                st.info("所选记录没有可对比的指标数据。")
            else:
                for tag, note in (("运行 A", note_a), ("运行 B", note_b)):
                    if note:
                        st.caption(f"{tag}：{note}")
                cmp_rows = []
                for label, field, direction in COMPARE_FIELDS:
                    a = _num(rep_a.get(field))
                    b = _num(rep_b.get(field))
                    if a is None and b is None:
                        continue
                    a_val = a if a is not None else 0
                    b_val = b if b is not None else 0
                    if direction == "max":
                        better = ("B 更优" if b_val > a_val
                                  else "A 更优" if a_val > b_val else "持平")
                    else:
                        better = ("B 更优" if b_val < a_val
                                  else "A 更优" if a_val < b_val else "持平")
                    cmp_rows.append({
                        "指标": label,
                        "运行 A": _fmt_metric(label, a),
                        "运行 B": _fmt_metric(label, b),
                        "更优": better,
                    })
                st.dataframe(pd.DataFrame(cmp_rows), use_container_width=True, hide_index=True)
                st.plotly_chart(_compare_radar(rep_a, rep_b), use_container_width=True)

    # 删除（有权删除者）
    with st.expander("🗑 删除运行记录"):
        if not can_delete:
            st.info("当前角色无权删除历史运行记录")
        else:
            sel = st.selectbox("选择要删除的记录", labels, key="hist_del_sel")
            if st.button("确认删除", key="hist_del_btn"):
                idx = labels.index(sel)
                res = auth_delete_sim_run(token, runs[idx].get("id"))
                if isinstance(res, dict) and res.get("success"):
                    st.success("已删除")
                else:
                    st.error((res or {}).get("error", "删除失败"))
                st.rerun()
