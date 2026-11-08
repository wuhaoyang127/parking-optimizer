"""研究端「打开车主端」一键启动服务并跳转。"""
import streamlit as st
import streamlit.components.v1 as components

from driver_bridge.launch import ensure_driver_running
from driver_bridge.settings import setting


def render_open_driver_button():
    """渲染「打开车主端」按钮：点击后确保车主端服务运行并跳转。"""
    if st.button("🚗 打开车主端（启动并跳转）", type="primary"):
        try:
            st.session_state.driver_redirect = ensure_driver_running()
        except Exception as exc:
            st.error(str(exc))
    if st.session_state.get("driver_redirect"):
        url = st.session_state.pop("driver_redirect")
        components.html(f"<script>window.location.href='{url}';</script>", height=0)
