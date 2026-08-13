from __future__ import annotations
"""简单分配策略：FCFS / 最近路径 / 随机"""

import random
from ..domain.spot import Spot, Vehicle
from ..simulation.parking_lot import ParkingLot


class BaseStrategy:
    """策略基类"""
    name: str = "base"

    def assign(self, vehicle: Vehicle, time: float, parking_lot: ParkingLot,
               path_engine) -> tuple[Spot | None, str]:
        raise NotImplementedError


class FCFS(BaseStrategy):
    """先到先服务：最近可用独立或depth=1车位"""
    name = "fcfs"

    def assign(self, vehicle, time, parking_lot, path_engine):
        available = parking_lot.get_available_spots()
        if not available:
            return (None, "waiting")
        # 选第一个可用的
        for spot in available:
            if spot.depth == 1:
                return (spot, "assigned")
        return (available[0], "assigned")  # fallback


class NearestPath(BaseStrategy):
    """最近路径分配：选距离入口最近的车位"""
    name = "nearest"

    def assign(self, vehicle, time, parking_lot, path_engine):
        available = parking_lot.get_available_spots()
        if not available:
            return (None, "waiting")
        best = min(available, key=lambda s: path_engine.distance_to_spot(s.node_id))
        return (best, "assigned")


class RandomAssign(BaseStrategy):
    """随机分配"""
    name = "random"

    def assign(self, vehicle, time, parking_lot, path_engine):
        available = parking_lot.get_available_spots()
        if not available:
            return (None, "waiting")
        return (random.choice(available), "assigned")
