"""Local integration console for installations without the original Supabase account."""
import secrets
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
import streamlit as st
from driver_bridge.client import call, publish
from driver_bridge.settings import setting
from ui.common.driver_launch import render_driver_connect_panel
from ui.pages.driver_release_panel import render_driver_releases

st.set_page_config(page_title="停车研究站 · 车主端连接", page_icon="🅿️", layout="wide")
st.title("研究算法 → 车主智能推荐")
st.caption("本地对接控制台 · 完整研究站仍由 app.py 启动")
password = setting("PARKING_CONSOLE_PASSWORD")
entered = st.text_input("管理员控制台口令", type="password")
if len(password) < 16 or not secrets.compare_digest(entered.encode(), password.encode()):
    st.info("输入控制台口令（配置在环境变量或 Streamlit secrets 的 PARKING_CONSOLE_PASSWORD）。")
    st.stop()
render_driver_connect_panel()
try:
    supported = call("/api/research/v1/capabilities")["supported"]
    algorithm = st.selectbox("研究算法", supported)
    params_text = st.text_area("算法参数JSON（留空使用默认值）", value="{}")
    note = st.text_input("版本备注")
    if st.button("发布版本到暂存区", type="primary"):
        import json
        params = json.loads(params_text or "{}")
        model = st.session_state.get("driver_trained_model") if algorithm == "ml_duration_tree" else None
        if algorithm == "ml_duration_tree" and not params:
            params = st.session_state.get("driver_trained_params", {})
        release = publish(algorithm, params, note, model=model,
                          seed=int(st.session_state.get("driver_release_seed", 0)))
        st.session_state.driver_pending_release = release["release_id"]
        st.success("已发布：" + release["release_id"])
    render_driver_releases()
except Exception as exc:
    st.error(str(exc))
