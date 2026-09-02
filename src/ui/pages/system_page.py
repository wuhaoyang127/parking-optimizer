"""页面2：系统设置（用户管理 / 数据备份 / 导入布局）。"""
from ui.common import *
from ui.pages.import_users import _render_import_users
from ui.pages.import_layout import _load_layout_doc, _render_import_layout

_ROLE_OPTIONS = ["viewer", "operator", "custom"]


def _role_index(ur: str) -> int:
    return _ROLE_OPTIONS.index(ur) if ur in _ROLE_OPTIONS else 0


def _render_custom_role_editor():
    """自定义角色模板：管理员勾选该角色的板块 + 功能权限，保存后同步给所有 custom 用户。"""
    st.markdown("#### 🧩 自定义角色权限")
    st.caption("勾选「自定义」角色能看到的板块和可执行的功能；保存后同步给所有「自定义」角色用户。")
    saved = auth_get_custom_sections(st.session_state.token)
    # 兼容旧版返回（list = 仅板块数组 / 其他异常类型按默认处理）
    if isinstance(saved, dict):
        cur_sections = saved.get("sections") or DEFAULT_CUSTOM_SECTIONS
        cur_features = saved.get("features") or ROLES["custom"]
    elif isinstance(saved, list):
        cur_sections = saved or DEFAULT_CUSTOM_SECTIONS
        cur_features = ROLES["custom"]
    else:
        cur_sections = DEFAULT_CUSTOM_SECTIONS
        cur_features = ROLES["custom"]
    if not isinstance(cur_features, dict):
        cur_features = ROLES["custom"]

    tab_sections, tab_features = st.tabs(["📑 板块可见性", "🔘 功能权限"])
    with tab_sections:
        c_all, c_none = st.columns(2)
        with c_all:
            if st.button("板块全选", key="custom_all", use_container_width=True):
                st.session_state.custom_sections = list(SECTION_KEYS); st.rerun()
        with c_none:
            if st.button("板块全不选", key="custom_none", use_container_width=True):
                st.session_state.custom_sections = ["feedback"]; st.rerun()
        if "custom_sections" not in st.session_state:
            st.session_state.custom_sections = list(cur_sections)
        chosen_sections = []
        for key in SECTION_KEYS:
            if st.checkbox(SECTION_LABELS[key], value=key in st.session_state.custom_sections,
                           key=f"perm_sec_{key}"):
                chosen_sections.append(key)
        st.session_state.custom_sections = chosen_sections

    with tab_features:
        if "custom_features" not in st.session_state:
            st.session_state.custom_features = {k: bool(cur_features.get(k)) for k in FEATURE_KEYS}
        chosen_features = {}
        for key in FEATURE_KEYS:
            label, help_text = FEATURE_LABELS[key]
            chosen_features[key] = st.checkbox(
                label, value=st.session_state.custom_features.get(key, False),
                key=f"perm_feat_{key}", help=help_text)
        st.session_state.custom_features = chosen_features

    if st.button("💾 保存自定义角色权限", type="primary", use_container_width=True):
        if not chosen_sections:
            st.error("至少勾选一个板块（建议至少保留「仿真设置」）")
        else:
            res = auth_save_custom_sections(st.session_state.token,
                                            chosen_sections, chosen_features)
            if res.get("success"):
                st.success("已保存，并同步到所有「自定义」角色用户")
            else:
                st.error(res.get("error", "保存失败：请确认已在 Supabase 执行迁移 13"))


def render_system(role):
    """页面2: 系统设置（用户管理 / 数据备份 / 导入布局）"""
    st.subheader("🔧 系统设置")
    tab1, tab2, tab3 = st.tabs(["👥 用户管理", "💾 数据备份", "📐 导入布局"])

    # ── 用户管理 ──
    with tab1:
        if not role["can_manage_users"]:
            st.info("仅管理员可管理用户")
        else:
            users = auth_list_users(st.session_state.token)
            if len(users) <= 1: st.caption("暂无其他注册用户")
            for u_info in users:
                u = u_info.get("username", "")
                ur = u_info.get("role", "viewer")
                if u == ADMIN_USER: continue
                c1, c2, c3, c4 = st.columns([2, 2, 1.5, 1.5])
                c1.write(f"**{u}**")
                new_role = c2.selectbox("角色", _ROLE_OPTIONS,
                    index=_role_index(ur), key=f"role_{u}", label_visibility="collapsed")
                if new_role != ur: auth_update_role(st.session_state.token, u, new_role); st.rerun()
                if c3.button("🔑", key=f"rst_{u}", help="重置密码"):
                    st.session_state[f"rst_open_{u}"] = True
                if c4.button("🗑", key=f"del_{u}"):
                    auth_delete_user(st.session_state.token, u); st.rerun()
                if st.session_state.get(f"rst_open_{u}"):
                    rp = st.text_input("新密码", type="password", key=f"rst_pw_{u}")
                    if st.button("确认重置", key=f"rst_ok_{u}"):
                        if rp:
                            auth_reset_pw(st.session_state.token, u, rp)
                            st.session_state[f"rst_open_{u}"] = False; st.success(f"{u} 密码已重置！"); st.rerun()
            st.divider()
            st.caption(f"👑 **{ADMIN_USER}** — 管理员（不可删除/不可降级）")
            with st.expander("🧩 自定义角色权限（板块级）", expanded=False):
                _render_custom_role_editor()

    # ── 数据备份 ──
    with tab2:
        if not role["can_manage_data"]:
            st.info("仅管理员可进行数据备份")
        else:
            c_dl, c_up = st.columns(2)
            with c_dl:
                export_data = auth_export_users(st.session_state.token)
                st.download_button("📥 导出用户数据",
                    json.dumps(export_data, indent=2, ensure_ascii=False),
                    "users_backup.json", "application/json", use_container_width=True)
            with c_up:
                _render_import_users()

    # ── 导入布局 ──
    with tab3:
        if not role["can_configure"]:
            st.info("仅管理员/操作员可查看布局导入说明")
        else:
            with st.expander("📖 布局导入格式说明", expanded=False):
                st.markdown(_load_layout_doc())
                st.download_button("📥 下载示例布局 JSON",
                                   json.dumps(EXAMPLE_LAYOUT, indent=2, ensure_ascii=False),
                                   "example_layout.json", "application/json")
            if not role["can_manage_data"]:
                st.info("📤 上传布局仅管理员可操作")
            else:
                _render_import_layout()
