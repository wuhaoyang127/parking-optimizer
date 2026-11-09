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
        st.link_button("🚗 打开车主端", web_url, type="primary")
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
    st.link_button("📦 下载本地部署包（其他电脑用）", url, type="primary")


def render_download_public_script_button():
    """渲染「下载公网启动脚本」按钮（指向配置的 start-public.ps1 URL）。"""
    url = setting("PARKING_PUBLIC_SCRIPT_URL")
    if not url:
        return
    st.link_button("🌐 下载公网启动脚本（start-public.ps1）", url, type="primary")


def render_open_console_button():
    """渲染「打开推送控制台」按钮（指向独立控制台，默认本机 8501）。"""
    url = setting("PARKING_DRIVER_CONSOLE_URL", "http://127.0.0.1:8501")
    st.link_button("🖥️ 打开推送控制台", url, type="primary")


def render_driver_connect_panel():
    """侧边栏「车主端连接」折叠面板：按钮 + 使用说明，收纳顶部控件保持简洁。"""
    with st.expander("🚗 车主端连接", expanded=False):
        render_open_driver_button()
        render_open_console_button()
        render_download_package_button()
        render_download_public_script_button()
        st.markdown(
            '<div style="color:#ffffff !important;line-height:1.9;">'
            '<strong style="color:#ffffff !important;">使用说明</strong><br>'
            '· <strong style="color:#ffffff !important;">打开车主端</strong>：'
            '本机自动启动车主端并跳转；云端环境则直接跳转。<br>'
            '· <strong style="color:#ffffff !important;">下载本地部署包</strong>：'
            '下载 zip，其他电脑解压后双击 '
            '<code style="color:#22d3ee !important;background:rgba(34,211,238,.18);'
            'padding:2px 7px;border-radius:4px;">START-HERE.cmd</code>，'
            '自动安装依赖并启动全套系统（已内置 Python 与 Node.js，无需额外安装）。'
            "</div>",
            unsafe_allow_html=True,
        )
