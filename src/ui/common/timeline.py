"""动态路径页时间线与回放状态计算。"""
from ui.common._imports import *


def build_timeline(events, net, pe):
    vehicles_tl = {}; events_by_time = {}
    for e in events:
        events_by_time.setdefault(e.time, []).append(e)
        vid = e.vehicle_id
        if not vid: continue
        if vid not in vehicles_tl:
            vehicles_tl[vid] = {"arrival_time": None, "assigned_time": None, "spot_entry_time": None,
                "departure_start": None, "departure_end": None, "spot_id": None,
                "path_nodes": None, "rejected": False, "shifts": []}
        tl = vehicles_tl[vid]; et = e.event_type.value
        if et == "vehicle_arrival": tl["arrival_time"] = e.time
        elif et == "parking_assigned":
            tl["assigned_time"] = e.time; tl["spot_id"] = e.spot_id
            try: tl["path_nodes"] = pe.shortest_path(pe.entry_id, e.spot_id)
            except: tl["path_nodes"] = [pe.entry_id, e.spot_id]
        elif et == "spot_entry":
            tl["spot_entry_time"] = e.time
            # 多入口：按该车实际入口重建入库路径（事件元数据带 entry）
            origin = e.metadata.get("entry") or pe.entry_id
            try: tl["path_nodes"] = pe.shortest_path(origin, e.spot_id)
            except: tl["path_nodes"] = [origin, e.spot_id]
        elif et == "departure":
            tl["departure_start"] = e.time
            if not e.metadata.get("had_blocking"): tl["departure_end"] = e.time
        elif et == "shift_start":
            tl["shifts"].append({"from": e.metadata.get("from_spot"), "to": e.metadata.get("to_spot"),
                                "start": e.time, "end": None})
            if tl["departure_start"] is None: tl["departure_start"] = e.time
        elif et == "shift_end":
            if tl["shifts"]: tl["shifts"][-1]["end"] = e.time
            tl["departure_end"] = e.time
        elif et == "rejected": tl["rejected"] = True
    all_times = sorted(set(e.time for e in events))
    if all_times and all_times[0] > 0: all_times.insert(0, 0.0)
    return {"all_times": all_times, "max_time": all_times[-1] if all_times else 0,
            "vehicles": vehicles_tl, "events_by_time": events_by_time}


def replay_state(events_raw, t, spots, net):
    ss = {s.spot_id: {"occ": False, "by": "", "blocked": False} for s in spots}
    dv = []; v_spot = {}; v_entered = {}; v_departing = {}
    for e in events_raw:
        if e["time"] > t: break
        vid = str(e.get("vehicle_id", ""))
        if not vid: continue
        et = e["type"]
        if et == "vehicle_arrival": v_spot[vid] = None; v_entered[vid] = False; v_departing[vid] = False
        elif et == "parking_assigned": v_spot[vid] = e.get("spot_id", "")
        elif et == "spot_entry": v_entered[vid] = True
        elif et in ("departure", "shift_start", "shift_end"): v_departing[vid] = True
        elif et == "rejected": v_spot.pop(vid, None); v_entered.pop(vid, None); v_departing.pop(vid, None)
    for vid, spot_id in v_spot.items():
        if spot_id and v_entered.get(vid) and not v_departing.get(vid):
            if spot_id in ss: ss[spot_id]["occ"] = True; ss[spot_id]["by"] = vid
    for vid, spot_id in v_spot.items():
        if spot_id and not v_entered.get(vid) and not v_departing.get(vid):
            nx, ny = 0.0, 0.0
            if spot_id in net.nodes: nd = net.nodes[spot_id]; nx, ny = nd.x, nd.y
            dv.append({"vid": vid, "x": nx, "y": ny, "st": "驶入", "target": spot_id})
    sg = {}
    for s in spots: sg.setdefault(s.stack_group_id, []).append(s)
    for g, grp in sg.items():
        grp.sort(key=lambda s: s.depth)
        for i, inner in enumerate(grp):
            for j in range(i):
                if ss[grp[j].spot_id]["occ"] and ss[inner.spot_id]["occ"]:
                    ss[inner.spot_id]["blocked"] = True
    return {"ss": ss, "dv": dv}
