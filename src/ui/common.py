from __future__ import annotations

import sys, hashlib, json, math, os, time
from pathlib import Path
# 确保 src 在 sys.path（本文件位于 src/ui/，其父目录的父目录是 src）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auth import login as auth_login, register as auth_register
from auth import logout as auth_logout, list_users as auth_list_users
from auth import update_user_role as auth_update_role, delete_user as auth_delete_user
from auth import change_password as auth_change_pw, reset_user_password as auth_reset_pw
from auth import export_users as auth_export_users, import_users as auth_import_users
from auth import set_session_token, clear_session_token, restore_session
from auth import get_preference as auth_get_pref, set_preference as auth_set_pref
# 本地计算纯函数（布局构建/仿真运行/车辆序列化）统一从 local_compute 导入：
# ui 与 local_worker 共用同一实现，worker 无需安装 Streamlit/Pandas/Plotly。
from local_compute import (LAYOUT_BUILDERS, LAYOUTS, BUILTIN_LAYOUT_KEYS,
                           build_linear, build_rectangle, build_lshape,
                           build_triangle, build_circle,
                           run_single, COUNT_FIELDS, _avg_metrics,
                           build_layout_from_json, _vehicle_to_dict)
# 以下新增函数做容错导入：若部署缓存导致 auth.py 未同步到最新，
# 用 stub 降级，避免整个 app 因单个函数缺失而崩溃（登录等核心功能不受影响）。
try:
    from auth import check_supabase_health
except ImportError:
    def check_supabase_health():
        return {"online": False, "api_key_valid": False, "status": "error",
                "message": "功能未加载：后端代码未同步，请在 Streamlit Cloud 重新部署",
                "latency_ms": None, "checked_at": ""}

try:
    from auth import submit_feedback as auth_submit_feedback
    from auth import list_my_feedbacks as auth_list_my_feedbacks
    from auth import list_feedbacks as auth_list_feedbacks
    from auth import update_feedback_status as auth_update_feedback_status
    from auth import reply_feedback as auth_reply_feedback
    from auth import delete_feedback as auth_delete_feedback
    from auth import update_feedback_display_time as auth_update_feedback_display_time
except ImportError:
    def _fb_unavailable(*_a, **_k):
        return {"success": False, "error": "反馈功能未加载：后端代码未同步，请重新部署应用"}

    auth_submit_feedback = _fb_unavailable
    auth_list_my_feedbacks = lambda *_a, **_k: []
    auth_list_feedbacks = lambda *_a, **_k: []
    auth_update_feedback_status = _fb_unavailable
    auth_reply_feedback = _fb_unavailable
    auth_delete_feedback = _fb_unavailable
    auth_update_feedback_display_time = _fb_unavailable

try:
    from auth import save_sim_run as auth_save_sim_run
    from auth import list_sim_runs as auth_list_sim_runs
    from auth import delete_sim_run as auth_delete_sim_run
    from auth import log_action as auth_log_action
except ImportError:
    def _sim_runs_unavailable(*_a, **_k):
        return {"success": False, "error": "运行记录功能未加载：后端代码未同步，请重新部署应用"}

    auth_save_sim_run = _sim_runs_unavailable
    auth_list_sim_runs = lambda *_a, **_k: []
    auth_delete_sim_run = _sim_runs_unavailable
    auth_log_action = _sim_runs_unavailable

try:
    from auth import create_compute_task as auth_create_compute_task
    from auth import get_compute_task as auth_get_compute_task
    from auth import requeue_compute_task as auth_requeue_compute_task
    from auth import get_latest_compute_task as auth_get_latest_compute_task
    from auth import delete_compute_task as auth_delete_compute_task
except ImportError:
    def _compute_tasks_unavailable(*_a, **_k):
        return {"success": False, "error": "本地计算任务功能未加载：请先执行 migrations/07_compute_tasks.sql"}

    auth_create_compute_task = _compute_tasks_unavailable
    auth_get_compute_task = _compute_tasks_unavailable
    auth_requeue_compute_task = _compute_tasks_unavailable
    auth_get_latest_compute_task = _compute_tasks_unavailable
    auth_delete_compute_task = _compute_tasks_unavailable

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from parking_opt.domain.spot import RoadNetwork, RoadNode, NodeType, Spot, SpotType, Vehicle
from parking_opt.routing.path_engine import PathEngine
from parking_opt.simulation.parking_lot import ParkingLot
from parking_opt.simulation.engine import SimulationEngine
from parking_opt.simulation.arrival import generate_demand
from parking_opt.simulation.defaults import (CAR_SPEED, MAX_WAIT_TIME, SIM_DURATION,
                                             DURATION_MIN, DURATION_MAX, PEAK_RATIO, ERROR_RATIO)
from parking_opt.strategies import StrategyRegistry
from parking_opt.strategies.mosa import estimate_scene as estimate_mosa_scene
from parking_opt.strategies.mosa import resolve_scene as resolve_mosa_scene
from parking_opt.strategies.mosa import SCENE_LABELS as MOSA_SCENE_LABELS
from parking_opt.evaluation.metrics import compute_metrics
from parking_opt.evaluation.ranking import (weighted_rank, below_significance_fields,
                                            DEFAULT_WEIGHTS as RANK_DEFAULT_WEIGHTS)
from parking_opt.io.demand_io import export_demand_json, parse_demand_json
from parking_opt.optimization.cpsat_baseline import CPSatBaseline
from viz import draw_parking_layout

# ═══════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════
# 策略显示名：从注册表动态生成（新算法在 strategies/__init__.py 登记后自动出现）
STRATEGY_LABELS = {name: cls.label for name, cls in StrategyRegistry.all().items()}
STRATEGY_LABELS["compare_all"] = "全部对比"

# 算法评估指标：显示名 -> (指标字段, 方向, 说明)
# 方向: "max"=越大越好, "min"=越小越好
PRIORITY_METRICS = {
    "满足率": ("satisfaction_rate", "max", "尽可能多的车辆被分配到位"),
    "利用率": ("spatial_utilization", "max", "提高车位时空利用率"),
    "平均等待": ("avg_wait_time_s", "min", "减少车辆排队等待时间"),
    "移位次数": ("shift_count", "min", "减少纵深移位的次数"),
    "移位距离": ("shift_distance_m", "min", "减少移位产生的额外行驶成本"),
    "行驶距离": ("total_drive_distance_m", "min", "降低车辆整体行驶成本"),
    "运行耗时": ("runtime_s", "min", "保证算法实时可用"),
}
# 默认优先级顺序（从高到低）
DEFAULT_PRIORITY = ["满足率", "利用率", "平均等待", "移位次数", "移位距离", "行驶距离", "运行耗时"]

# 加权评分默认权重（中文指标名 -> 百分值，总和 100）；字段名见 ranking.DEFAULT_WEIGHTS
DEFAULT_WEIGHTS_BY_LABEL = {
    "满足率": 30, "利用率": 25, "平均等待": 15, "移位次数": 10,
    "移位距离": 10, "行驶距离": 5, "运行耗时": 5,
}

# 需求序列导出的项目内文件夹（本地运行时方便下次直接从这里导入；不入库）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEMAND_EXPORT_DIR = PROJECT_ROOT / "data" / "demand_exports"
# 自定义布局本地备份文件（仅本地桌面运行时写入，作为 Supabase 失败时的兜底恢复源）
LOCAL_LAYOUT_BACKUP_PATH = PROJECT_ROOT / "data" / "custom_layouts_backup.json"

def strategy_description(name: str) -> str:
    """返回策略说明：优先读策略类的 DESCRIPTION 属性，新算法接入后无需改这里即可自动展示。"""
    if name == "compare_all":
        return "**全部对比**\n\n同时运行以上所有策略（默认参数），按你设定的优先级排序并推荐最优策略。"
    cls = StrategyRegistry.get(name)
    if cls and getattr(cls, "DESCRIPTION", ""):
        return cls.DESCRIPTION
    return "**该算法暂无详细说明**"


ADMIN_USER = "wuhaoyang127"
LOGIN_MAX_FAILS = 3       # 连续登录失败多少次后临时锁定
LOGIN_LOCK_SECONDS = 30   # 临时锁定时长（秒）
STRATEGY_TIME_BUDGET = 60.0  # 每个种子单次仿真的超时标记（秒）：超过仅标记，结果仍全部展示，可在指标页选择隐藏
ROLES = {
    "admin": {"can_configure": True, "can_manage_users": True, "can_run_simulation": True,
              "can_export": True, "can_debug": True, "can_manage_data": True,
              "can_import_algo": True, "label": "管理员"},
    "operator": {"can_configure": True, "can_manage_users": False, "can_run_simulation": True,
                 "can_export": True, "can_debug": True, "can_manage_data": False,
                 "can_import_algo": False, "label": "操作员"},
    "viewer": {"can_configure": False, "can_manage_users": False, "can_run_simulation": True,
               "can_export": False, "can_debug": False, "can_manage_data": False,
               "can_import_algo": False, "label": "访客"},
}
# LAYOUT_BUILDERS / LAYOUTS / BUILTIN_LAYOUT_KEYS 已从 src/local_compute.py 导入（见文件顶部）

# 自定义布局 JSON 的最简示例（供「导入布局」页下载参考）
EXAMPLE_LAYOUT = {
    "name": "我的停车场",
    "nodes": [
        {"id": "ENTRY", "type": "entry", "x": 0, "y": 0},
        {"id": "R1", "type": "road", "x": 5, "y": 0},
        {"id": "S01", "type": "spot", "x": 8, "y": 3, "spot_type": "standalone"},
        {"id": "T1-1", "type": "spot", "x": 8, "y": -3, "spot_type": "tandem", "group": "T1", "depth": 1},
        {"id": "T1-2", "type": "spot", "x": 11, "y": -3, "spot_type": "tandem", "group": "T1", "depth": 2},
    ],
    "edges": [
        {"from": "ENTRY", "to": "R1", "distance": 5},
        {"from": "R1", "to": "S01", "distance": 3},
        {"from": "S01", "to": "R1", "distance": 3},
        {"from": "R1", "to": "T1-1", "distance": 3},
        {"from": "T1-1", "to": "T1-2", "distance": 3},
        {"from": "T1-2", "to": "T1-1", "distance": 3},
        {"from": "T1-1", "to": "R1", "distance": 3},
        {"from": "R1", "to": "ENTRY", "distance": 5},
    ],
}

GLOBAL_CSS = """
<style>
:root { --primary: #1a2332; --accent: #3b82f6; --bg: #f1f5f9; --card: #fff; --text: #1e293b;
    --muted: #64748b; --border: #e2e8f0; --radius: 10px; --shadow: 0 1px 3px rgba(0,0,0,.06); }
.stApp { background: var(--bg); }
h1 { font-size: 1.5rem!important; font-weight: 700!important; color: var(--primary)!important; }
h2 { font-size: 1.15rem!important; font-weight: 600!important; color: var(--primary)!important; }
.metric-card { background: var(--card); border-radius: var(--radius); padding: .6rem .7rem;
    box-shadow: var(--shadow); text-align: center; border-top: 3px solid var(--accent); }
.metric-card .val { font-size: 1.3rem; font-weight: 700; color: var(--primary); }
.metric-card .lbl { font-size: .68rem; color: var(--muted); }
.metric-card.warn { border-top-color: #f59e0b; } .metric-card.bad { border-top-color: #ef4444; }
.metric-card.good { border-top-color: #22c55e; }
section[data-testid="stSidebar"] { background: linear-gradient(180deg, #0f172a, #1e3a5f); }
/* 全侧边栏文字亮色 + 放大 */
section[data-testid="stSidebar"] * { color: #f1f5f9!important; font-size: 1.05rem!important; }
section[data-testid="stSidebar"] .stRadio label {
    font-size: 1.7rem!important; padding: .9rem 1.1rem!important; border-radius: 10px!important;
    margin-bottom: 6px!important; transition: all 0.15s!important; }
/* 悬停 */
section[data-testid="stSidebar"] .stRadio div[role="radiogroup"] label:hover {
    background: rgba(255,255,255,.12)!important; }
/* 选中 - 只加光圈，无填充 */
section[data-testid="stSidebar"] .stRadio div[role="radiogroup"] label[data-selected="true"] {
    background: transparent!important; color: #22d3ee!important;
    font-weight: 700!important; font-size: 1.8rem!important;
    border: 2px solid #22d3ee!important;
    box-shadow: 0 0 12px rgba(34,211,238,.35), inset 0 0 6px rgba(34,211,238,.1)!important; }
section[data-testid="stSidebar"] .stRadio div[role="radiogroup"] label[data-selected="true"] * {
    color: #22d3ee!important; background: transparent!important; }
/* 按钮 */
section[data-testid="stSidebar"] .stButton>button { background: rgba(255,255,255,.08)!important;
    border: 1px solid rgba(255,255,255,.15)!important; border-radius: 9px!important;
    font-size: 1.1rem!important; padding: .6rem 1.1rem!important; }
section[data-testid="stSidebar"] .stButton>button:hover { background: rgba(255,255,255,.18)!important;
    border-color: rgba(34,211,238,.5)!important; }
.stButton>button[kind="primary"] { background: linear-gradient(135deg, #3b82f6, #2563eb)!important;
    border: none!important; border-radius: 8px!important; font-weight: 600!important; color: white!important; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: var(--radius);
    padding: .7rem; margin-bottom: .4rem; box-shadow: var(--shadow); }
hr { margin: .4rem 0; border-color: var(--border); }
</style>
"""

# ═══════════════════════════════════════════════════════════
# 停车场布局构建器 / 仿真运行 / 车辆序列化
# 已移至 src/local_compute.py（本文件顶部 import 引入），
# 使 local_worker 无需安装 Streamlit/Pandas/Plotly 即可复用。
# ═══════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════
# 仿真 & 时间轴工具函数（run_single/_avg_metrics 已移至 local_compute）
# ═══════════════════════════════════════════════════════════


def _plot_radar(all_m):
    """多维指标雷达图：每个指标归一化到 [0,1]，外圈=更好（min 指标反转）"""
    dims = [("满足率", "satisfaction_rate", "max"), ("利用率", "spatial_utilization", "max"),
            ("平均等待", "avg_wait_time_s", "min"), ("移位次数", "shift_count", "min"),
            ("行驶距离", "total_drive_distance_m", "min")]
    labels = [d[0] for d in dims]
    norm = {}
    for name, field, direction in dims:
        vals = [m.get(field, 0) for m in all_m]
        lo, hi = min(vals), max(vals)
        norm[name] = [(0.5 if hi == lo else
                       (1 - (v - lo) / (hi - lo) if direction == "min" else (v - lo) / (hi - lo)))
                      for v in vals]
    fig = go.Figure()
    for idx, m in enumerate(all_m):
        nm = STRATEGY_LABELS.get(m["strategy"], m["strategy"])
        vals = [norm[d[0]][idx] for d in dims]
        fig.add_trace(go.Scatterpolar(r=vals + [vals[0]], theta=labels + [labels[0]],
                                      name=nm, fill="toself", opacity=0.45))
    fig.update_layout(height=420, margin=dict(l=50, r=50, t=50, b=50),
                      legend=dict(orientation="h", yanchor="bottom", y=-0.15),
                      polar=dict(radialaxis=dict(range=[0, 1], showticklabels=False)))
    return fig


def save_demand_to_project(vehicles, seed=None, source="generated",
                           generator_params=None, generated_at=None,
                           prefix="demand") -> Path:
    """一键保存到项目 data/demand_exports/（自动时间戳命名防覆盖），返回保存路径。"""
    DEMAND_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = DEMAND_EXPORT_DIR / f"{prefix}_{source}_{stamp}.json"
    text = export_demand_json(vehicles, seed=seed, source=source,
                              generator_params=generator_params,
                              generated_at=generated_at)
    path.write_text(text, encoding="utf-8")
    return path


def save_demand_to_path(vehicles, path, seed=None, source="generated",
                        generator_params=None, generated_at=None) -> Path:
    """把需求序列写到用户指定路径（父目录不存在则创建），返回实际保存路径。"""
    target = Path(path)
    if target.suffix.lower() != ".json":
        target = target.with_suffix(".json")
    target.parent.mkdir(parents=True, exist_ok=True)
    text = export_demand_json(vehicles, seed=seed, source=source,
                              generator_params=generator_params,
                              generated_at=generated_at)
    target.write_text(text, encoding="utf-8")
    return target


def is_local_desktop() -> bool:
    """是否本地桌面运行（Windows）。「下载到项目文件夹」等服务器端写文件功能仅本地有意义。"""
    return os.name == "nt"


def render_save_as_button(json_str: str, default_name: str):
    """渲染一个浏览器端「另存为…」按钮（File System Access API）。

    Chrome/Edge 且处于安全上下文（https 或 localhost）时，点击弹出系统保存对话框，
    由访问者自选保存位置，直接写入访问者电脑（类似 Word 另存为）；
    浏览器不支持或非安全上下文时，自动降级为普通浏览器下载。
    """
    import base64
    b64 = base64.b64encode(json_str.encode("utf-8")).decode("ascii")
    name_js = json.dumps(default_name)
    html = f"""
<div style="margin:2px 0;">
  <button id="saveas-btn" type="button" style="
      width:100%; padding:0.5rem 0.9rem; border:1px solid #d1d5db; border-radius:8px;
      background:#fff; color:#1e293b; font-size:0.95rem; font-weight:600; cursor:pointer;">
    💾 另存为…（自选保存位置）
  </button>
  <div id="saveas-msg" style="font-size:0.82rem; color:#64748b; margin-top:4px;"></div>
</div>
<script>
(function() {{
  const btn = document.getElementById('saveas-btn');
  const msg = document.getElementById('saveas-msg');
  const b64 = "{b64}";
  const filename = {name_js};
  function blob() {{
    return new Blob([Uint8Array.from(atob(b64), c => c.charCodeAt(0))],
                    {{type: 'application/json'}});
  }}
  function fallbackDownload() {{
    const url = URL.createObjectURL(blob());
    const a = document.createElement('a');
    a.href = url; a.download = filename; a.click();
    URL.revokeObjectURL(url);
    msg.textContent = '已开始浏览器下载（当前环境不支持另存为对话框）';
    msg.style.color = '#64748b';
  }}
  btn.addEventListener('click', async () => {{
    if (window.showSaveFilePicker) {{
      try {{
        const handle = await window.showSaveFilePicker({{
          suggestedName: filename,
          types: [{{description: 'JSON 文件',
                    accept: {{'application/json': ['.json']}}}}],
        }});
        const writable = await handle.createWritable();
        await writable.write(blob());
        await writable.close();
        msg.textContent = '✅ 已保存到你的电脑：' + handle.name;
        msg.style.color = '#16a34a';
      }} catch (e) {{
        if (e && e.name === 'AbortError') {{
          msg.textContent = '已取消保存';
          msg.style.color = '#64748b';
        }} else {{
          fallbackDownload();
        }}
      }}
    }} else {{
      fallbackDownload();
    }}
  }});
}})();
</script>
"""
    st.components.v1.html(html, height=86)


def list_demand_files() -> list[tuple[Path, str]]:
    """列出项目 data/demand_exports/ 下的需求序列 JSON，返回 [(路径, 显示名)]，按修改时间倒序。"""
    if not DEMAND_EXPORT_DIR.exists():
        return []
    files = sorted(DEMAND_EXPORT_DIR.glob("*.json"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return [(p, f"{p.name}（{time.strftime('%Y-%m-%d %H:%M', time.localtime(p.stat().st_mtime))}）")
            for p in files]


def weighted_rank_df(all_m, weights_by_label):
    """按中文指标名权重对多策略指标做加权评分，返回 (DataFrame, 排序后的带分列表)。"""
    weights = {}
    for label, w in weights_by_label.items():
        if label in PRIORITY_METRICS:
            weights[PRIORITY_METRICS[label][0]] = w
    ranked = weighted_rank(all_m, weights)
    df = pd.DataFrame(ranked)[["rank", "strategy", "weighted_score",
                               "satisfaction_rate", "spatial_utilization",
                               "avg_wait_time_s", "shift_count", "shift_distance_m",
                               "total_drive_distance_m", "rejected_count", "runtime_s"]]
    df.columns = ["排名", "策略", "综合得分", "满足率", "利用率", "平均等待(s)",
                  "移位次数", "移位距离(m)", "行驶距离(m)", "拒绝数", "耗时(s)"]
    return df, ranked


def neutralized_metric_labels(metrics_list) -> list[str]:
    """返回被「实际意义阈值」判定为无区分度的指标中文名列表（供页面提示）。"""
    fields = below_significance_fields(metrics_list)
    labels = []
    for label, (field, _direction, _desc) in PRIORITY_METRICS.items():
        if field in fields:
            labels.append(label)
    return labels


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


def build_local_task_context(payload: dict) -> dict:
    """从本地计算任务 payload 重建仿真页面上下文。

    供「载入最近一次本地计算结果」使用：把任务的布局/需求/策略/引擎参数
    与结果一起恢复，使指标分析、布局图、动态路径页与当时跑完直接看一致。
    返回 dict 直接交给 pages._apply_sim_state(result, ctx) 使用。
    """
    payload = payload or {}
    layout = payload.get("layout") or {}
    demand = payload.get("demand") or {}
    strategy = payload.get("strategy") or {}
    eng = payload.get("engine") or {}

    custom_layout = None
    if layout.get("source") == "custom":
        data = layout.get("custom_data") or {}
        net, spots = build_layout_from_json(data)
        name = data.get("name") or "导入布局"
        lid = str(name).lower().replace(" ", "_")
        custom_layout = {lid: {"name": name, "data": data, "net": net, "spots": spots}}
        layout_key = lid
        layout_category = "real"
        n_spots = len(spots)
        tandem_ratio = 0.0
    else:
        layout_key = layout.get("builtin_key") or "linear"
        if layout_key not in LAYOUT_BUILDERS:
            layout_key = "linear"
        n_spots = int(layout.get("n_spots", 15))
        tandem_ratio = float(layout.get("tandem_ratio", 0.5))
        net, spots = LAYOUT_BUILDERS[layout_key](n_spots, tandem_ratio)
        layout_category = "builtin"

    pe = PathEngine(net)

    base_vehicles = None
    imported_meta = None
    demand_source = "generated"
    gen = demand.get("generator") or {}
    n_vehicles = int(gen.get("total_vehicles", 0))
    if demand.get("source") in ("imported", "real_gate"):
        vehs, meta = parse_demand_json(demand.get("json_str", ""))
        base_vehicles = list(vehs)
        demand_source = ("real_gate" if (meta or {}).get("source") == "real_gate"
                         else "imported")
        imported_meta = meta or {}
        n_vehicles = len(base_vehicles)

    strategy_name = strategy.get("name") or "duration_greedy"
    strat_params = dict(strategy.get("params") or {})

    env_params = {
        "car_speed": float(eng.get("car_speed", CAR_SPEED)),
        "max_wait_time": float(eng.get("max_wait_time", MAX_WAIT_TIME)),
        "sim_duration": int(gen.get("sim_duration", int(SIM_DURATION))),
        "duration_min": int(gen.get("duration_min", int(DURATION_MIN))),
        "duration_max": int(gen.get("duration_max", int(DURATION_MAX))),
        "peak_ratio": float(gen.get("peak_ratio", PEAK_RATIO)),
        "error_ratio": float(gen.get("error_ratio", ERROR_RATIO)),
    }

    return {
        "layout": layout_key,
        "layout_category": layout_category,
        "custom_layout": custom_layout,
        "n_spots": n_spots,
        "tandem_ratio": tandem_ratio,
        "net": net,
        "spots": spots,
        "pe": pe,
        "strategy_name": strategy_name,
        "strat_params": strat_params,
        "env_params": env_params,
        "wait_policy": eng.get("wait_policy") or "fifo",
        "seed": int(eng.get("seed", 42)),
        "n_runs": int(eng.get("n_runs", 1)),
        "random_reps": int(eng.get("random_reps", 100)),
        "base_vehicles": base_vehicles,
        "demand_source": demand_source,
        "imported_meta": imported_meta,
        "n_vehicles": n_vehicles,
    }

# ═══════════════════════════════════════════════════════════
# 认证 & 登录
# ═══════════════════════════════════════════════════════════
def _load_priority_preference():
    """登录/恢复会话后，从 Supabase 加载用户的算法优先级设置"""
    token = st.session_state.get("token")
    if not token:
        return
    try:
        val = auth_get_pref(token, "algorithm_priority")
        if val:
            order = json.loads(val)
            order = [n for n in order if n in PRIORITY_METRICS]
            # 补充缺失的指标（按默认顺序追加），兼容旧版本保存的配置
            for n in DEFAULT_PRIORITY:
                if n not in order:
                    order.append(n)
            if order:
                st.session_state.priority_order = order
    except Exception:
        pass


def _load_run_history():
    """登录/恢复会话后，从 Supabase 加载用户的调参历史（每策略最近5次）"""
    token = st.session_state.get("token")
    if not token:
        return
    try:
        val = auth_get_pref(token, "run_history")
        if val:
            history = json.loads(val)
            if isinstance(history, dict):
                st.session_state.run_history = history
    except Exception:
        pass


LAST_PARAMS_PREF_KEY = "last_params_v1"


def _load_last_params():
    """登录/恢复会话后，从 Supabase 加载各策略最近一次使用的参数（用于回填控件）。"""
    token = st.session_state.get("token")
    if not token:
        return
    try:
        val = auth_get_pref(token, LAST_PARAMS_PREF_KEY)
        if val:
            last = json.loads(val)
            if isinstance(last, dict):
                st.session_state.last_params = {
                    k: v for k, v in last.items() if isinstance(v, dict)}
    except Exception:
        pass


def persist_last_params(strategy_name: str, params: dict):
    """保存某策略最近一次使用的参数（内存 + Supabase 用户偏好），reboot 后回填控件。"""
    last = st.session_state.setdefault("last_params", {})
    last[strategy_name] = dict(params or {})
    token = st.session_state.get("token")
    if not token:
        return
    try:
        auth_set_pref(token, LAST_PARAMS_PREF_KEY,
                      json.dumps(last, ensure_ascii=False))
    except Exception:
        pass


# 计算位置偏好：cloud = 云端 CPU；local = 本机 worker（云 UI + 本地算力）
COMPUTE_MODE_PREF_KEY = "compute_mode_v1"
COMPUTE_MODE_CLOUD = "cloud"
COMPUTE_MODE_LOCAL = "local"


def load_compute_mode():
    """登录/恢复会话后，从 Supabase 读取计算位置偏好（cloud / local）。"""
    mode = COMPUTE_MODE_CLOUD
    token = st.session_state.get("token")
    if token:
        try:
            val = auth_get_pref(token, COMPUTE_MODE_PREF_KEY)
            if val == COMPUTE_MODE_LOCAL:
                mode = COMPUTE_MODE_LOCAL
        except Exception:
            pass
    st.session_state.compute_mode = mode


def persist_compute_mode(mode: str):
    """保存计算位置偏好（内存 + Supabase 用户偏好）。"""
    mode = COMPUTE_MODE_LOCAL if mode == COMPUTE_MODE_LOCAL else COMPUTE_MODE_CLOUD
    st.session_state.compute_mode = mode
    token = st.session_state.get("token")
    if not token:
        return
    try:
        auth_set_pref(token, COMPUTE_MODE_PREF_KEY, mode)
    except Exception:
        pass


def vehicles_from_dicts(items) -> list:
    """dict 列表 → Vehicle 列表（本地计算结果载入云端界面用）。"""
    out = []
    for d in items or []:
        if not isinstance(d, dict):
            continue
        out.append(Vehicle(
            vehicle_id=d.get("vehicle_id", ""),
            arrival_time=float(d.get("arrival_time", 0.0) or 0.0),
            parking_duration=float(d.get("parking_duration", 0.0) or 0.0),
            estimated_duration=float(d.get("estimated_duration",
                                          d.get("parking_duration", 0.0) or 0.0)),
            assigned_spot=d.get("assigned_spot"),
            rejected=bool(d.get("rejected", False)),
            wait_start=d.get("wait_start"),
            wait_end=d.get("wait_end"),
            entry_id=d.get("entry_id"),
            exit_id=d.get("exit_id"),
        ))
    return out


def _json_safe(obj):
    """把参数/指标转成 JSON 原生类型（防 numpy/日期等脏类型导致 Supabase 写入失败）。"""
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, (int, float, str)) or obj is None:
        return obj
    try:
        import numpy as _np
        if isinstance(obj, (_np.integer, _np.floating)):
            return obj.item()
    except Exception:
        pass
    return str(obj)


def persist_sim_run(strategy: str, params: dict, env: dict, metrics,
                    layout_key: str = None, demand_source: str = None) -> dict:
    """把一次仿真运行结果持久化到 Supabase sim_runs 表（登录用户，跨会话可查）。

    metrics 为 dict（单策略）或 list（全部对比）；同时写入一条审计日志。
    """
    token = st.session_state.get("token")
    if not token:
        return None
    payload = _json_safe(metrics)
    try:
        res = auth_save_sim_run(token, strategy, _json_safe(params or {}),
                                _json_safe(env or {}), payload,
                                layout_key, demand_source)
        try:
            auth_log_action(token, "sim_run", {
                "strategy": strategy, "layout_key": layout_key,
                "demand_source": demand_source})
        except Exception:
            pass
        return res
    except Exception:
        return None


# 自定义布局持久化（Supabase 偏好，用户级）：布局真相源为 session_state.custom_layouts，
# 全局 LAYOUT_BUILDERS/LAYOUTS 仅作为渲染时的镜像，避免"进程残留但删不掉"。
CUSTOM_LAYOUTS_PREF_KEY = "custom_layouts_v1"


def _sync_custom_layouts_to_globals():
    """以 session_state.custom_layouts 为真相源，重建全局字典中的自定义布局项。"""
    customs = st.session_state.get("custom_layouts", {}) or {}
    for k in [k for k in LAYOUT_BUILDERS if k not in BUILTIN_LAYOUT_KEYS]:
        LAYOUT_BUILDERS.pop(k, None)
    for k in [k for k in LAYOUTS if k not in BUILTIN_LAYOUT_KEYS]:
        LAYOUTS.pop(k, None)
    for lid, linfo in customs.items():
        data = linfo.get("data")
        if not isinstance(data, dict):
            continue
        net, spots = linfo.get("net"), linfo.get("spots")
        if net is None or spots is None:
            try:
                net, spots = build_layout_from_json(data)
                linfo["net"], linfo["spots"] = net, spots
            except Exception:
                continue
        LAYOUT_BUILDERS[lid] = (lambda ns=len(spots), tr=0.0, d=data: build_layout_from_json(d))
        LAYOUTS[lid] = linfo.get("name", lid)


def _build_customs_from_items(items) -> dict:
    """把持久化的布局 items 列表转成 {lid: {name,data,net,spots}}，跳过无效项。"""
    customs = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        name = it.get("name")
        data = it.get("data")
        if not name or not isinstance(data, dict):
            continue
        lid = str(name).lower().replace(" ", "_")
        try:
            net, spots = build_layout_from_json(data)
        except Exception:
            continue
        customs[lid] = {"name": name, "data": data, "net": net, "spots": spots}
    return customs


def _load_layout_items_from_local_backup():
    """读取本地备份文件（仅桌面运行时可能存在），返回 items 列表或 None。"""
    if not is_local_desktop():
        return None
    try:
        if not LOCAL_LAYOUT_BACKUP_PATH.exists():
            return None
        items = json.loads(LOCAL_LAYOUT_BACKUP_PATH.read_text(encoding="utf-8"))
        return items if isinstance(items, list) else None
    except Exception:
        return None


def _write_local_layout_backup(items):
    """本地桌面运行时，把布局列表写一份到 data/custom_layouts_backup.json。"""
    if not is_local_desktop():
        return
    try:
        LOCAL_LAYOUT_BACKUP_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOCAL_LAYOUT_BACKUP_PATH.write_text(
            json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def restore_custom_layouts():
    """登录/恢复会话后，从 Supabase 恢复自定义布局列表（带重试，防网络抖动）。

    云端无记录但本地备份存在时（仅桌面运行时），回退本地备份并自愈回写云端。
    恢复失败时不写入 session_state.custom_layouts（保持缺失），由页面渲染时的
    ``ensure_custom_layouts_loaded()`` 自动重试，避免一次网络抖动就丢布局。
    """
    token = st.session_state.get("token")
    if not token:
        return
    customs = {}
    cloud_ok = False
    last_err = None
    for attempt in range(3):
        try:
            val = auth_get_pref(token, CUSTOM_LAYOUTS_PREF_KEY)
            if val:
                items = json.loads(val)
                if isinstance(items, list):
                    customs = _build_customs_from_items(items)
                    cloud_ok = True
            last_err = None
            break
        except Exception as e:
            last_err = str(e)
            time.sleep(0.6 * (attempt + 1))
    if not customs:
        local_items = _load_layout_items_from_local_backup()
        if local_items:
            customs = _build_customs_from_items(local_items)
    if customs:
        st.session_state.custom_layouts = customs
        st.session_state.pop("layout_restore_error", None)
        st.session_state.pop("layout_restore_retry_at", None)
        _sync_custom_layouts_to_globals()
        if not cloud_ok:
            # 云端没有记录但本地备份有：回写云端（自愈）
            persist_custom_layouts()
    else:
        # 云端和本地都没有可恢复的布局；若因异常导致，记下来供 UI 提示重试
        if last_err:
            st.session_state.layout_restore_error = last_err
            # 失败后 30 秒内不自动重试，避免每个控件交互都打一次后端
            st.session_state.layout_restore_retry_at = time.time() + 30
        _sync_custom_layouts_to_globals()


def ensure_custom_layouts_loaded():
    """页面渲染前确保自定义布局已加载。

    登录/会话恢复时若云端读取失败（网络抖动），本函数会在后续页面渲染时
    自动重试恢复（失败后 30 秒节流），避免用户看到空列表后被迫重新导入。
    """
    if "custom_layouts" not in st.session_state and st.session_state.get("token"):
        retry_at = st.session_state.get("layout_restore_retry_at", 0.0) or 0.0
        if time.time() >= retry_at:
            restore_custom_layouts()
    _sync_custom_layouts_to_globals()


def persist_custom_layouts():
    """把当前自定义布局列表保存到 Supabase（并写本地备份）。

    返回 (ok, error)：ok=False 时 UI 应提示用户云端保存失败的原因。
    """
    token = st.session_state.get("token")
    if not token:
        return False, "未登录，无法保存到云端"
    customs = st.session_state.get("custom_layouts", {}) or {}
    items = [{"name": v.get("name", lid), "data": v.get("data")}
             for lid, v in customs.items() if isinstance(v.get("data"), dict)]
    _write_local_layout_backup(items)
    try:
        res = auth_set_pref(token, CUSTOM_LAYOUTS_PREF_KEY,
                            json.dumps(items, ensure_ascii=False))
    except Exception as e:
        return False, f"云端保存异常：{e}"
    if isinstance(res, dict) and res.get("success"):
        return True, ""
    return False, (res or {}).get("error", "云端保存失败")


def clear_custom_layouts():
    """退出登录时清空当前会话的自定义布局（session_state 与全局镜像）。"""
    st.session_state.pop("custom_layouts", None)
    st.session_state.pop("layout_restore_error", None)
    st.session_state.pop("layout_restore_retry_at", None)
    for k in [k for k in LAYOUT_BUILDERS if k not in BUILTIN_LAYOUT_KEYS]:
        LAYOUT_BUILDERS.pop(k, None)
    for k in [k for k in LAYOUTS if k not in BUILTIN_LAYOUT_KEYS]:
        LAYOUTS.pop(k, None)


def check_login():
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False; st.session_state.username = None
        st.session_state.role = None; st.session_state.token = None
        st.session_state.compute_mode = COMPUTE_MODE_CLOUD
    if not st.session_state.logged_in and not st.session_state.token:
        restored = restore_session()
        if restored:
            st.session_state.logged_in = True
            st.session_state.username = restored["username"]
            st.session_state.role = restored["role"]
            st.session_state.token = restored["token"]
            _load_priority_preference()
            _load_run_history()
            _load_last_params()
            restore_custom_layouts()
            load_compute_mode()
    if "login_fails" not in st.session_state:
        st.session_state.login_fails = 0
        st.session_state.login_blocked_until = 0.0
    if not st.session_state.logged_in:
        st.markdown('<div style="text-align:center;padding:3rem 0 1rem"><div style="font-size:3rem">🚗</div>'
            '<h1 style="border:none;font-size:1.6rem!important">智能停车场优化系统</h1>'
            '<p style="color:#64748b">车位分配 · 纵深移位 · 仿真对比</p></div>', unsafe_allow_html=True)
        c1, c2, c3 = st.columns([1, 2.5, 1])
        with c2:
            if time.time() < st.session_state.login_blocked_until:
                wait = int(st.session_state.login_blocked_until - time.time()) + 1
                st.error(f"⏳ 尝试次数过多，请 {wait} 秒后再试")
                st.stop()
            tab_login, tab_register = st.tabs(["登录", "注册"])
            with tab_login:
                username = st.text_input("用户名", key="login_user").strip()
                password = st.text_input("密码", type="password", key="login_pw").strip()
                if st.button("登录", type="primary", use_container_width=True):
                    res = auth_login(username, password)
                    if res.get("success"):
                        st.session_state.logged_in = True
                        st.session_state.username = res["username"]
                        st.session_state.role = res["role"]
                        st.session_state.token = res["token"]
                        st.session_state.login_fails = 0
                        set_session_token(res["token"])
                        _load_priority_preference()
                        _load_run_history()
                        _load_last_params()
                        restore_custom_layouts()
                        load_compute_mode()
                        st.rerun()
                    else:
                        st.session_state.login_fails += 1
                        if st.session_state.login_fails >= LOGIN_MAX_FAILS:
                            st.session_state.login_blocked_until = time.time() + LOGIN_LOCK_SECONDS
                        st.error(res.get("error", "用户名或密码错误"))
            with tab_register:
                reg_user = st.text_input("新用户名", key="reg_user").strip()
                reg_pw = st.text_input("密码", type="password", key="reg_pw").strip()
                reg_pw2 = st.text_input("确认密码", type="password", key="reg_pw2").strip()
                if st.button("注册", use_container_width=True):
                    if not reg_user or not reg_pw: st.error("请填写用户名和密码")
                    elif reg_pw != reg_pw2: st.error("两次密码不一致")
                    else:
                        res = auth_register(reg_user, reg_pw)
                        if res.get("success"): st.success("注册成功！请切换到登录标签页")
                        else: st.error(res.get("error", "注册失败"))
        st.stop()

# ═══════════════════════════════════════════════════════════
# 页面渲染函数
# ═══════════════════════════════════════════════════════════
# 环境参数（引擎 + 需求生成）声明：与策略参数一样，网页渲染为可调控件
ENV_PARAM_SPECS = [
    {"key": "car_speed", "label": "车速(m/s)", "type": "float",
     "min": 0.5, "max": 5.0, "step": 0.1, "default": CAR_SPEED,
     "help": "车辆行驶速度，影响行驶/移位时间"},
    {"key": "max_wait_time", "label": "排队等待上限(秒)", "type": "int",
     "min": 60, "max": 7200, "step": 60, "default": MAX_WAIT_TIME,
     "help": "车位满时车辆排队等待的最长时间"},
    {"key": "sim_duration", "label": "仿真时长(秒)", "type": "int",
     "min": 3600, "max": 86400, "step": 600, "default": int(SIM_DURATION),
     "help": "仿真总时长（默认6小时）"},
    {"key": "duration_min", "label": "停车时长下限(秒)", "type": "int",
     "min": 60, "max": 7200, "step": 60, "default": int(DURATION_MIN),
     "help": "车辆停车时长范围下限"},
    {"key": "duration_max", "label": "停车时长上限(秒)", "type": "int",
     "min": 600, "max": 14400, "step": 300, "default": int(DURATION_MAX),
     "help": "车辆停车时长范围上限"},
    {"key": "peak_ratio", "label": "高峰车辆占比", "type": "float",
     "min": 0.0, "max": 1.0, "step": 0.05, "default": PEAK_RATIO,
     "help": "高峰时段到达的车辆占比"},
    {"key": "error_ratio", "label": "时长预估误差(±)", "type": "float",
     "min": 0.0, "max": 0.9, "step": 0.05, "default": ERROR_RATIO,
     "help": "预估停车时长相较真实时长的误差比例"},
]


def _coerce_int(value, default, lo, hi):
    """把持久化的参数值安全转成 int 并夹在 [lo, hi] 内。"""
    try:
        v = int(value)
    except (TypeError, ValueError):
        try:
            return int(default)
        except (TypeError, ValueError):
            return int(lo)
    return max(int(lo), min(int(hi), v))


def _coerce_float(value, default, lo, hi):
    """把持久化的参数值安全转成 float 并夹在 [lo, hi] 内。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        try:
            return float(default)
        except (TypeError, ValueError):
            return float(lo)
    return max(float(lo), min(float(hi), v))


def _render_param_widget(p, prefix, disabled, initial=None):
    """按单个参数声明渲染控件，返回参数值。prefix 用于生成唯一 widget key。

    p 里可带 "locked": True —— 该参数由系统自动判定/绑定，渲染为灰色不可调
    （如 MOSA 的场景模式由车位数/车辆数/时间自动判定）。

    initial: 可选 {key: value}，优先作为控件初始值（用于 reboot 后回填上次参数）。
    """
    key = p["key"]
    label = p.get("label", key)
    help_text = p.get("help")
    ptype = p.get("type", "float")
    default = p.get("default")
    dis = disabled or bool(p.get("locked", False))
    wkey = f"{prefix}_{key}"
    initial = initial or {}
    if ptype == "int":
        lo, hi = int(p.get("min", 0)), int(p.get("max", 100))
        init_val = _coerce_int(initial.get(key), default, lo, hi)
        return st.slider(label, lo, hi, init_val,
                         int(p.get("step", 1)), key=wkey, disabled=dis, help=help_text)
    if ptype == "float":
        lo, hi = float(p.get("min", 0.0)), float(p.get("max", 1.0))
        init_val = _coerce_float(initial.get(key), default, lo, hi)
        return st.slider(label, lo, hi, init_val,
                         float(p.get("step", 0.1)), key=wkey, disabled=dis, help=help_text)
    if ptype == "choice":
        options = p.get("options", [])
        opts = [o[0] for o in options] if options else []
        fmt = {o[0]: o[1] for o in options} if options else {}
        iv = initial.get(key)
        idx = opts.index(iv) if iv in opts else (opts.index(default) if default in opts else 0)
        return st.selectbox(label, opts, index=idx, format_func=lambda v: fmt.get(v, v),
                            key=wkey, disabled=dis, help=help_text)
    if ptype == "bool":
        iv = initial.get(key)
        val = iv if isinstance(iv, bool) else bool(default)
        return st.checkbox(label, val, key=wkey, disabled=dis, help=help_text)
    if ptype == "strategy":
        names = list(StrategyRegistry.all().keys())
        fmt = {n: StrategyRegistry.get(n).label for n in names}
        iv = initial.get(key)
        idx = names.index(iv) if iv in names else (names.index(default) if default in names else 0)
        return st.selectbox(label, names, index=idx, format_func=lambda v: fmt.get(v, v),
                            key=wkey, disabled=dis, help=help_text)
    return None


def render_strategy_params(strategy_name, disabled=False, initial=None):
    """渲染某策略的全部参数控件，返回 {key: value}。initial 用于回填上次参数。"""
    params = {}
    for p in StrategyRegistry.specs(strategy_name):
        params[p["key"]] = _render_param_widget(p, f"sp_{strategy_name}", disabled,
                                                initial=initial)
    return params


# 导入需求序列后不再起作用的「需求生成」环境参数（导入模式将变灰）
DEMAND_GEN_ENV_KEYS = {"sim_duration", "duration_min", "duration_max",
                       "peak_ratio", "error_ratio"}


def render_env_params(disabled=False, disabled_keys=None):
    """渲染环境参数（引擎 + 需求）控件，返回 {key: value}。

    disabled_keys: 需要额外禁用的参数 key 集合（如导入需求序列后，需求生成参数变灰）。
    """
    params = {}
    for p in ENV_PARAM_SPECS:
        key = p["key"]
        dis = disabled or (disabled_keys is not None and key in disabled_keys)
        params[key] = _render_param_widget(p, "env", dis)
    return params


