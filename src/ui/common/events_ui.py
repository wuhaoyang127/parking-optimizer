"""事件日志 → 车辆明细表 / 需求时序直方图。"""
from ui.common._imports import *


def _fmt_clock(seconds):
    """把秒数格式化为 HH:MM:SS；None/非有限值返回 '-'。"""
    if seconds is None:
        return "-"
    try:
        f = float(seconds)
        if not math.isfinite(f):
            return "-"
        sec = int(round(f))
    except (TypeError, ValueError, OverflowError):
        return "-"
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _finite_time(value):
    """把事件时间转成有限非负 float；异常或非有限返回 None。"""
    try:
        f = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return f if math.isfinite(f) and f >= 0 else None


def build_vehicle_detail_rows(events_raw):
    """从事件日志（dict 列表）提取每辆车的到达/离开明细，返回 list[dict]。"""
    by_vid = {}
    for e in events_raw:
        vid = str(e.get("vehicle_id", "") or "")
        if not vid:
            continue
        rec = by_vid.setdefault(vid, {
            "arrival": None, "assigned_spot": "", "entry": None, "departure": None,
            "wait_start": None, "wait_end": None, "rejected": False,
        })
        et = e.get("type")
        t = e.get("time", 0)
        if et == "vehicle_arrival":
            rec["arrival"] = t
        elif et == "parking_assigned":
            rec["assigned_spot"] = str(e.get("spot_id", "") or "")
        elif et == "spot_entry":
            rec["entry"] = t
        elif et == "departure" and rec["departure"] is None:
            rec["departure"] = t
        elif et == "wait_start":
            rec["wait_start"] = t
        elif et == "wait_end":
            rec["wait_end"] = t
        elif et == "rejected":
            rec["rejected"] = True

    rows = []
    for vid in sorted(by_vid):
        rec = by_vid[vid]
        arr = _finite_time(rec["arrival"])
        dep = _finite_time(rec["departure"])
        entry = _finite_time(rec["entry"])
        ws = _finite_time(rec["wait_start"])
        we = _finite_time(rec["wait_end"])
        wait = None
        if ws is not None:
            end = we if we is not None else arr
            if end is None:
                end = ws
            wait = round(end - ws, 1)
        rows.append({
            "车辆编号": vid,
            "到达时间(s)": round(arr, 1) if arr is not None else None,
            "到达时刻": _fmt_clock(arr),
            "分配车位": rec["assigned_spot"] or "-",
            "进入车位(s)": round(entry, 1) if entry is not None else None,
            "离场时间(s)": round(dep, 1) if dep is not None else None,
            "离场时刻": _fmt_clock(dep),
            "等待时长(s)": wait,
            "状态": "拒绝" if rec["rejected"] else "正常",
        })
    return rows


def build_demand_histogram(events_raw, bin_hours=1):
    """到达/离场按时段分布的条形图（plotly Figure）；无事件返回 None。"""
    arrivals = [_finite_time(e.get("time"))
                for e in events_raw if e.get("type") == "vehicle_arrival"]
    departures = [_finite_time(e.get("time"))
                  for e in events_raw if e.get("type") == "departure"]
    arrivals = [t for t in arrivals if t is not None]
    departures = [t for t in departures if t is not None]
    if not arrivals and not departures:
        return None

    bin_s = bin_hours * 3600
    max_t = max(arrivals + departures)
    n_bins = max(1, int(math.ceil(max_t / bin_s)))
    labels, a_counts, d_counts = [], [0] * n_bins, [0] * n_bins
    for t in arrivals:
        a_counts[min(int(t // bin_s), n_bins - 1)] += 1
    for t in departures:
        d_counts[min(int(t // bin_s), n_bins - 1)] += 1
    for i in range(n_bins):
        labels.append(f"{i * bin_hours}-{i * bin_hours + bin_hours}h")

    fig = go.Figure()
    fig.add_trace(go.Bar(name="到达", x=labels, y=a_counts, marker_color="#3b82f6"))
    fig.add_trace(go.Bar(name="离场", x=labels, y=d_counts, marker_color="#f59e0b"))
    fig.update_layout(barmode="group", height=320,
                      margin=dict(l=30, r=30, t=40, b=30),
                      xaxis_title="仿真时段", yaxis_title="车辆数",
                      legend=dict(orientation="h", yanchor="bottom", y=1.02))
    return fig
