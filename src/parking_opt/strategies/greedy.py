from __future__ import annotations
"""贪心策略族：朴素贪心（基线）与时长感知贪心（主方法）"""

from ..domain.spot import Spot, Vehicle, SpotType
from ..simulation.parking_lot import ParkingLot
from .baselines import BaseStrategy


class GreedyStrategy(BaseStrategy):
    """朴素在线贪心分配（基线）：不利用停车时长信息"""

    name = "greedy"

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

    def assign(self, vehicle, time, parking_lot, path_engine):
        available = parking_lot.get_available_spots()
        if not available:
            return (None, "waiting")

        # 选最近可用 (忽略阻挡风险)
        best = min(available, key=lambda s: path_engine.distance_to_spot(s.node_id))
        return (best, "assigned")


class DurationAwareGreedy(BaseStrategy):
    """时长感知贪心：利用预估停车时长安排纵深车位内外层，减少移位

    核心思想：纵深车位里，depth=1（外层）的车若先离场则不挡 depth>1（里层）的车。
    因此：
      - 预估停车时长短（会早走）→ 优先放外层 depth=1
      - 预估停车时长长（会晚走）→ 优先放里层 depth>1
    这样外层车先走、里层车后走，避免"里层车要出、外层车挡着"导致的移位。
    """

    name = "duration_greedy"

    # 停车时长阈值(s)：低于此值视为"短停"，优先放外层。取停车时长范围中位数附近。
    DURATION_THRESHOLD = 12000.0

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

        # 2. 根据预估停车时长决定纵深车位内外层
        remaining = max(vehicle.estimated_duration, 0.0)

        if remaining < self.DURATION_THRESHOLD:
            # 短停：优先外层 depth=1，避免挡住里层
            if depth1:
                best = min(depth1, key=lambda s: path_engine.distance_to_spot(s.node_id))
                return (best, "assigned")
            if depth_n:
                best = min(depth_n, key=lambda s: self._inner_estimated_departure(s, parking_lot))
                return (best, "assigned")
        else:
            # 长停：优先里层 depth>1，把外层留给短停车
            if depth_n:
                best = min(depth_n, key=lambda s: self._inner_estimated_departure(s, parking_lot))
                return (best, "assigned")
            if depth1:
                best = min(depth1, key=lambda s: path_engine.distance_to_spot(s.node_id))
                return (best, "assigned")

        return (None, "waiting")

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
