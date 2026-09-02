"""页面2：系统设置（用户管理 / 数据备份 / 导入布局）。"""
from ui.common import *
from ui.pages.import_users import _render_import_users
from ui.pages.import_layout import _load_layout_doc, _render_import_layout


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
                new_role = c2.selectbox("角色", ["viewer", "operator"],
                    index=0 if ur == "viewer" else 1, key=f"role_{u}", label_visibility="collapsed")
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
