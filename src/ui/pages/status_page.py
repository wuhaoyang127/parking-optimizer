"""页面：系统状态与预警（Supabase 探测 + 前端兼容性检测）。"""
from ui.common import *
from ui.pages.metric_card import _metric


def _detect_ui_compat():
    """检测前端 UI 依赖的 use_container_width 是否仍被 Streamlit 支持。

    项目有 27 处控件使用 use_container_width，Streamlit 已将其标记废弃（计划移除）。
    一旦被移除，这些控件会抛 TypeError 导致页面崩溃，此处运行时探测以提前预警。
    """
    import inspect
    import streamlit as _st
    try:
        if "use_container_width" in inspect.signature(_st.button).parameters:
            return {"removed": False,
                    "detail": f"use_container_width 可用（Streamlit {_st.__version__}，已标记废弃但尚未移除）"}
        return {"removed": True,
                "detail": f"use_container_width 已被 Streamlit {_st.__version__} 移除，界面控件将报错，需立即升级代码"}
    except Exception as e:
        return {"removed": None, "detail": f"无法检测（{e}）"}


def render_status_page(role):
    """页面: 系统状态与预警 —— 主动探测 Supabase 后端可用性"""
    st.subheader("🚨 系统状态与预警")
    if not role["can_debug"]:
        st.info("仅管理员和操作员可查看系统状态")
        return
    st.caption("主动探测 Supabase 后端是否在线、API key 是否有效")

    if "health_check" not in st.session_state:
        st.session_state.health_check = None

    if st.button("🔄 立即重新探测"):
        st.session_state.health_check = None
        st.rerun()

    if st.session_state.health_check is None:
        with st.spinner("探测中..."):
            st.session_state.health_check = check_supabase_health()

    h = st.session_state.health_check
    status = h.get("status", "error")
    if status == "ok":
        st.success(f"✅ {h.get('message')}")
    elif status == "warn":
        st.warning(f"⚠️ {h.get('message')}")
    else:
        st.error(f"🚫 {h.get('message')}")

    c1, c2, c3 = st.columns(3)
    with c1:
        _metric("后端在线", "✅ 是" if h.get("online") else "❌ 否",
                "good" if h.get("online") else "bad")
    with c2:
        _metric("API key 有效", "✅ 是" if h.get("api_key_valid") else "❌ 否",
                "good" if h.get("api_key_valid") else "bad")
    with c3:
        lat = h.get("latency_ms")
        _metric("响应耗时", f"{lat}ms" if lat is not None else "—")

    st.caption(f"探测时间：{h.get('checked_at')}")

    # ── 前端 UI 兼容性检测（use_container_width 废弃预警）──
    st.markdown("---")
    ui = _detect_ui_compat()
    if ui["removed"]:
        st.error(f"🚫 **前端兼容性风险**：{ui['detail']}")
    elif ui["removed"] is None:
        st.warning(f"⚠️ **前端兼容性未知**：{ui['detail']}")
    else:
        st.caption(f"✅ **前端 UI 兼容性**：{ui['detail']}")

    st.markdown("""
**说明**
- 本页主动探测 `auth.py` 中配置的 Supabase 后端（URL 与 anon key）是否可用。
- 后端在线但 API key 失效 → key 已过期或权限变更，需到 Supabase 控制台检查。
- 无法连接 → 项目可能已暂停（免费项目 7 天无活动会自动暂停）或已过期。
""")
