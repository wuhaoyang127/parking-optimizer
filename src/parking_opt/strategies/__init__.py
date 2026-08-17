"""策略包：统一注册表 + 内置策略（融合算法示例在 fusion.py）。"""

from .baselines import BaseStrategy, FCFS, NearestPath, RandomAssign
from .greedy import GreedyStrategy, DepartureOrderGreedy, DurationAwareGreedy
from .registry import StrategyRegistry

# 登记内置策略（新增算法在此追加一行登记即可）
StrategyRegistry.register(FCFS)
StrategyRegistry.register(NearestPath)
StrategyRegistry.register(RandomAssign)
StrategyRegistry.register(GreedyStrategy)
StrategyRegistry.register(DepartureOrderGreedy)
StrategyRegistry.register(DurationAwareGreedy)

__all__ = [
    "BaseStrategy", "FCFS", "NearestPath", "RandomAssign",
    "GreedyStrategy", "DepartureOrderGreedy", "DurationAwareGreedy",
    "StrategyRegistry",
]
