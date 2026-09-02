"""历史运行页：时间格式化/摘要/对比辅助。"""
from datetime import datetime

from ui.common import *


def _fmt_run_time(value):
    """把 Supabase 时间字符串格式化为易读本地时间。"""
    if not value:
        return ""
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return value.replace("T", " ")[:16]
    return str(value)[:16]


def _run_summary(metrics):
    """从 metrics（dict 单策略 / list 全部对比）提取代表性指标与说明。"""
    if isinstance(metrics, dict):
        return metrics, ""
    if isinstance(metrics, list) and metrics:
        best = max(metrics, key=lambda m: (m.get("satisfaction_rate", 0),
                                           -m.get("shift_count", 0)))
        label = STRATEGY_LABELS.get(best.get("strategy"), best.get("strategy"))
        return best, f"全部对比 {len(metrics)} 策略；最佳：{label}"
    return {}, ""


# 两次运行对比的指标清单（显示名, 字段, 方向）
COMPARE_FIELDS = [
    ("满足率", "satisfaction_rate", "max"),
    ("利用率", "spatial_utilization", "max"),
    ("平均等待(s)", "avg_wait_time_s", "min"),
    ("移位次数", "shift_count", "min"),
    ("移位距离(m)", "shift_distance_m", "min"),
    ("行驶距离(m)", "total_drive_distance_m", "min"),
    ("拒绝数", "rejected_count", "min"),
    ("运行耗时(s)", "runtime_s", "min"),
]


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _fmt_metric(label: str, v):
    if v is None:
        return "—"
    if label in ("满足率", "利用率"):
        return f"{v:.1%}"
    if label in ("移位次数", "拒绝数"):
        return f"{v:.0f}"
    if label.endswith("(s)"):
        return f"{v:.1f}"
    if label.endswith("(m)"):
        return f"{v:.0f}"
    return f"{v:.3f}"


def _compare_radar(rep_a: dict, rep_b: dict):
    """两次运行的五维雷达图（每维按两者 min–max 归一化，外圈=更好）。"""
    import plotly.graph_objects as go
    dims = [("满足率", "satisfaction_rate", "max"),
            ("利用率", "spatial_utilization", "max"),
            ("平均等待", "avg_wait_time_s", "min"),
            ("移位次数", "shift_count", "min"),
            ("行驶距离", "total_drive_distance_m", "min")]
    labels = [d[0] for d in dims]
    norm_a, norm_b = [], []
    for _, field, direction in dims:
        a = _num(rep_a.get(field)) or 0.0
        b = _num(rep_b.get(field)) or 0.0
        lo, hi = min(a, b), max(a, b)
        if hi == lo:
            na = nb = 0.5
        else:
            na = (a - lo) / (hi - lo)
            nb = (b - lo) / (hi - lo)
            if direction == "min":
                na, nb = 1 - na, 1 - nb
        norm_a.append(na)
        norm_b.append(nb)
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(r=norm_a + [norm_a[0]], theta=labels + [labels[0]],
                                  name="运行 A", fill="toself", opacity=0.45))
    fig.add_trace(go.Scatterpolar(r=norm_b + [norm_b[0]], theta=labels + [labels[0]],
                                  name="运行 B", fill="toself", opacity=0.45))
    fig.update_layout(height=400, margin=dict(l=60, r=60, t=50, b=50),
                      legend=dict(orientation="h", yanchor="bottom", y=-0.15),
                      polar=dict(radialaxis=dict(range=[0, 1], showticklabels=False)))
    return fig
