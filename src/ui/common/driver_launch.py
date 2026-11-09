"""研究端「打开车主端」一键启动服务并跳转（本机）或纯跳转（云端）。"""
import streamlit as st
import streamlit.components.v1 as components

from driver_bridge.launch import _integration_root, ensure_driver_running
from driver_bridge.settings import setting


def render_open_driver_button():
    """渲染「打开车主端」按钮。

    本机（能找到 parking-integrated）：启动服务 + 跳转；
    云端（Streamlit Cloud，找不到 parking-integrated）：只跳转。
    """
    web_url = setting("PARKING_DRIVER_WEB_URL")
    if not web_url:
        return
    try:
        _integration_root()
    except RuntimeError:
        st.link_button("🚗 打开车主端", web_url)
        return
    if st.button("🚗 打开车主端（启动并跳转）", type="primary"):
        try:
            st.session_state.driver_redirect = ensure_driver_running()
        except Exception as exc:
            st.error(str(exc))
    if st.session_state.get("driver_redirect"):
        url = st.session_state.pop("driver_redirect")
        components.html(f"<script>window.location.href='{url}';</script>", height=0)


def render_download_package_button():
    """渲染「下载本地部署包」按钮（指向配置的 zip URL，供其他电脑一键部署）。"""
    url = setting("PARKING_PACKAGE_URL")
    if not url:
        return
    st.link_button("📦 下载本地部署包（其他电脑用）", url)
