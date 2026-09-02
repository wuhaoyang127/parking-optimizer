"""车辆入库/离场/移位路径段提取（动态路径三阶段回放）。"""
from ui.common._imports import *
from ui.common.interp import _est_path_duration


def build_vehicle_phases(net, pe, events, vid):
    """从事件日志提取车辆 vid 的入库 / 离场 / 移位路径段。

    events 元素形如 {"time","type","vehicle_id","spot_id","metadata"}。
    返回:
      {
        "enter": {"path", "t_start", "t_end", "spot_id", "entry_id"} | None,
        "leave": {"path", "t_start", "t_end", "spot_id", "exit_id",
                  "helper_shifts": [{"path","from_spot","to_spot","vehicle_id"}]} | None,
        "shifts": [{"path","from_spot","to_spot","t_start","t_end"}],
      }
    路径缺失/不可达时回退直连两节点；结束时刻缺失时按路径长度估算。
    """
    veh_ev = sorted([e for e in events if str(e.get("vehicle_id", "")) == str(vid)],
                    key=lambda e: e["time"])
    result = {"enter": None, "leave": None, "shifts": []}

    # ── 入库段：parking_assigned → spot_entry；起点为该车实际入口 ──
    t_assign = None; t_entry = None; spot_id = None; entry_origin = None
    for e in veh_ev:
        et = e.get("type")
        if et == "parking_assigned" and t_assign is None:
            t_assign = float(e["time"]); spot_id = e.get("spot_id", "")
        elif et == "spot_entry" and t_entry is None:
            t_entry = float(e["time"])
            meta = e.get("metadata", {}) or {}
            entry_origin = meta.get("entry")
            if not spot_id:
                spot_id = e.get("spot_id", "")
    if t_assign is not None and spot_id:
        origin = entry_origin or pe.entry_id
        path = pe.shortest_path(origin, spot_id) or [origin, spot_id]
        if t_entry is None or t_entry <= t_assign:
            t_entry = t_assign + _est_path_duration(net, path)
        result["enter"] = {"path": path, "t_start": t_assign, "t_end": t_entry,
                           "spot_id": spot_id, "entry_id": origin}

    # ── 离场段：departure 时刻起；终点为该车出口 ──
    dep = next((e for e in veh_ev if e.get("type") == "departure"), None)
    if dep is not None and spot_id:
        meta = dep.get("metadata", {}) or {}
        exit_id = meta.get("exit") or pe.default_exit_id or pe.entry_id
        path = pe.shortest_path(spot_id, exit_id) or [spot_id, exit_id]
        t_start = float(dep["time"])
        # 若该车曾作为移位车（先被移走再回位），离场动画从其移位回位后开始
        own_shift_ends = [float(e["time"]) for e in veh_ev if e.get("type") == "shift_end"]
        if own_shift_ends:
            t_start = max(t_start, max(own_shift_ends))
        t_end = t_start + _est_path_duration(net, path)
        result["leave"] = {"path": path, "t_start": t_start, "t_end": t_end,
                           "spot_id": spot_id, "exit_id": exit_id,
                           "helper_shifts": _helper_shift_paths(pe, events, vid)}

    # ── 移位段：该车作为移位车（shift_start → 最近 shift_end） ──
    for e in veh_ev:
        if e.get("type") != "shift_start":
            continue
        meta = e.get("metadata", {}) or {}
        frm = meta.get("from_spot"); to = meta.get("to_spot")
        if not frm or not to:
            continue
        path = pe.shortest_path(frm, to) or [frm, to]
        t_start = float(e["time"])
        t_end = None
        for e2 in veh_ev:
            if e2.get("type") == "shift_end" and float(e2["time"]) >= t_start:
                t_end = float(e2["time"]); break
        if t_end is None or t_end <= t_start:
            t_end = t_start + _est_path_duration(net, path)
        result["shifts"].append({"path": path, "from_spot": frm, "to_spot": to,
                                 "t_start": t_start, "t_end": t_end})
    return result


def _helper_shift_paths(pe, events, vid):
    """为 vid 让行而发生的移位轨迹（shift_start 的 blocked_vehicle == vid）。"""
    out = []
    for e in events:
        if e.get("type") != "shift_start":
            continue
        meta = e.get("metadata", {}) or {}
        if str(meta.get("blocked_vehicle", "")) != str(vid):
            continue
        frm = meta.get("from_spot"); to = meta.get("to_spot")
        if not frm or not to:
            continue
        path = pe.shortest_path(frm, to) or [frm, to]
        out.append({"path": path, "from_spot": frm, "to_spot": to,
                    "vehicle_id": str(e.get("vehicle_id", ""))})
    return out
