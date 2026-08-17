from __future__ import annotations
"""离散事件仿真引擎 (SimPy)"""

import random
import simpy
from .parking_lot import ParkingLot
from ..domain.spot import Vehicle, Spot, Event, EventType
from ..routing.path_engine import PathEngine


class SimulationEngine:
    """SimPy 停车仿真主循环"""

    CAR_SPEED = 1.39  # m/s (5 km/h)，默认值，可被构造参数覆盖
    MAX_WAIT_TIME = 1800  # 最大等待秒数（30分钟），默认值
    RETRY_INTERVAL = 60  # 排队等待时的重试间隔（秒）

    def __init__(self, parking_lot: ParkingLot, path_engine: PathEngine,
                 vehicles: list[Vehicle], strategy, seed: int = 42,
                 wait_policy: str = "fifo", car_speed: float = 1.39,
                 max_wait_time: float = 1800):
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

        self.events: list[Event] = []
        self.shift_count = 0
        self.total_shift_dist = 0.0
        self.waiting_queue: list[Vehicle] = []  # 排队等待中的车辆

    def _log(self, time: float, event_type: EventType, vehicle_id: str = None,
             spot_id: str = None, strategy: str = None, **metadata):
        self.events.append(Event(
            time=time, event_type=event_type,
            vehicle_id=vehicle_id, spot_id=spot_id,
            strategy=strategy, metadata=metadata
        ))

    def run(self) -> list[Event]:
        """运行仿真，返回事件日志"""
        # 调度所有车辆到达
        for v in sorted(self.vehicles, key=lambda x: x.arrival_time):
            self.env.process(self._vehicle_arrival(v))

        self.env.run()
        return self.events

    def _vehicle_arrival(self, vehicle: Vehicle):
        """车辆到达处理"""
        yield self.env.timeout(vehicle.arrival_time - self.env.now)

        self._log(self.env.now, EventType.VEHICLE_ARRIVAL, vehicle.vehicle_id)

        # 调用策略
        result = self.strategy.assign(vehicle, self.env.now,
                                      self.parking_lot, self.path_engine)
        spot, status = result

        if status == "rejected":
            vehicle.rejected = True
            self._log(self.env.now, EventType.REJECTED, vehicle.vehicle_id,
                      strategy=self.strategy.name, reason="停车场无空闲车位，无法分配")
            return

        if status == "waiting":
            # 车位满：加入等待队列（短停车优先调度），并启动超时监视
            self._log(self.env.now, EventType.WAIT_START, vehicle.vehicle_id)
            vehicle.wait_start = self.env.now
            self.waiting_queue.append(vehicle)
            self.env.process(self._wait_timeout(vehicle))
            return

        # 立即分配成功：同步占位，异步行驶入位
        self._occupy(vehicle, spot)
        self.env.process(self._drive_and_depart(vehicle, spot))

    def _occupy(self, vehicle: Vehicle, spot: Spot):
        """同步占用车位 + 记录分配事件（保证后续车不会再分到同一车位）"""
        self.parking_lot.assign(vehicle, spot)
        self._log(self.env.now, EventType.PARKING_ASSIGNED, vehicle.vehicle_id,
                  spot.spot_id, self.strategy.name)

    def _drive_and_depart(self, vehicle: Vehicle, spot: Spot):
        """异步：行驶入位、调度离场"""
        drive_dist = self.path_engine.distance_to_spot(spot.node_id)
        drive_time = drive_dist / self.car_speed
        yield self.env.timeout(drive_time)

        self._log(self.env.now, EventType.SPOT_ENTRY, vehicle.vehicle_id,
                  spot.spot_id, drive_distance=drive_dist)

        # 调度离场
        dep_time = self.env.now + vehicle.parking_duration
        self.env.process(self._vehicle_departure(vehicle, dep_time))

    def _wait_timeout(self, vehicle: Vehicle):
        """等待超时：从队列移除并拒绝"""
        yield self.env.timeout(self.max_wait_time)
        if vehicle in self.waiting_queue:
            self.waiting_queue.remove(vehicle)
            vehicle.wait_end = self.env.now
            self._log(self.env.now, EventType.WAIT_END, vehicle.vehicle_id)
            vehicle.rejected = True
            self._log(self.env.now, EventType.REJECTED, vehicle.vehicle_id,
                      reason="等待超时后仍无空闲车位，无法分配")

    def _dispatch_waiting(self):
        """车位空出后，从等待队列分配车辆；shortest 策略下短停车优先，否则 FIFO"""
        if not self.waiting_queue:
            return
        if self.wait_policy == "shortest":
            self.waiting_queue.sort(key=lambda v: getattr(v, "estimated_duration", float("inf")))
        for vehicle in list(self.waiting_queue):
            spot, status = self.strategy.assign(vehicle, self.env.now,
                                                self.parking_lot, self.path_engine)
            if status == "assigned":
                self.waiting_queue.remove(vehicle)
                vehicle.wait_end = self.env.now
                self._log(self.env.now, EventType.WAIT_END, vehicle.vehicle_id)
                # 同步占位（避免循环内后续车重复分配到同一车位），异步行驶入位
                self._occupy(vehicle, spot)
                self.env.process(self._drive_and_depart(vehicle, spot))

    def _vehicle_departure(self, vehicle: Vehicle, dep_time: float):
        """车辆离场处理（含移位）"""
        yield self.env.timeout(dep_time - self.env.now)

        spot = self.parking_lot.get_spot(vehicle.assigned_spot)
        blockers = self.parking_lot.get_blockers(spot)

        if not blockers:
            # 无阻挡，直接离场
            self.parking_lot.free(spot)
            self._log(self.env.now, EventType.DEPARTURE, vehicle.vehicle_id,
                      spot.spot_id, had_blocking=False)
            self._dispatch_waiting()  # 车位空出，调度等待队列
            return

        # 有阻挡，执行移位
        self._log(self.env.now, EventType.DEPARTURE, vehicle.vehicle_id,
                  spot.spot_id, had_blocking=True, blocker_count=len(blockers),
                  reason=f"被 {len(blockers)} 辆外侧车辆阻挡，需移位后离场")

        for blk_spot, blk_vid in blockers:
            buffer = self.parking_lot.select_buffer()
            if buffer is None:
                self._log(self.env.now, EventType.BUFFER_FAILED, blk_vid,
                          blocked_vehicle=vehicle.vehicle_id, reason="无可用缓冲位，无法移位")
                continue

            # 移位
            dist = self.path_engine.shortest_distance(blk_spot.node_id, buffer.node_id)
            travel_time = dist / self.car_speed

            self._log(self.env.now, EventType.SHIFT_START, blk_vid,
                      from_spot=blk_spot.spot_id, to_spot=buffer.spot_id,
                      blocked_vehicle=vehicle.vehicle_id, distance=dist,
                      reason=f"为让行内层车辆 {vehicle.vehicle_id} 离场而临时移位")
            self.shift_count += 1
            self.total_shift_dist += dist * 2

            yield self.env.timeout(travel_time)
            # 外层车可能在移位行驶期间已自行离场（此时无阻挡，直接让里层车离场）
            if blk_spot.occupied_by != blk_vid:
                self.parking_lot.free(spot)
                self.parking_lot.release_buffer(buffer.spot_id)
                continue
            self.parking_lot.move_vehicle(blk_spot, buffer)

            # 被阻挡车离场
            self.parking_lot.free(spot)

            # 阻挡车归位（或前移）
            yield self.env.timeout(travel_time)
            innermost = self._find_innermost_available(blk_spot)
            target = innermost if innermost else blk_spot
            self.parking_lot.move_vehicle(buffer, target)
            self.parking_lot.release_buffer(buffer.spot_id)

            self._log(self.env.now, EventType.SHIFT_END, blk_vid,
                      final_spot=target.spot_id)

        self._dispatch_waiting()  # 离场（含移位）完成，调度等待队列

    def _find_innermost_available(self, spot: Spot) -> Spot | None:
        """找纵深组中最内侧的空闲车位（用于前移归位）"""
        group = self.parking_lot.get_group_spots(spot)
        for s in reversed(group):  # 从内到外
            if not s.is_occupied:
                return s
        return None
