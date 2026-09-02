"""页面4：车辆动态路径（选车/三阶段/帧回放主流程）。"""
from ui.common import *
from ui.pages.path_charts import _draw_charts
from ui.pages.path_frames import _render_frame_controls
from ui.pages.path_shift_table import _build_shift_rows


def _vehicle_sort_key(v: str):
    """车辆ID排序键：带下划线时按末尾数字排序，否则按字典序；
    返回同构 (int, int, str) 元组，避免 int/str 混合比较 TypeError。"""
    if "_" in v:
        try:
            return (0, int(v.rsplit("_", 1)[-1]), v)
        except ValueError:
            pass
    return (1, 0, v)


def render_path_page():
    """页面4: 车辆动态路径 — 20帧快照回放"""
    st.subheader("🚗 车辆动态路径")
    if not st.session_state.get("sim_has_run"):
        st.info("👈 请先在 **仿真设置** 中运行仿真")
        return

    net = st.session_state.sim_net
    spots = st.session_state.sim_spots
    events = st.session_state.get("sim_events_raw") or []
    if not events:
        st.info("本次仿真没有可回放的事件日志（可能因运行超时被跳过）。"
                "请回到仿真设置重新运行仿真。")
        return
    max_time = max(e["time"] for e in events)

    if "replay_time" not in st.session_state: st.session_state.replay_time = 0.0
    if "frame_index" not in st.session_state: st.session_state.frame_index = 0
    if "frame_playing" not in st.session_state: st.session_state.frame_playing = False
    if "selected_vehicle" not in st.session_state: st.session_state.selected_vehicle = None

    all_vehs = sorted(set(
        str(e.get("vehicle_id", "")) for e in events
        if str(e.get("vehicle_id", "")) and e.get("type") in ("vehicle_arrival", "parking_assigned", "spot_entry")
    ), key=_vehicle_sort_key)

    shift_rows = _build_shift_rows(events)
    shift_vehicles = {r["移位车辆"] for r in shift_rows}

    # 按车辆序号分段（每段 20 辆），先选段再细选
    SEGMENT_SIZE = 20
    segment_labels = []
    segment_map = {}
    for i in range(0, len(all_vehs), SEGMENT_SIZE):
        chunk = all_vehs[i:i + SEGMENT_SIZE]
        label = f"{chunk[0]} ~ {chunk[-1]}"
        segment_labels.append(label)
        segment_map[label] = chunk

    if segment_labels:
        seg_sel = st.selectbox("① 选择车辆区间", segment_labels)
        filtered_vehs = segment_map[seg_sel]
    else:
        filtered_vehs = all_vehs

    with st.expander(f"🔄 移位车辆表（{len(shift_rows)} 条，演示移位动态用）", expanded=bool(shift_rows)):
        if shift_rows:
            st.dataframe(shift_rows, use_container_width=True)
            st.caption("在「② 选择车辆」中选带 🔄 标记的车辆，回放阶段选「移位」即可演示；"
                       "内层车离场时也可看到让行车的辅助虚线。")
        else:
            st.caption("本仿真没有发生移位（可提高需求强度或增加纵深车位比例后再运行）。")

    # 若已选车辆不在当前段，则重置
    if st.session_state.get("selected_vehicle") and st.session_state.selected_vehicle not in filtered_vehs:
        st.session_state.selected_vehicle = None

    st.selectbox("② 选择车辆", [""] + filtered_vehs, key="selected_vehicle",
                 format_func=lambda v: (f"🚙 {v}" if v else "— 选择车辆 —")
                                        + (" 🔄移位" if v in shift_vehicles else ""))

    hl_veh = st.session_state.selected_vehicle
    if not hl_veh:
        st.info("请选择一辆车")
        return

    veh_ev = sorted([e for e in events if str(e.get("vehicle_id","")) == hl_veh], key=lambda e: e["time"])
    pe = st.session_state.get("sim_pe")
    phases = build_vehicle_phases(net, pe, events, hl_veh) if pe else {"enter": None, "leave": None, "shifts": []}

    # 阶段选择（入库 / 离场 / 移位，只显示存在事件的阶段）
    phase_choices = []
    if phases.get("enter"): phase_choices.append(("enter", "🚗 入库"))
    if phases.get("leave"): phase_choices.append(("leave", "🚪 离场"))
    if phases.get("shifts"): phase_choices.append(("shift", "🔄 移位"))
    if not phase_choices:
        rej = [e for e in veh_ev if e.get("type") == "rejected"]
        if rej:
            reason = (rej[0].get("metadata", {}) or {}).get("reason", "停车场无空闲车位")
            st.error(f"🚫 该车辆被拒绝：{reason}")
        else:
            st.warning("该车辆尚无入库/离场/移位事件")
        return

    phase_labels = [lbl for _, lbl in phase_choices]
    if st.session_state.get("path_phase_radio") not in phase_labels:
        st.session_state.path_phase_radio = phase_labels[0]  # 防切换车辆后选项不匹配
    phase_sel = st.radio("③ 选择回放阶段", phase_labels,
                         horizontal=True, key="path_phase_radio")
    phase_key = next(k for k, lbl in phase_choices if lbl == phase_sel)

    if phase_key == "shift":
        shifts = phases["shifts"]
        if len(shifts) > 1:
            shift_labels = [f"{s['from_spot']} → {s['to_spot']}"
                            + ("（回位）" if s.get("kind") == "return" else "")
                            for s in shifts]
            shift_sel = st.selectbox("选择移位段", shift_labels, key="path_shift_sel")
            seg = shifts[shift_labels.index(shift_sel)]
        else:
            seg = shifts[0]
        t_start, t_end = seg["t_start"], seg["t_end"]
        path = seg["path"]
        spot_id = f"{seg['from_spot']} → {seg['to_spot']}"
    else:
        seg = phases[phase_key]
        t_start, t_end = seg["t_start"], seg["t_end"]
        path = seg["path"]
        spot_id = seg.get("spot_id", "")

    st.session_state.path_phase_key = phase_key
    st.session_state.path_phase_seg = seg
    st.session_state.path_phase_path = path
    st.session_state.path_phase_t_start = t_start
    st.session_state.path_phase_t_end = t_end

    N = 20
    frames = [t_start + (t_end - t_start) * i / (N - 1) for i in range(N)]

    phase_label = {"enter": "入库", "leave": "离场", "shift": "移位"}.get(phase_key, phase_key)
    st.caption(f"🅿️ 车位: **{spot_id}** | {phase_label}: {t_start:.1f}s → {t_end:.1f}s ({(t_end-t_start):.1f}s)")

    # 展示该车辆的拒绝/调整理由（因客观原因无法停最优车位、或需移位/离场）
    notes = []
    for e in veh_ev:
        et = e.get("type", "")
        meta = e.get("metadata", {}) or {}
        reason = meta.get("reason", "")
        if et == "rejected":
            notes.append(f"🚫 **拒绝**：{reason or '停车场无空闲车位'}")
        elif et == "departure" and meta.get("had_blocking"):
            notes.append(f"🔄 **离场需移位**：{reason or '被外侧车辆阻挡'}")
        elif et == "shift_start":
            notes.append(f"🔄 **被临时移位**：{reason or '为让行内层车辆离场'}")
    for n in notes:
        st.warning(n)

    _render_frame_controls(frames, t_start, t_end)
    _draw_charts(net, spots, events, max_time)

    # 自动轮播（放在图表之后，确保先渲染再切帧）
    if st.session_state.frame_playing:
        if st.session_state.frame_index < N - 1:
            time.sleep(0.4)
            st.session_state.frame_index += 1
            st.rerun()
        else:
            st.session_state.frame_playing = False
            st.rerun()
