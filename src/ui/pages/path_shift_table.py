"""动态路径页：移位车辆表构建。"""
from ui.common import *


def _build_shift_rows(events):
    """收集全部 shift_start 事件，返回移位车辆明细行列表。"""
    shift_rows = []
    for e in events:
        if e.get("type") != "shift_start":
            continue
        meta = e.get("metadata", {}) or {}
        vid = str(e.get("vehicle_id", ""))
        end_time = None
        for e2 in events:
            if (e2.get("type") == "shift_end" and str(e2.get("vehicle_id", "")) == vid
                    and float(e2["time"]) >= float(e["time"])):
                end_time = float(e2["time"]); break
        shift_rows.append({
            "移位车辆": vid,
            "开始(s)": round(float(e["time"]), 1),
            "从车位": meta.get("from_spot", ""),
            "到车位(缓冲)": meta.get("to_spot", ""),
            "让行对象": str(meta.get("blocked_vehicle", "—")),
            "原因": meta.get("reason", ""),
            "回位(s)": round(end_time, 1) if end_time is not None else "未回位",
        })
    return shift_rows
