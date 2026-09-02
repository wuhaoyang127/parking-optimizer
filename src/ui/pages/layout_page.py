"""页面3：停车场布局图（内置/真实布局分别回显最近一次仿真）。"""
from ui.common import *


def render_layout_page():
    """页面3: 停车场布局图 — 内置布局/真实布局分别回显最近一次仿真的布局"""
    ensure_custom_layouts_loaded()
    st.subheader("🅿️ 停车场布局图")
    if not st.session_state.get("sim_has_run"):
        st.info("👈 请先在 **仿真设置** 中运行仿真")
        return

    builtin_sim = st.session_state.get("last_builtin_sim")
    real_sim = st.session_state.get("last_real_sim")
    options = []
    if builtin_sim:
        options.append("内置布局")
    if real_sim:
        options.append("真实布局")
    if not options:
        st.info("暂无已仿真的布局（请先在仿真设置中运行）")
        return

    if "layout_view_mode" not in st.session_state or st.session_state.layout_view_mode not in options:
        st.session_state.layout_view_mode = (
            "真实布局"
            if st.session_state.get("sim_layout_category") == "real" and real_sim
            else "内置布局")
    mode = st.radio(
        "视图模式", options, horizontal=True, key="layout_view_mode",
        help="内置布局回显最近一次仿真的内置示意布局；真实布局回显最近一次仿真的导入布局")

    if mode == "真实布局":
        sim_info = real_sim
        st.caption(f"真实布局：{LAYOUTS.get(sim_info['layout'], sim_info['layout'])}"
                   f"（最近一次仿真的导入布局）")
    else:
        sim_info = builtin_sim
        st.caption(f"内置布局：{LAYOUTS.get(sim_info['layout'], sim_info['layout'])}"
                   f"（最近一次仿真的内置示意布局）")
    net = sim_info["net"]
    spots = sim_info["spots"]
    sa = sum(1 for s in spots if s.spot_type == SpotType.STANDALONE)
    ta = sum(1 for s in spots if s.spot_type == SpotType.TANDEM)
    st.caption(f"{len(spots)} 车位 — {sa} 独立 + {ta} 纵深")

    if "layout_zoom" not in st.session_state: st.session_state.layout_zoom = 1.0
    c_zoom, _ = st.columns([1, 5])
    with c_zoom:
        zoom = st.slider("🔍 缩放", 0.5, 3.0, st.session_state.layout_zoom, 0.1, key="layout_zoom_slider")
    st.session_state.layout_zoom = zoom
    adaptive = 520 / 400
    scale = adaptive * zoom

    fig = draw_parking_layout(net, spots, height=520, scale=scale)
    st.plotly_chart(fig, use_container_width=True, config={"scrollZoom": True})
