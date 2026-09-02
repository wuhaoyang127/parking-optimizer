from __future__ import annotations
"""MOSA 常量：时间熔断、场景权重、拒绝惩罚。"""

# 时间熔断（非规模保护）：任何规模都会运行 NSGA-II，
# 但单次 prepare 超过该秒数后停止进化、返回当前种群中的最优方案，避免网页卡死。
# 注意：需小于页面层每个种子 60 秒的时限（ui/common.py STRATEGY_TIME_BUDGET），
# 给仿真执行留出时间。
PREPARE_TIME_BUDGET = 45.0

# 场景权重（f1 时间 / f2 距离 / f3 利用率均衡）
SCENE_WEIGHTS = {
    "peak": {"f1": 0.6, "f2": 0.2, "f3": 0.2},
    "normal": {"f1": 0.2, "f2": 0.6, "f3": 0.2},
    "saturated": {"f1": 0.2, "f2": 0.2, "f3": 0.6},
}

SCENE_LABELS = {
    "peak": "高峰（重时间）",
    "normal": "平峰（重距离）",
    "saturated": "饱和（重利用率）",
}

REJECT_PENALTY = 1000.0  # 拒绝一辆车的惩罚（加到 f1/f2，与原算法 mosa_full.py 一致）
