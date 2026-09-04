"""策略包：统一注册表 + 内置策略 + 融合算法示例。"""

from .baselines import BaseStrategy, FCFS, NearestPath, RandomAssign
from .greedy import GreedyStrategy, DepartureOrderGreedy, DurationAwareGreedy
from .registry import StrategyRegistry
from .fusion import CompositeStrategy, PeakOffPeakFusion
from .mosa import MosaStrategy
from .risk_scoring import RiskScoringStrategy
from .rho import RhoRollingStrategy

# 登记内置策略（新增算法在此追加一行登记即可）
StrategyRegistry.register(FCFS)
StrategyRegistry.register(NearestPath)
StrategyRegistry.register(RandomAssign)
StrategyRegistry.register(GreedyStrategy)
StrategyRegistry.register(DepartureOrderGreedy)
StrategyRegistry.register(DurationAwareGreedy)
StrategyRegistry.register(PeakOffPeakFusion)
StrategyRegistry.register(MosaStrategy)
StrategyRegistry.register(RiskScoringStrategy)
StrategyRegistry.register(RhoRollingStrategy)

__all__ = [
    "BaseStrategy", "FCFS", "NearestPath", "RandomAssign",
    "GreedyStrategy", "DepartureOrderGreedy", "DurationAwareGreedy",
    "CompositeStrategy", "PeakOffPeakFusion", "MosaStrategy",
    "RiskScoringStrategy", "RhoRollingStrategy", "StrategyRegistry",
]
