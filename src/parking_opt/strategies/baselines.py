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

    参数 type 支持：int / float / choice / bool / strategy。
      - int/float：网页渲染为滑块或数字输入（用 min/max/step 控制）；
      - choice：网页渲染为下拉框，需提供 options=[(value, label), ...]；
      - bool：网页渲染为开关；
      - strategy：网页渲染为「已登记算法」下拉框（选项来自 StrategyRegistry），
        用于融合算法选择子算法，default 为某个已登记算法 name。
    """

    name: str = "base"
    label: str = "基础策略"
    PARAMS: list = []  # 可调参数声明，见类文档字符串
    DESCRIPTION: str = ""  # 算法说明（Markdown），网页仿真设置页自动展示

    def prepare(self, vehicles: list[Vehicle], parking_lot: ParkingLot,
                path_engine) -> None:
        """仿真开始前的准备钩子（默认空实现，在线策略无需重写）。

        离线全信息算法（如 MOSA/CP-SAT 类预分配）可重写本方法：在仿真运行前
        一次性拿到完整需求序列，做全局优化并把结果缓存到实例上；随后 assign
        只做「查表执行」。引擎在 run() 开头自动调用（若策略实现了本方法）。

        注意：本方法可读完整需求（含未来到达），属离线信息；因此离线预分配
        策略必须明确标注为「离线全信息对照基准」，与在线策略分开比较。
        """
        return None

    def assign(self, vehicle: Vehicle, time: float, parking_lot: ParkingLot,
               path_engine) -> tuple[Spot | None, str]:
        raise NotImplementedError


class FCFS(BaseStrategy):
    """先到先服务：最近可用独立或depth=1车位"""
    name = "fcfs"
    label = "先到先服务"
    DESCRIPTION = "**先到先服务**\n\n按车位出现的顺序，选第一个可用的空闲车位。"

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
    DESCRIPTION = "**最近路径**\n\n选距离入口最近的空闲车位，不考虑纵深阻挡风险。"

    def assign(self, vehicle, time, parking_lot, path_engine):
        available = parking_lot.get_available_spots()
        if not available:
            return (None, "waiting")
        entry = getattr(vehicle, "entry_id", None)  # 多入口：按该车入口计距离
        best = min(available, key=lambda s: path_engine.distance_to_spot(s.node_id, entry))
        return (best, "assigned")


class RandomAssign(BaseStrategy):
    """随机分配"""
    name = "random"
    label = "随机分配"
    DESCRIPTION = "**随机分配**\n\n从当前空闲车位中随机选一个（基线对照用）。"

    def assign(self, vehicle, time, parking_lot, path_engine):
        available = parking_lot.get_available_spots()
        if not available:
            return (None, "waiting")
        return (random.choice(available), "assigned")
