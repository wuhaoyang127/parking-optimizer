"""车辆入库/离场/移位路径段提取（动态路径三阶段回放）。"""
from ui.common._imports import *
from ui.common.interp import _est_path_duration


def _spot_at_time(veh_ev, t, default):
    """重放车辆自身事件，返回 t 时刻实际所在车位。

    车辆被移位后跟随 shift_start.to_spot（缓冲位），回位后跟随
    shift_end.final_spot（缺省回退到最近一次 shift_start.from_spot）。
    """
    pos = default
    last_from = None
    for e in veh_ev:
        if float(e["time"]) > t:
            break
        et = e.get("type")
        if et in ("parking_assigned", "spot_entry"):
            sid = e.get("spot_id")
            if sid:
                pos = str(sid)
        elif et == "shift_start":
            meta = e.get("metadata", {}) or {}
            last_from = meta.get("from_spot")
            to = meta.get("to_spot")
            if to:
                pos = str(to)
        elif et == "shift_end":
            meta = e.get("metadata", {}) or {}
            fin = meta.get("final_spot") or last_from
            if fin:
                pos = str(fin)
    return pos


def build_vehicle_phases(net, pe, events, vid):
    """从事件日志提取车辆 vid 的入库 / 离场 / 移位路径段。

    events 元素形如 {"time","type","vehicle_id","spot_id","metadata"}。
    返回:
      {
        "enter": {"path", "t_start", "t_end", "spot_id", "entry_id"} | None,
        "leave": {"path", "t_start", "t_end", "spot_id", "exit_id",
                  "helper_shifts": [{"path","from_spot","to_spot","vehicle_id"}]} | None,
        "shifts": [{"path","from_spot","to_spot","t_start","t_end",
                    "kind":"shift"|"return"}],
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
        path = pe.shortest_path(origin, spot_id)
        if not path and origin != pe.entry_id:
            # 该入口到车位不可达：按引擎口径回退默认入口
            origin = pe.entry_id
            path = pe.shortest_path(origin, spot_id)
        if not path:
            # 真的不可达：只标车位，不画假直线
            path = [spot_id]
        if t_entry is None or t_entry <= t_assign:
            t_entry = t_assign + _est_path_duration(net, path)
        result["enter"] = {"path": path, "t_start": t_assign, "t_end": t_entry,
                           "spot_id": spot_id, "entry_id": origin}

    # ── 离场段：departure 时刻起；起点为该车此刻实际车位（移位后跟随）──
    dep = next((e for e in veh_ev if e.get("type") == "departure"), None)
    if dep is not None and spot_id:
        dep_time = float(dep["time"])
        meta = dep.get("metadata", {}) or {}
        exit_id = meta.get("exit") or pe.default_exit_id or pe.entry_id
        leave_spot = _spot_at_time(veh_ev, dep_time, spot_id)
        path = pe.shortest_path(leave_spot, exit_id)
        if not path and exit_id != pe.entry_id:
            # 事件记录的出口从该车位不可达：按引擎离场口径回退入口
            exit_id = pe.entry_id
            path = pe.shortest_path(leave_spot, exit_id)
        if not path:
            # 真的不可达：只标起点，不画穿越空地的假直线
            path = [leave_spot]
        t_start = dep_time
        # 若该车曾作为移位车（先被移走再回位），离场动画从其移位回位后开始
        own_shift_ends = [float(e["time"]) for e in veh_ev if e.get("type") == "shift_end"]
        if own_shift_ends:
            t_start = max(t_start, max(own_shift_ends))
        t_end = t_start + _est_path_duration(net, path)
        result["leave"] = {"path": path, "t_start": t_start, "t_end": t_end,
                           "spot_id": leave_spot, "exit_id": exit_id,
                           "helper_shifts": _helper_shift_paths(pe, events, vid)}

    # ── 移位段：该车作为移位车（shift_start → 最近 shift_end；含回位段）──
    for e in veh_ev:
        if e.get("type") != "shift_start":
            continue
        meta = e.get("metadata", {}) or {}
        frm = meta.get("from_spot"); to = meta.get("to_spot")
        if not frm or not to:
            continue
        path = pe.shortest_path(frm, to) or [frm]
        t_start = float(e["time"])
        t_end = None
        final = None
        for e2 in veh_ev:
            if e2.get("type") == "shift_end" and float(e2["time"]) >= t_start:
                t_end = float(e2["time"])
                final = (e2.get("metadata", {}) or {}).get("final_spot")
                break
        has_end = t_end is not None and t_end > t_start
        if not has_end:
            t_end = t_start + _est_path_duration(net, path)
        result["shifts"].append({"path": path, "from_spot": frm, "to_spot": to,
                                 "t_start": t_start, "t_end": t_end, "kind": "shift"})
        # 回位段：缓冲位 → 回位目标（shift_end.final_spot，缺省为原车位）；
        # 仅当存在 shift_end（确实回位）时才有该段
        if has_end:
            back_to = final or frm
            back_path = pe.shortest_path(to, back_to) or [to]
            back_dur = _est_path_duration(net, back_path)
            result["shifts"].append({"path": back_path, "from_spot": to, "to_spot": back_to,
                                     "t_start": max(t_start, t_end - back_dur),
                                     "t_end": t_end, "kind": "return"})
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
        path = pe.shortest_path(frm, to) or [frm]
        out.append({"path": path, "from_spot": frm, "to_spot": to,
                    "vehicle_id": str(e.get("vehicle_id", ""))})
    return out
