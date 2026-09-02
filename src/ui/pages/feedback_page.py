"""页面：用户反馈（意见箱 + 管理员全部反馈）。"""
from ui.common import *
from ui.pages.feedback_helpers import _render_my_feedbacks
from ui.pages.feedback_admin import _render_admin_feedbacks


def render_feedback_page(role):
    """页面: 用户反馈 —— 意见箱 + 仿真结果反馈"""
    st.subheader("💬 反馈")
    is_admin = role.get("can_manage_users", False)

    if "feedback_sort_order" not in st.session_state:
        st.session_state.feedback_sort_order = "正序（早→晚）"
    st.radio("反馈排序", ["正序（早→晚）", "倒序（晚→早）"],
             horizontal=True, key="feedback_sort_order",
             help="按反馈显示时间排序（未修改过的用原始提交时间）")
    sort_desc = st.session_state.feedback_sort_order.startswith("倒序")

    with st.expander("📝 提交反馈", expanded=True):
        _render_submit_feedback()

    with st.expander("📋 我的反馈", expanded=False):
        _render_my_feedbacks(reverse=sort_desc)

    if is_admin:
        st.divider()
        st.markdown("### 🗂 全部反馈（管理员）")
        _render_admin_feedbacks(reverse=sort_desc)


def _render_submit_feedback():
    """提交反馈表单（所有登录用户）"""
    category = st.radio("反馈类型", ["general", "simulation"],
                        format_func=lambda x: "通用意见" if x == "general" else "仿真结果反馈",
                        horizontal=True)
    title = st.text_input("标题", placeholder="一句话概括你的反馈")
    content = st.text_area("内容", placeholder="详细描述你的意见 / 问题 / 建议...")

    related_run = None
    if category == "simulation":
        if st.session_state.get("sim_has_run"):
            sn = st.session_state.get("sim_strategy_name", "")
            strat_params = st.session_state.get("sim_strategy_params", {})
            env_params = st.session_state.get("sim_env_params", {})
            st.caption(f"将关联最近一次仿真：策略「{STRATEGY_LABELS.get(sn, sn)}」")
            related_run = json.dumps({"strategy": sn, "params": strat_params, "env": env_params},
                                     ensure_ascii=False)
        else:
            st.info("当前尚未运行仿真，反馈将以通用形式提交")
            category = "general"

    if st.session_state.get("fb_submitted"):
        st.success("✅ 反馈已提交！")
        st.session_state.fb_submitted = False

    if st.button("提交反馈", type="primary"):
        if not title.strip() or not content.strip():
            st.error("请填写标题和内容")
        else:
            res = auth_submit_feedback(st.session_state.token, category, title.strip(),
                                       content.strip(), related_run)
            if res.get("success"):
                st.session_state.fb_submitted = True
                st.rerun()
            else:
                st.error(res.get("error", "提交失败"))
