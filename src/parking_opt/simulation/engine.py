from __future__ import annotations
"""离散事件仿真引擎 (SimPy)

- 时间片路口碰撞检测：所有车辆运动（入库/离场/移位）按有向边生成时间片，
  同一边上时间片不重叠（EDGE_GAP 间隔），冲突时等待推进（硬约束）。
- 场景 A 离场让行：里层车离场被外层车阻挡时，外层车移位让行 → 里层车离场 → 外层车回位。
- 场景 B 入库让行：新车停里层车位被外层车阻挡时，外层车移位让行 → 新车停入 → 外层车回位。
"""

import random
import simpy

from .parking_lot import ParkingLot
from ..domain.spot import Event, EventType
from ..routing.path_engine import PathEngine
from .defaults import CAR_SPEED as DEFAULT_CAR_SPEED, MAX_WAIT_TIME as DEFAULT_MAX_WAIT
from ._timeslice import TimeSliceMixin, TimeSlice  # noqa: F401（TimeSlice 供测试/调试导入）
from ._arrival import ArrivalMixin
from ._departure import DepartureMixin


class SimulationEngine(ArrivalMixin, DepartureMixin, TimeSliceMixin):
    """SimPy 停车仿真主循环（含时间片碰撞检测与双向移位让行）"""

    CAR_SPEED = DEFAULT_CAR_SPEED  # m/s (5 km/h)，默认值，可被构造参数覆盖
    MAX_WAIT_TIME = DEFAULT_MAX_WAIT  # 最大等待秒数（30分钟），默认值
    RETRY_INTERVAL = 60  # 排队等待时的重试间隔（秒）
    EDGE_GAP = 2.0  # 路口碰撞 GAP 间隔（秒）：同一边相邻时间片的最小间隔
    MAX_SLICE_ITER = 500  # 时间片冲突等待的最大推进次数（防御）

    def __init__(self, parking_lot: ParkingLot, path_engine: PathEngine,
                 vehicles: list, strategy, seed: int = 42,
                 wait_policy: str = "fifo", car_speed: float = DEFAULT_CAR_SPEED,
                 max_wait_time: float = DEFAULT_MAX_WAIT,
                 buffer_w_distance: float = 1.0, buffer_w_idle: float = 1.0,
                 buffer_w_secondary: float = 2.0, buffer_idle_half_life: float = 300.0):
        self.env = simpy.Environment()
        self.parking_lot = parking_lot
        self.path_engine = path_engine
        self.vehicles = vehicles
        self.strategy = strategy  # 策略对象 (需有 .assign(vehicle, time, parking_lot, path_engine) 方法)
        self.seed = seed
        random.seed(seed)
        # 等待调度策略：fifo=先到先服务（默认，保留策略差异）；shortest=短停车优先（引擎优化强）
        self.wait_policy = wait_policy
        self.car_speed = car_speed  # 车速（m/s）
        self.max_wait_time = max_wait_time  # 排队等待上限（秒）
        # 缓冲位评分选位权重与空闲时间半衰（C = w_d·D̂ + w_t·T̂ + w_q·Q̂）
        self.buffer_w_distance = buffer_w_distance
        self.buffer_w_idle = buffer_w_idle
        self.buffer_w_secondary = buffer_w_secondary
        self.buffer_idle_half_life = buffer_idle_half_life

        self.events: list[Event] = []
        self.shift_count = 0
        self.total_shift_dist = 0.0
        self.waiting_queue: list = []  # 排队等待中的车辆
        self.time_slices: list = []  # 全部车辆运动时间片（路口碰撞检测）
        self._shift_level: dict[str, int] = {}  # 车辆当前移位层级（1=首次移位，2=二次移位）

    # ========== 事件与基础 ==========

    def _select_buffer(self, from_spot):
        """按评分标准选择缓冲位：距离 + 空闲时间 + 二次移位惩罚（越小越好）。"""
        return self.parking_lot.select_buffer_scored(
            from_spot, self.path_engine, self.env.now,
            waiting_len=len(self.waiting_queue),
            w_d=self.buffer_w_distance, w_t=self.buffer_w_idle,
            w_q=self.buffer_w_secondary, tau=self.buffer_idle_half_life)

    def _next_shift_level(self, vehicle_id: str) -> int:
        """计算该车本次移位的层级（1=首次移位，2=二次移位……）。"""
        return self._shift_level.get(vehicle_id, 0) + 1

    def _commit_shift_level(self, vehicle_id: str, level: int):
        """移位成功后记录该车当前层级。"""
        self._shift_level[vehicle_id] = level

    def _rollback_shift_level(self, vehicle_id: str, level: int):
        """移位失败/放弃：回退到本次尝试前的层级。"""
        self._shift_level[vehicle_id] = max(0, level - 1)

    def _clear_shift_level(self, vehicle_id: str):
        """回位/离场后清除层级。"""
        self._shift_level[vehicle_id] = 0

    def _log(self, time: float, event_type: EventType, vehicle_id: str = None,
             spot_id: str = None, strategy: str = None, **metadata):
        self.events.append(Event(
            time=time, event_type=event_type,
            vehicle_id=vehicle_id, spot_id=spot_id,
            strategy=strategy, metadata=metadata
        ))

    def run(self) -> list[Event]:
        """运行仿真，返回事件日志"""
        # 离线预分配钩子：策略若实现了 prepare（如 MOSA），在仿真开始前
        # 一次性拿到完整需求做全局优化；在线策略未实现该方法时自动跳过。
        prepare = getattr(self.strategy, "prepare", None)
        if callable(prepare):
            prepare(self.vehicles, self.parking_lot, self.path_engine)

        # 调度所有车辆到达
        for v in sorted(self.vehicles, key=lambda x: x.arrival_time):
            self.env.process(self._vehicle_arrival(v))

        self.env.run()
        return self.events
