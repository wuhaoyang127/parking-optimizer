"""车辆位置/路径段插值（动态路径动画用）。"""
from ui.common._imports import *


def interp_vehicle_pos(net, events_raw, vid, t):
    """计算车辆 vid 在时刻 t 的平滑插值位置 (x, y)"""
    veh_ev = []
    for e in events_raw:
        ev_vid = e.get("vehicle_id", "")
        # 宽松匹配：支持 int/str 混合
        if str(ev_vid) == str(vid) or ev_vid == vid:
            veh_ev.append(e)
    veh_ev.sort(key=lambda e: e["time"])

    assigned_t, spot_id, entry_t, origin_entry = None, None, None, None
    for e in veh_ev:
        et = e["type"]
        sid = e.get("spot_id", "")
        # 查找任何分配/进入事件
        if et in ("parking_assigned", "spot_entry") and assigned_t is None:
            assigned_t = e["time"]
            if sid: spot_id = sid
            origin_entry = e.get("metadata", {}).get("entry") or origin_entry
        elif et == "spot_entry" and assigned_t is not None:
            entry_t = e["time"]
            origin_entry = e.get("metadata", {}).get("entry") or origin_entry
            break
        elif et == "departure" and assigned_t is not None:
            break  # 后面不再需要

    # 如果还是没找到分配事件，尝试从任意有 spot_id 的事件推断
    if assigned_t is None:
        for e in veh_ev:
            sid = e.get("spot_id", "")
            if sid:
                assigned_t = e["time"]; spot_id = sid; break

    # 动画起点：该车实际入口（事件元数据），否则默认入口
    en = net.nodes.get(origin_entry) if origin_entry else None
    if en is None or en.node_type != NodeType.ENTRY:
        en = next((n for n in net.nodes.values() if n.node_type == NodeType.ENTRY), None)
    ep = (en.x, en.y) if en else (0.0, 0.0)
    entry_id = en.node_id if en else "ENTRY"

    # 没找到任何分配 → 入口位置
    if assigned_t is None or not spot_id:
        return ep

    # 还没到分配时间 → 入口
    if t < assigned_t:
        return ep

    # 获取路径（从该车实际入口到车位）
    path = None
    if "sim_pe" in st.session_state:
        try:
            pe = st.session_state.sim_pe
            path = pe.shortest_path(entry_id, spot_id)
        except Exception:
            path = None
    if not path:
        path = [entry_id, spot_id]

    # 计算到达时间（如果没找到确切 entry 事件，估算）
    if entry_t is None or entry_t <= assigned_t:
        # 按路径长度估算：每单位距离 0.5 秒
        total_dist = 0.0
        for i in range(len(path) - 1):
            fn = net.nodes.get(path[i]); tn = net.nodes.get(path[i + 1])
            if fn and tn:
                total_dist += math.hypot(tn.x - fn.x, tn.y - fn.y)
        entry_t = assigned_t + max(total_dist * 0.5, 2.0)

    # 行驶阶段
    if t < entry_t and path and len(path) >= 2:
        dur = max(entry_t - assigned_t, 0.5)
        prog = min(max((t - assigned_t) / dur, 0.0), 1.0)
        return _interp_path(net, path, prog)

    # 已停入 → 返回车位位置
    nd = net.nodes.get(spot_id)
    return (nd.x, nd.y) if nd else ep


def _interp_path(net, nodes, prog):
    segs, total = [], 0.0
    for i in range(len(nodes)-1):
        fn = net.nodes.get(nodes[i]); tn = net.nodes.get(nodes[i+1])
        if fn and tn:
            sl = max(math.hypot(tn.x-fn.x, tn.y-fn.y), 0.01)
            segs.append((fn, tn, sl)); total += sl
    if total == 0: return (0.0, 0.0)
    target = prog * total; acc = 0.0
    for fn, tn, sl in segs:
        if acc + sl >= target:
            sp = (target-acc)/sl
            return (fn.x+(tn.x-fn.x)*sp, fn.y+(tn.y-fn.y)*sp)
        acc += sl
    l = segs[-1]; return (l[1].x, l[1].y)


def _est_path_duration(net, path, min_sec: float = 3.0) -> float:
    """按路径长度估算行驶时长：0.5 s/m（与动画插值口径一致），最短 min_sec。"""
    total = 0.0
    for i in range(len(path) - 1):
        fn = net.nodes.get(path[i]); tn = net.nodes.get(path[i + 1])
        if fn and tn:
            total += math.hypot(tn.x - fn.x, tn.y - fn.y)
    return max(total * 0.5, min_sec)


def interp_path_segment(net, path, t_start, t_end, t):
    """按时间 t 在路径段 [t_start, t_end] 上线性插值位置（用于离场/移位动画）。"""
    if not path or len(path) < 2:
        nd = net.nodes.get(path[0]) if path else None
        return (nd.x, nd.y) if nd else (0.0, 0.0)
    if t_end <= t_start:
        prog = 0.0
    else:
        prog = min(max((t - t_start) / (t_end - t_start), 0.0), 1.0)
    return _interp_path(net, path, prog)
