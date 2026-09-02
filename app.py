"""智能停车场优化系统 — 多页面导航版（瘦入口，页面逻辑在 src/ui/）"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

import streamlit as st

from ui.common import *  # 常量 + 工具 + check_login + auth 封装
from ui.pages import (
    render_settings, render_system, render_layout_page, render_path_page,
    render_metrics_page, render_algo_import_page, render_status_page, render_feedback_page,
    render_history_page,
)

st.set_page_config(page_title="智能停车场优化", page_icon="🚗", layout="wide")
st.markdown(GLOBAL_CSS, unsafe_allow_html=True)
check_login()
role = resolve_role(st.session_state.role, st.session_state.get("permissions"))

# ── 页面注册表（key 顺序即导航顺序；板块权限控制导航可见性）──
PAGE_RENDERERS = {
    "settings": render_settings,
    "system": render_system,
    "layout": render_layout_page,
    "path": render_path_page,
    "metrics": render_metrics_page,
    "history": render_history_page,
    "algo_import": render_algo_import_page,
    "status": render_status_page,
    "feedback": render_feedback_page,
}
allowed = [k for k in SECTION_KEYS if k in role.get("sections", [])]
pages = [SECTION_LABELS[k] for k in allowed]

# ── Sidebar ──
with st.sidebar:
    st.markdown(f'<div style="display:flex;align-items:center;gap:8px;padding:0.3rem 0 0.8rem 0;">'
        f'<div style="width:32px;height:32px;border-radius:50%;background:rgba(255,255,255,0.2);'
        f'display:flex;align-items:center;justify-content:center;font-size:1rem">🚗</div>'
        f'<div><div style="font-weight:700;font-size:0.9rem;color:white;">{st.session_state.username}</div>'
        f'<div style="font-size:0.7rem;color:rgba(255,255,255,0.7);">{role["label"]}</div></div></div>',
        unsafe_allow_html=True)

    if st.button("🚪 退出", use_container_width=True):
        auth_logout(st.session_state.token)
        clear_session_token()
        clear_custom_layouts()
        st.session_state.logged_in = False; st.session_state.token = None
        st.rerun()

    with st.expander("🔑 修改密码"):
        old_pw = st.text_input("当前密码", type="password", key="chg_old")
        new_pw = st.text_input("新密码", type="password", key="chg_new")
        new_pw2 = st.text_input("确认新密码", type="password", key="chg_new2")
        if st.button("确认修改", use_container_width=True, key="do_chg_pw"):
            if not old_pw or not new_pw: st.error("请填写完整")
            elif new_pw != new_pw2: st.error("两次密码不一致")
            else:
                res = auth_change_pw(st.session_state.token, old_pw, new_pw)
                if res.get("success"): st.success("密码已修改！")
                else: st.error(res.get("error", "修改失败"))

    st.divider()
    # ── 页面导航（只显示有权板块）──
    if "page" not in st.session_state or st.session_state.page not in pages:
        st.session_state.page = pages[0]
    selected = st.radio("导航", pages,
                        index=pages.index(st.session_state.page),
                        label_visibility="collapsed")
    if selected != st.session_state.page:
        st.session_state.page = selected
        st.rerun()

# ── 主区域（按板块 key 分发；无权板块不渲染）──
page = st.session_state.page
key = next((k for k, label in SECTION_LABELS.items() if label == page), None)
if key is None or key not in allowed:
    st.warning("当前角色没有访问该板块的权限。")
elif key == "layout":
    render_layout_page()
elif key == "path":
    render_path_page()
else:
    PAGE_RENDERERS[key](role)
