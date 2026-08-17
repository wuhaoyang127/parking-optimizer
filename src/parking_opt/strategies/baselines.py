from __future__ import annotations
"""简单分配策略：FCFS / 最近路径 / 随机"""

import random
from ..domain.spot import Spot, Vehicle
from ..simulation.parking_lot import ParkingLot


class BaseStrategy:
    """策略基类

    新算法接入约定（详见 docs/新算法接入说明.md）：
      - 继承本类，设置 name（英文唯一标识）、label（网页显示名）；
      - 用 PARAMS 列表声明可调参数，每项含 key/label/type/min/max/step/default/help；
      - 构造函数接收与 PARAMS 中 key 同名的关键字参数（带默认值）；
      - 在 strategies/__init__.py 的注册表中登记后，网页会自动出现参数控件。

    参数 type 支持：int / float / choice / bool。
      - int/float：网页渲染为滑块或数字输入（用 min/max/step 控制）；
      - choice：网页渲染为下拉框，需提供 options=[(value, label), ...]；
      - bool：网页渲染为开关。
    """

    name: str = "base"
    label: str = "基础策略"
    PARAMS: list = []  # 可调参数声明，见类文档字符串

    def assign(self, vehicle: Vehicle, time: float, parking_lot: ParkingLot,
               path_engine) -> tuple[Spot | None, str]:
        raise NotImplementedError


class FCFS(BaseStrategy):
    """先到先服务：最近可用独立或depth=1车位"""
    name = "fcfs"
    label = "先到先服务"

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
    label = "最近路径"

    def assign(self, vehicle, time, parking_lot, path_engine):
        available = parking_lot.get_available_spots()
        if not available:
            return (None, "waiting")
        best = min(available, key=lambda s: path_engine.distance_to_spot(s.node_id))
        return (best, "assigned")


class RandomAssign(BaseStrategy):
    """随机分配"""
    name = "random"
    label = "随机分配"

    def assign(self, vehicle, time, parking_lot, path_engine):
        available = parking_lot.get_available_spots()
        if not available:
            return (None, "waiting")
        return (random.choice(available), "assigned")
