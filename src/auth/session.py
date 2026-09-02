"""auth 包：session token 的 Cookie/URL 持久化与恢复。"""
import json
from typing import Optional

import streamlit as st

from auth.users import validate_session


def _cookie_token() -> Optional[str]:
    """从浏览器 Cookie 读取 token（Streamlit 的只读 Cookie API）。"""
    try:
        tok = st.context.cookies.get("token")
        return tok or None
    except Exception:
        return None


def _set_cookie_js(token: str) -> None:
    """通过同源 iframe 的 JS 写入 Cookie（Streamlit 暂无 Python 写 Cookie API）。"""
    try:
        import streamlit.components.v1 as components
        safe = json.dumps(token)
        components.html(
            "<script>try{document.cookie='token='+encodeURIComponent(" + safe +
            ")+';path=/;max-age=604800;SameSite=Lax';}catch(e){}</script>",
            height=0,
        )
    except Exception:
        pass


def _clear_cookie_js() -> None:
    """通过 JS 清除 Cookie。"""
    try:
        import streamlit.components.v1 as components
        components.html(
            "<script>try{document.cookie='token=;path=/;max-age=0';}catch(e){}</script>",
            height=0,
        )
    except Exception:
        pass


def set_session_token(token: str):
    """写入 session token：Cookie 为主；URL query param 仅作瞬时兜底。

    下次页面加载若 Cookie 生效，restore_session() 会自动清掉 URL 中的 token。
    """
    _set_cookie_js(token)
    try:
        st.query_params["token"] = token
    except Exception:
        pass


def get_session_token() -> Optional[str]:
    """优先从 Cookie 读取 token，回退到 URL query param（兼容旧链接）。"""
    return _cookie_token() or st.query_params.get("token")


def clear_session_token():
    """清除 Cookie 与 URL 中的 token。"""
    _clear_cookie_js()
    try:
        if "token" in st.query_params:
            del st.query_params["token"]
    except Exception:
        pass


def restore_session() -> Optional[dict]:
    """页面加载时尝试恢复登录态，返回 {username, role, token} 或 None"""
    token = get_session_token()
    if not token:
        return None
    res = validate_session(token)
    if res.get("success"):
        # Cookie 生效后，清理 URL 中的兜底 token（token 不再长期暴露在 URL）
        if _cookie_token():
            try:
                if "token" in st.query_params:
                    del st.query_params["token"]
            except Exception:
                pass
        return {"username": res["username"], "role": res["role"], "token": token}
    else:
        clear_session_token()
        return None
