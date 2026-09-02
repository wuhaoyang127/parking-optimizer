"""viz 包：颜色方案与基础尺寸。"""


# ─── 颜色方案 ───
ROAD_COLOR_MAIN = "#78909C"; ROAD_COLOR_SPUR = "#B0BEC5"
ENTRY_COLOR = "#2E7D32"
EXIT_COLOR = "#C62828"
SPOT_FREE = "#66BB6A"; SPOT_OCCUPIED = "#EF5350"; SPOT_BLOCKED = "#FF9800"
VEHICLE_COLOR = "#2196F3"; HIGHLIGHT_VEHICLE = "#E91E63"; HIGHLIGHT_PATH = "#FFEB3B"
BG_COLOR = "#FAFBFC"

# ─── 基础尺寸（scale=1 时）───
BASE = {
    "spot": 10, "tandem": 8, "spot_text": 7,
    "entry": 16, "entry_text": 9,
    "veh": 12, "veh_hl": 18, "veh_text": 8,
    "road_main": 3, "road_spur": 1.5,
    "path_w": 4, "path_marker": 6,
    "rnode": 5, "rnode_text": 7,
}


def _s(key: str, scale: float) -> float:
    """缩放尺寸"""
    return BASE[key] * scale


# 显式 __all__：让 `from viz.colors import *` 也能携带 _ 前缀内部名
__all__ = [n for n in globals() if not n.startswith("_")] + ["_s"]
