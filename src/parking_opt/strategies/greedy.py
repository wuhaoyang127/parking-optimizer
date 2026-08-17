from __future__ import annotations
"""贪心策略族：朴素贪心（基线）与时长感知贪心（主方法）"""

import statistics

from ..domain.spot import Spot, Vehicle, SpotType
from ..simulation.parking_lot import ParkingLot
from .baselines import BaseStrategy


class GreedyStrategy(BaseStrategy):
    """朴素在线贪心分配（基线）：不利用停车时长信息"""

    name = "greedy"
    label = "贪心（基线）"

    def assign(self, vehicle: Vehicle, time: float, parking_lot: ParkingLot,
               path_engine) -> tuple[Spot | None, str]:
        available = parking_lot.get_available_spots()
        if not available:
            return (None, "waiting")

        # 按优先级分组
        group1 = []  # STANDALONE
        group2 = []  # TANDEM depth=1
        group3 = []  # TANDEM depth>1

        for spot in available:
            if spot.spot_type == SpotType.STANDALONE:
                group1.append(spot)
            elif spot.depth == 1:
                group2.append(spot)
            else:
                group3.append(spot)

        # 优先级1: 独立车位 → 选最近
        if group1:
            best = min(group1, key=lambda s: path_engine.distance_to_spot(s.node_id))
            return (best, "assigned")

        # 优先级2: depth=1 纵深车位 → 选最近
        if group2:
            best = min(group2, key=lambda s: path_engine.distance_to_spot(s.node_id))
            return (best, "assigned")

        # 优先级3: depth>1 → 选内侧车预计离场最早的
        if group3:
            best = min(group3, key=lambda s: self._inner_estimated_departure(s, parking_lot))
            return (best, "assigned")

        return (None, "waiting")

    def _inner_estimated_departure(self, spot: Spot, parking_lot: ParkingLot) -> float:
        """返回该车位内侧阻挡车的预计离场时间"""
        outer_spots = parking_lot.get_outer_spots(spot)
        max_dep = 0.0
        for outer in outer_spots:
            if outer.is_occupied and outer.occupied_by:
                v = parking_lot.vehicles.get(outer.occupied_by)
                if v:
                    est_dep = v.arrival_time + v.estimated_duration
                    if est_dep > max_dep:
                        max_dep = est_dep
        return max_dep


class DepartureOrderGreedy(BaseStrategy):
    """离场顺序贪心基线：最近可用，若选depth>1则选内侧最早离场的"""

    name = "departure_greedy"
    label = "离场贪心"

    def assign(self, vehicle, time, parking_lot, path_engine):
        available = parking_lot.get_available_spots()
        if not available:
            return (None, "waiting")

        # 选最近可用 (忽略阻挡风险)
        best = min(available, key=lambda s: path_engine.distance_to_spot(s.node_id))
        return (best, "assigned")


class DurationAwareGreedy(BaseStrategy):
    """时长感知贪心：利用预估停车时长安排纵深车位内外层，减少移位（连续评分）

    核心思想：纵深车位里，depth=1（外层）的车若先离场则不挡 depth>1（里层）的车。
    因此：短停（早走）→ 优先外层；长停（晚走）→ 优先里层。

    连续评分（区别于固定阈值二分）：
      - 分界阈值自适应：取"已见车辆预估停车时长"的中位数，随场景自动调整，无需人工标定；
      - 里层车位选择：按"外侧阻挡车预计离场时间"连续排序（越早越好）。
    """

    name = "duration_greedy"
    label = "时长感知贪心（主方法）"

    DEFAULT_THRESHOLD = 3600.0  # 自适应前的默认阈值（1小时）
    WARMUP = 10  # 自适应所需的最少样本数

    PARAMS = [
        {"key": "threshold", "label": "时长阈值(秒)", "type": "float",
         "min": 600.0, "max": 7200.0, "step": 300.0, "default": 3600.0,
         "help": "停车时长低于该值优先分外层车位；样本不足时作为固定阈值"},
        {"key": "warmup", "label": "自适应样本数", "type": "int",
         "min": 1, "max": 100, "step": 1, "default": 10,
         "help": "累计多少辆车的预估时长后，改用中位数自适应阈值"},
    ]

    def __init__(self, threshold: float = 3600.0, warmup: int = 10):
        self.threshold = threshold
        self.warmup = warmup
        self._seen_durations = []

    def assign(self, vehicle, time, parking_lot, path_engine):
        available = parking_lot.get_available_spots()
        if not available:
            return (None, "waiting")

        standalone = [s for s in available if s.spot_type == SpotType.STANDALONE]
        depth1 = [s for s in available if s.spot_type == SpotType.TANDEM and s.depth == 1]
        depth_n = [s for s in available if s.spot_type == SpotType.TANDEM and s.depth > 1]

        # 1. 独立车位优先（无阻挡问题），选最近
        if standalone:
            best = min(standalone, key=lambda s: path_engine.distance_to_spot(s.node_id))
            return (best, "assigned")

        # 2. 纵深车位：按预估停车时长连续分流
        est_dur = max(vehicle.estimated_duration, 0.0)
        self._seen_durations.append(est_dur)
        threshold = self._adaptive_threshold()

        if depth1 and depth_n:
            # 内外层都有空闲：短停→外层、长停→里层
            if est_dur < threshold:
                best = min(depth1, key=lambda s: path_engine.distance_to_spot(s.node_id))
                return (best, "assigned")
            else:
                best = min(depth_n, key=lambda s: self._inner_estimated_departure(s, parking_lot))
                return (best, "assigned")

        # 只剩一层：直接选
        if depth1:
            best = min(depth1, key=lambda s: path_engine.distance_to_spot(s.node_id))
            return (best, "assigned")
        if depth_n:
            best = min(depth_n, key=lambda s: self._inner_estimated_departure(s, parking_lot))
            return (best, "assigned")

        return (None, "waiting")

    def _adaptive_threshold(self) -> float:
        """自适应阈值：已见车辆预估时长的中位数（样本足够时），否则用默认值"""
        if len(self._seen_durations) >= self.warmup:
            return statistics.median(self._seen_durations)
        return self.threshold

    def _inner_estimated_departure(self, spot, parking_lot) -> float:
        """返回该里层车位外侧阻挡车的预计离场时间（越早越好）"""
        max_dep = 0.0
        for outer in parking_lot.get_outer_spots(spot):
            if outer.is_occupied and outer.occupied_by:
                v = parking_lot.vehicles.get(outer.occupied_by)
                if v:
                    est_dep = v.arrival_time + v.estimated_duration
                    if est_dep > max_dep:
                        max_dep = est_dep
        return max_dep
