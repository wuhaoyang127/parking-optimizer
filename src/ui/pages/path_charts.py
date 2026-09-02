"""动态路径页：停车场图表绘制（全局/周边双窗口）。"""
from ui.common import *


def _draw_charts(net, spots, events, max_time):
    """绘制停车场图表（被静态和播放模式共用）"""
    state = replay_state(events, st.session_state.replay_time, spots, net)
    hl_path, hl_center, hl_veh = None, None, st.session_state.selected_vehicle
    hl_color, extra_paths = None, []

    if hl_veh:
        phase_key = st.session_state.get("path_phase_key", "enter")
        phase_seg = st.session_state.get("path_phase_seg")
        if phase_seg:
            hl_path = phase_seg.get("path") or None
            hl_color = {"enter": "#FFEB3B", "leave": "#FF9800", "shift": "#9C27B0"}.get(phase_key, "#FFEB3B")
            extra_paths = [{"path": h.get("path"), "color": "#9C27B0"}
                           for h in phase_seg.get("helper_shifts", []) if h.get("path")]
            # 高亮车位置：入库用事件插值；离场/移位按路径段插值
            if phase_key == "enter":
                ipos = interp_vehicle_pos(net, events, hl_veh, st.session_state.replay_time)
            else:
                ipos = interp_path_segment(net, hl_path or [],
                                           phase_seg.get("t_start", 0.0),
                                           phase_seg.get("t_end", 0.0),
                                           st.session_state.replay_time)
            hl_center = ipos
            found = False
            for dv in state["dv"]:
                if str(dv.get("vid","")) == hl_veh: dv["x"],dv["y"]=ipos[0],ipos[1]; found=True; break
            if not found:
                state["dv"].append({"vid":hl_veh,"x":ipos[0],"y":ipos[1],"st":"行驶中","target":hl_path[-1] if hl_path else "?"})

    for dv in state["dv"]:
        vid = str(dv.get("vid",""))
        if vid and vid != hl_veh:
            ipos = interp_vehicle_pos(net, events, vid, st.session_state.replay_time)
            dv["x"],dv["y"] = ipos[0],ipos[1]

    if "path_zoom" not in st.session_state: st.session_state.path_zoom = 1.0
    zoom = st.slider("🔍 图缩放", 0.5, 3.0, st.session_state.path_zoom, 0.1, key="path_zoom_slider",
                     label_visibility="collapsed")
    st.session_state.path_zoom = zoom

    if hl_veh:
        sc = (480/400)*zoom
        c1,c2 = st.columns(2)
        with c1:
            st.caption("🌍 全局视图")
            fig = draw_parking_layout(net, spots, state, highlight_vehicle=hl_veh,
                                       highlight_path=hl_path, highlight_path_color=hl_color,
                                       extra_paths=extra_paths, height=480, scale=sc)
            st.plotly_chart(fig, use_container_width=True, config={"scrollZoom": True})
        with c2:
            st.caption(f"🔍 {hl_veh} 周边")
            if hl_center:
                fig = draw_parking_layout(net, spots, state, highlight_vehicle=hl_veh,
                                           highlight_path=hl_path, highlight_path_color=hl_color,
                                           extra_paths=extra_paths,
                                           view_center=hl_center, view_radius=18, height=480, scale=sc)
                st.plotly_chart(fig, use_container_width=True, config={"scrollZoom": True})
            else:
                st.info("车辆尚未出现在画面中")
    else:
        sc = (520/400)*zoom
        st.caption("🌍 全局视图 — 选择一辆车查看双窗口回放")
        fig = draw_parking_layout(net, spots, state, height=520, scale=sc)
        st.plotly_chart(fig, use_container_width=True, config={"scrollZoom": True})
