"""系统设置页：导入用户数据（三态：上传→预览→完成）。"""
from ui.common import *


def _render_import_users():
    """导入用户数据（三态）"""
    if "import_usr_state" not in st.session_state:
        st.session_state.import_usr_state = "idle"; st.session_state.import_usr_data = None
        st.session_state.import_usr_result = None

    state = st.session_state.import_usr_state
    if state == "idle":
        uploaded = st.file_uploader("📤 导入用户数据", type=["json"], key="restore_users",
                                     label_visibility="collapsed")
        if uploaded is not None:
            try:
                raw = json.loads(uploaded.read().decode("utf-8"))
                if isinstance(raw, dict):
                    normalized = []
                    for uname, info in raw.items():
                        normalized.append({
                            "username": uname,
                            "password_hash": info.get("password_hash", info.get("password", "")),
                            "role": info.get("role", "viewer")
                        })
                elif isinstance(raw, list):
                    normalized = raw
                else:
                    st.error("不支持的数据格式"); st.stop()
                if not normalized: st.error("无用户数据"); st.stop()
                st.session_state.import_usr_data = normalized
                st.session_state.import_usr_state = "preview"
                st.rerun()
            except json.JSONDecodeError: st.error("不是有效的 JSON 文件")
            except Exception as e: st.error(f"解析失败: {e}")

    elif state == "preview":
        data = st.session_state.import_usr_data
        st.info(f"📋 检测到 **{len(data)}** 个用户")
        df_preview = pd.DataFrame(data)
        show_cols = [c for c in ["username", "role"] if c in df_preview.columns]
        st.dataframe(df_preview[show_cols], use_container_width=True, hide_index=True)
        c1, c2 = st.columns(2)
        if c1.button("✅ 确认导入", use_container_width=True, type="primary"):
            res = auth_import_users(st.session_state.token, data)
            st.session_state.import_usr_result = res
            st.session_state.import_usr_state = "done"
            st.rerun()
        if c2.button("❌ 取消", use_container_width=True):
            st.session_state.import_usr_state = "idle"; st.rerun()

    elif state == "done":
        res = st.session_state.import_usr_result
        if res and res.get("success"):
            st.success(f"✅ 成功导入 {res.get('count', 0)} 个用户")
        else:
            st.error(f"导入失败: {res.get('error', '未知错误') if res else '无响应'}")
        if st.button("完成", use_container_width=True):
            st.session_state.import_usr_state = "idle"; st.rerun()
