from __future__ import annotations
"""融合算法接口与示例：组合多个子算法，按规则融合（供同事参考接入方式）。"""

from .baselines import BaseStrategy
from .registry import StrategyRegistry


class CompositeStrategy(BaseStrategy):
    """融合策略基类：提供「按算法名实例化子算法」的工具方法。

    融合算法继承本类后，在 assign 里通过 self._sub(name) 拿到子算法实例，
    再按自己的融合逻辑（时段切换 / 权重混合 / 概率选择）决定最终分配。

    子算法名必须是已登记到 StrategyRegistry 的算法 name。
    """

    def _sub(self, name: str):
        """按算法名实例化子算法（使用默认参数）。"""
        return StrategyRegistry.create(name)

    def _sub_with(self, name: str, **params):
        """按算法名 + 自定义参数实例化子算法。"""
        return StrategyRegistry.create(name, **params)


class PeakOffPeakFusion(CompositeStrategy):
    """高峰贪心 + 低谷最近（时段切换式融合，示例）。

    融合逻辑：按当前占用率判断高峰/低谷——
      占用率 >= peak_threshold 视为高峰，用 peak_strategy；否则用 offpeak_strategy。

    这里的 peak_threshold 就是「融合比例」：比例越高，越难进入高峰算法。
    同事可按需参考本类，改成权重混合或概率选择等其他融合语义。
    """

    name = "peak_offpeak_fusion"
    label = "高峰贪心+低谷最近（融合示例）"
    DESCRIPTION = ("**高峰贪心+低谷最近（融合示例）**\n\n按当前占用率判断高峰/低谷：占用率高于阈值用高峰算法"
                   "（默认时长感知贪心），否则用低谷算法（默认最近路径）。阈值即「融合比例」，可在下方参数区调节。")

    PARAMS = [
        {"key": "peak_strategy", "label": "高峰算法", "type": "strategy",
         "default": "duration_greedy", "help": "占用率高于阈值时使用该算法"},
        {"key": "offpeak_strategy", "label": "低谷算法", "type": "strategy",
         "default": "nearest", "help": "占用率低于阈值时使用该算法"},
        {"key": "peak_threshold", "label": "高峰判定阈值(占用率)", "type": "float",
         "min": 0.0, "max": 1.0, "step": 0.05, "default": 0.7,
         "help": "当前占用率超过该比例视为高峰（即融合比例，可调）"},
    ]

    def __init__(self, peak_strategy: str = "duration_greedy",
                 offpeak_strategy: str = "nearest", peak_threshold: float = 0.7):
        self.peak_strategy = peak_strategy
        self.offpeak_strategy = offpeak_strategy
        self.peak_threshold = peak_threshold
        # 缓存子算法实例（复用，保留有状态策略的内部状态）
        self._peak = StrategyRegistry.create(peak_strategy)
        self._offpeak = StrategyRegistry.create(offpeak_strategy)

    def assign(self, vehicle, time, parking_lot, path_engine):
        total = len(parking_lot.spots)
        occupied = sum(1 for s in parking_lot.spots.values() if s.is_occupied)
        ratio = occupied / total if total else 0.0
        if ratio >= self.peak_threshold:
            return self._peak.assign(vehicle, time, parking_lot, path_engine)
        return self._offpeak.assign(vehicle, time, parking_lot, path_engine)
