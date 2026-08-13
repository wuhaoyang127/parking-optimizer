from __future__ import annotations
"""离散事件仿真引擎 (SimPy)"""

import random
import simpy
from .parking_lot import ParkingLot
from ..domain.spot import Vehicle, Spot, Event, EventType
from ..routing.path_engine import PathEngine


class SimulationEngine:
    """SimPy 停车仿真主循环"""

    CAR_SPEED = 1.39  # m/s (5 km/h)
    MAX_WAIT_TIME = 1800  # 最大等待秒数（30分钟）
    RETRY_INTERVAL = 60  # 排队等待时的重试间隔（秒）

    def __init__(self, parking_lot: ParkingLot, path_engine: PathEngine,
                 vehicles: list[Vehicle], strategy, seed: int = 42):
        self.env = simpy.Environment()
        self.parking_lot = parking_lot
        self.path_engine = path_engine
        self.vehicles = vehicles
        self.strategy = strategy  # 策略对象 (需有 .assign(vehicle, time, parking_lot, path_engine) 方法)
        self.seed = seed
        random.seed(seed)

        self.events: list[Event] = []
        self.shift_count = 0
        self.total_shift_dist = 0.0

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
            self._log(self.env.now, EventType.WAIT_START, vehicle.vehicle_id)
            vehicle.wait_start = self.env.now
            # 排队等待：周期性重试，直到成功或超时
            while True:
                yield self.env.timeout(self.RETRY_INTERVAL)
                result = self.strategy.assign(vehicle, self.env.now,
                                              self.parking_lot, self.path_engine)
                spot, status = result
                if status == "assigned":
                    break
                if self.env.now - vehicle.wait_start >= self.MAX_WAIT_TIME:
                    vehicle.wait_end = self.env.now
                    self._log(self.env.now, EventType.WAIT_END, vehicle.vehicle_id)
                    vehicle.rejected = True
                    self._log(self.env.now, EventType.REJECTED, vehicle.vehicle_id,
                              reason="等待超时后仍无空闲车位，无法分配")
                    return
            vehicle.wait_end = self.env.now
            self._log(self.env.now, EventType.WAIT_END, vehicle.vehicle_id)

        # 分配成功
        self.parking_lot.assign(vehicle, spot)
        drive_dist = self.path_engine.distance_to_spot(spot.node_id)
        drive_time = drive_dist / self.CAR_SPEED

        self._log(self.env.now, EventType.PARKING_ASSIGNED, vehicle.vehicle_id,
                  spot.spot_id, self.strategy.name)
        yield self.env.timeout(drive_time)

        self._log(self.env.now, EventType.SPOT_ENTRY, vehicle.vehicle_id,
                  spot.spot_id, drive_distance=drive_dist)

        # 调度离场
        dep_time = self.env.now + vehicle.parking_duration
        self.env.process(self._vehicle_departure(vehicle, dep_time))

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
            travel_time = dist / self.CAR_SPEED

            self._log(self.env.now, EventType.SHIFT_START, blk_vid,
                      from_spot=blk_spot.spot_id, to_spot=buffer.spot_id,
                      blocked_vehicle=vehicle.vehicle_id, distance=dist,
                      reason=f"为让行内层车辆 {vehicle.vehicle_id} 离场而临时移位")
            self.shift_count += 1
            self.total_shift_dist += dist * 2

            yield self.env.timeout(travel_time)
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

    def _find_innermost_available(self, spot: Spot) -> Spot | None:
        """找纵深组中最内侧的空闲车位（用于前移归位）"""
        group = self.parking_lot.get_group_spots(spot)
        for s in reversed(group):  # 从内到外
            if not s.is_occupied:
                return s
        return None
