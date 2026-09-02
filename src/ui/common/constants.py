"""常量：策略显示名、指标定义、角色权限、全局 CSS、布局示例等。"""
from ui.common._imports import *

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
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
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
# LAYOUT_BUILDERS / LAYOUTS / BUILTIN_LAYOUT_KEYS 已从 src/local_compute.py 导入（见 _imports）

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
