from __future__ import annotations
"""在线贪心策略：主方法"""

from ..domain.spot import Spot, Vehicle, SpotType
from ..simulation.parking_lot import ParkingLot
from .baselines import BaseStrategy


class GreedyStrategy(BaseStrategy):
    """在线贪心分配 + 动态缓冲位"""

    name = "greedy"

    def assign(self, vehicle: Vehicle, time: float, parking_lot: ParkingLot,
               path_engine) -> tuple[Spot | None, str]:
        available = parking_lot.get_available_spots()
        if not available:
            return (None, "rejected")

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

        return (None, "rejected")

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
            return (None, "rejected")

        # 选最近可用 (忽略阻挡风险)
        best = min(available, key=lambda s: path_engine.distance_to_spot(s.node_id))
        return (best, "assigned")
