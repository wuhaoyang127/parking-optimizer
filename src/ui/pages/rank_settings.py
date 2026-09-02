"""仿真设置页：算法排名设置 + 计算位置切换。"""
from ui.common import *


def _render_rank_settings(disabled):
    """算法排名设置（加权评分 / 字典序优先级）。"""
    st.markdown("#### 🏆 算法排名设置")
    if "rank_mode" not in st.session_state:
        st.session_state.rank_mode = "加权评分"
    rank_mode = st.radio("排序模式", ["加权评分", "字典序优先级"],
                         horizontal=True, key="rank_mode", disabled=disabled)

    if rank_mode == "加权评分":
        st.caption("指标权重（总和应为 100，将自动归一化；指标先 min-max 归一化再加权求和）")
        weights_by_label = {}
        default_weights = st.session_state.get("rank_weights", DEFAULT_WEIGHTS_BY_LABEL)
        wcols = st.columns(4)
        for i, name in enumerate(list(PRIORITY_METRICS.keys())):
            with wcols[i % 4]:
                weights_by_label[name] = st.number_input(
                    name, 0, 100, int(default_weights.get(name, 10)), step=5,
                    key=f"rank_weight_{name}", disabled=disabled,
                    help=f"{PRIORITY_METRICS[name][2]}（"
                         f"{'越大越好' if PRIORITY_METRICS[name][1] == 'max' else '越小越好'}）")
        total_w = sum(weights_by_label.values())
        if total_w != 100:
            st.warning(f"⚠️ 权重总和为 {total_w}（应为 100），计算排名时将按比例归一化")
        else:
            st.caption("权重总和 = 100 ✅")
        st.session_state.rank_weights = weights_by_label
    else:
        st.caption("勾选顺序即优先级（从上到下 = 从高到低）；取消勾选后按新顺序重新勾选即可调整")
        priority_order = st.multiselect(
            "评估指标排序",
            options=list(PRIORITY_METRICS.keys()),
            default=st.session_state.get("priority_order", DEFAULT_PRIORITY),
            key="priority_order_sel",
            format_func=lambda n: f"{n} {'↑越大越好' if PRIORITY_METRICS[n][1]=='max' else '↓越小越好'}",
            disabled=disabled,
        )
        if not priority_order:
            priority_order = DEFAULT_PRIORITY
            st.warning("至少保留一个指标，已恢复默认顺序")
        st.session_state.priority_order = priority_order

        # 优先级变化时保存到 Supabase（登录用户，跨会话持久）
        if st.session_state.get("priority_order_saved") != priority_order:
            token = st.session_state.get("token")
            if token:
                try:
                    auth_set_pref(token, "algorithm_priority", json.dumps(priority_order))
                    st.session_state.priority_order_saved = priority_order
                except Exception:
                    pass
    return rank_mode


def _render_compute_mode(role=None):
    """计算位置：云端 CPU / 本机 worker（云 UI + 本地算力）。返回 compute_mode。

    role 传入时，无 can_local_compute 权限则隐藏本地选项（访客只能云端）。
    """
    compute_mode = st.session_state.get("compute_mode", "cloud")
    mode_options = ["☁️ 云端计算", "💻 本地计算（本机 CPU）"]
    allow_local = True if role is None else bool(role.get("can_local_compute"))
    if not allow_local:
        mode_options = mode_options[:1]
        st.caption("当前角色仅可使用云端计算")
    mode_sel = st.radio("计算位置", mode_options, horizontal=True,
                        index=0 if (compute_mode != "local" or not allow_local) else 1,
                        key="compute_mode_sel",
                        help="本地计算：云端界面 + 本机 worker 计算，大参数不再受云端内存限制")
    new_mode = "local" if mode_sel == mode_options[1] else "cloud"
    if new_mode != compute_mode:
        persist_compute_mode(new_mode)
        st.rerun()
    compute_mode = new_mode
    st.session_state.compute_mode = compute_mode
    return compute_mode
