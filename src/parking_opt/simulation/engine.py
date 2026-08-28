from __future__ import annotations
"""离散事件仿真引擎 (SimPy)

- 时间片路口碰撞检测：所有车辆运动（入库/离场/移位）按有向边生成时间片，
  同一边上时间片不重叠（EDGE_GAP 间隔），冲突时等待推进（硬约束）。
- 场景 A 离场让行：里层车离场被外层车阻挡时，外层车移位让行 → 里层车离场 → 外层车回位。
- 场景 B 入库让行：新车停里层车位被外层车阻挡时，外层车移位让行 → 新车停入 → 外层车回位。
"""

import math
import random
import simpy
from dataclasses import dataclass
from .parking_lot import ParkingLot
from ..domain.spot import Vehicle, Spot, Event, EventType, SpotType
from ..routing.path_engine import PathEngine
from .defaults import CAR_SPEED as DEFAULT_CAR_SPEED, MAX_WAIT_TIME as DEFAULT_MAX_WAIT


@dataclass
class TimeSlice:
    """道路时间片：车辆在一条有向边上的占用区间（路口碰撞检测单元）。"""
    vehicle_id: str
    edge: tuple[str, str]  # (from_node, to_node)
    start: float
    end: float
    kind: str              # enter / leave / shift


class SimulationEngine:
    """SimPy 停车仿真主循环（含时间片碰撞检测与双向移位让行）"""

    CAR_SPEED = DEFAULT_CAR_SPEED  # m/s (5 km/h)，默认值，可被构造参数覆盖
    MAX_WAIT_TIME = DEFAULT_MAX_WAIT  # 最大等待秒数（30分钟），默认值
    RETRY_INTERVAL = 60  # 排队等待时的重试间隔（秒）
    EDGE_GAP = 2.0  # 路口碰撞 GAP 间隔（秒）：同一边相邻时间片的最小间隔
    MAX_SLICE_ITER = 500  # 时间片冲突等待的最大推进次数（防御）

    def __init__(self, parking_lot: ParkingLot, path_engine: PathEngine,
                 vehicles: list[Vehicle], strategy, seed: int = 42,
                 wait_policy: str = "fifo", car_speed: float = DEFAULT_CAR_SPEED,
                 max_wait_time: float = DEFAULT_MAX_WAIT):
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
        self.time_slices: list[TimeSlice] = []  # 全部车辆运动时间片（路口碰撞检测）

    # ========== 事件与基础 ==========

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

    # ========== 时间片：路口碰撞检测 ==========

    def _edge_conflicts(self, ts: TimeSlice) -> list[TimeSlice]:
        """返回与 ts 在同一条有向边上时间重叠（考虑 GAP）的已有时间片。"""
        out = []
        for other in self.time_slices:
            if other.edge != ts.edge:
                continue
            if not (ts.end + self.EDGE_GAP <= other.start
                    or other.end + self.EDGE_GAP <= ts.start):
                out.append(other)
        return out

    def _reserve_drive(self, vehicle: Vehicle, path_nodes: list[str], kind: str,
                       start_time: float):
        """SimPy 生成器：按路径逐边预留时间片并行驶，返回 (成功, 结束时刻)。

        每条边先检测同边时间片冲突：冲突则等待到最早安全时刻（yield timeout），
        醒来后重新检测（避免等待期间被其他车辆抢占），安全后登记时间片并行驶。
        """
        edges = self.path_engine.get_path_edges(path_nodes)
        if not edges:
            return False, start_time
        t = start_time
        for (a, b, length) in edges:
            travel = length / self.car_speed
            if travel <= 0:
                continue
            iterations = 0
            while True:
                ts = TimeSlice(vehicle.vehicle_id, (a, b), t, t + travel, kind)
                conflicts = self._edge_conflicts(ts)
                if not conflicts:
                    if t <= self.env.now:
                        self.time_slices.append(ts)
                        break
                    # 安全但未到时刻：等到 t 再重新检测（防抢占）
                    yield self.env.timeout(max(0.0, t - self.env.now))
                    continue
                # 冲突：推进到最早安全时刻
                t = max(c.end for c in conflicts) + self.EDGE_GAP
                iterations += 1
                if iterations > self.MAX_SLICE_ITER:
                    return False, start_time
                if t > self.env.now:
                    yield self.env.timeout(t - self.env.now)
            # 行驶通过这条边
            yield self.env.timeout(travel)
            t += travel
        return True, t

    # ========== 车辆到达与入库 ==========

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

        # 兜底防御：分配车位在路网中从该车入口不可达时拒绝，
        # 避免 inf 行驶时间传播进仿真时钟产生 nan 事件时间（真实布局导入）
        dist_to_spot = self.path_engine.distance_to_spot(spot.node_id, self._entry_for(vehicle))
        if not math.isfinite(dist_to_spot):
            vehicle.rejected = True
            self._log(self.env.now, EventType.REJECTED, vehicle.vehicle_id,
                      strategy=self.strategy.name,
                      reason=f"分配车位 {spot.spot_id} 从入口不可达，无法入位")
            return

        # 立即分配成功：同步占位，异步行驶入位（含场景 B 入库让行）
        self._occupy(vehicle, spot)
        self.env.process(self._drive_and_depart(vehicle, spot))

    def _occupy(self, vehicle: Vehicle, spot: Spot):
        """同步占用车位 + 记录分配事件（保证后续车不会再分到同一车位）"""
        self.parking_lot.assign(vehicle, spot)
        self._log(self.env.now, EventType.PARKING_ASSIGNED, vehicle.vehicle_id,
                  spot.spot_id, self.strategy.name)

    def _vehicle_by_id(self, vehicle_id: str) -> Vehicle | None:
        return self.parking_lot.vehicles.get(vehicle_id)

    def _entry_for(self, vehicle: Vehicle) -> str:
        """该车入库入口：vehicle.entry_id 有效则用之，否则默认入口。"""
        return self.path_engine.resolve_entry(getattr(vehicle, "entry_id", None))

    def _exit_for(self, vehicle: Vehicle) -> str:
        """该车离场出口：vehicle.exit_id 有效则用之，否则默认出口；
        布局没有出口节点时回退默认入口（旧布局兼容）。"""
        return self.path_engine.resolve_exit(getattr(vehicle, "exit_id", None))

    def _leave_path(self, vehicle: Vehicle, spot: Spot) -> tuple[list[str], str, bool]:
        """离场路径：优先车辆出口；出口不可达时回退入口（并标记 degraded）。

        返回 (path_nodes, exit_node_used, degraded)。path_nodes 为空表示车位与
        出口/入口均不连通（罕见坏布局，由调用方按旧行为继续，不额外崩溃）。
        """
        entry = self._entry_for(vehicle)
        exit_node = self._exit_for(vehicle)
        path = self.path_engine.shortest_path(spot.node_id, exit_node)
        if path:
            return path, exit_node, False
        if exit_node != entry:
            path = self.path_engine.shortest_path(spot.node_id, entry)
            if path:
                return path, entry, True
        return [], exit_node, False

    def _entry_blockers(self, spot: Spot) -> list[tuple[Spot, str]]:
        """场景 B：入库目标为里层车位时，返回阻挡入位的外层车辆（从外到内）。"""
        if spot.spot_type != SpotType.TANDEM or spot.depth <= 1:
            return []
        blockers = []
        for outer in self.parking_lot.get_outer_spots(spot):
            if outer.is_occupied and outer.occupied_by:
                blockers.append((outer, outer.occupied_by))
        return blockers

    def _drive_and_depart(self, vehicle: Vehicle, spot: Spot):
        """异步：行驶入位（场景 B 入库让行）→ 调度离场"""
        blockers = self._entry_blockers(spot)
        shift_pairs: list[tuple[Spot, Spot, str]] = []  # (原车位, 缓冲位, 移位车id)

        # ── 场景 B：外行车移位让行 → 新车停入 → 外行车回位 ──
        for blk_spot, blk_vid in blockers:
            blocker = self._vehicle_by_id(blk_vid)
            if blocker is None:
                continue
            buffer = self.parking_lot.select_buffer()
            if buffer is None:
                self._log(self.env.now, EventType.BUFFER_FAILED, blk_vid,
                          blocked_vehicle=vehicle.vehicle_id,
                          reason="无可用缓冲位，无法入库让行")
                continue
            dist = self.path_engine.shortest_distance(blk_spot.node_id, buffer.node_id)
            if not math.isfinite(dist):
                self.parking_lot.release_buffer(buffer.spot_id)
                self._log(self.env.now, EventType.BUFFER_FAILED, blk_vid,
                          blocked_vehicle=vehicle.vehicle_id,
                          reason=f"缓冲位 {buffer.spot_id} 与阻挡车位 {blk_spot.spot_id} 不连通")
                continue
            path_out = self.path_engine.shortest_path(blk_spot.node_id, buffer.node_id)
            self._log(self.env.now, EventType.SHIFT_START, blk_vid,
                      from_spot=blk_spot.spot_id, to_spot=buffer.spot_id,
                      blocked_vehicle=vehicle.vehicle_id, distance=dist,
                      reason=f"为让行新车 {vehicle.vehicle_id} 入库而临时移位")
            self.shift_count += 1
            self.total_shift_dist += dist * 2
            ok, _ = yield from self._reserve_drive(blocker, path_out, "shift", self.env.now)
            if not ok:
                self.parking_lot.release_buffer(buffer.spot_id)
                continue
            self.parking_lot.move_vehicle(blk_spot, buffer)
            shift_pairs.append((blk_spot, buffer, blk_vid))

        # ── 新车驶入目标车位 ──
        entry = self._entry_for(vehicle)
        drive_dist = self.path_engine.distance_to_spot(spot.node_id, entry)
        path_in = self.path_engine.shortest_path(entry, spot.node_id)
        ok, _ = yield from self._reserve_drive(vehicle, path_in, "enter", self.env.now)
        if not ok:
            # 行驶失败（时间片冲突过多，罕见）：释放车位并拒绝
            self.parking_lot.free(spot)
            vehicle.rejected = True
            self._log(self.env.now, EventType.REJECTED, vehicle.vehicle_id,
                      reason="入库行驶时间片冲突过多，无法入位")
            for blk_spot, buffer, blk_vid in shift_pairs:
                self.parking_lot.move_vehicle(buffer, blk_spot)
                self.parking_lot.release_buffer(buffer.spot_id)
            return
        self._log(self.env.now, EventType.SPOT_ENTRY, vehicle.vehicle_id,
                  spot.spot_id, drive_distance=drive_dist, entry=entry)

        # ── 外行车回位 ──
        for blk_spot, buffer, blk_vid in reversed(shift_pairs):
            # 回位前/后各检查一次：行驶期间若已被其它进程移走，则跳过回位
            if buffer.occupied_by != blk_vid:
                self.parking_lot.release_buffer(buffer.spot_id)
                continue
            blocker = self._vehicle_by_id(blk_vid)
            path_back = self.path_engine.shortest_path(buffer.node_id, blk_spot.node_id)
            if blocker is not None and path_back:
                yield from self._reserve_drive(blocker, path_back, "shift", self.env.now)
            if buffer.occupied_by != blk_vid:
                self.parking_lot.release_buffer(buffer.spot_id)
                continue
            self.parking_lot.move_vehicle(buffer, blk_spot)
            self.parking_lot.release_buffer(buffer.spot_id)
            self._log(self.env.now, EventType.SHIFT_END, blk_vid,
                      final_spot=blk_spot.spot_id)

        # 调度离场
        dep_time = self.env.now + vehicle.parking_duration
        self.env.process(self._vehicle_departure(vehicle, dep_time))

    # ========== 等待队列 ==========

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
                # 兜底防御：不可达车位拒绝，避免 inf/nan 时间传播
                dist = self.path_engine.distance_to_spot(spot.node_id, self._entry_for(vehicle))
                if not math.isfinite(dist):
                    self.waiting_queue.remove(vehicle)
                    vehicle.wait_end = self.env.now
                    vehicle.rejected = True
                    self._log(self.env.now, EventType.WAIT_END, vehicle.vehicle_id)
                    self._log(self.env.now, EventType.REJECTED, vehicle.vehicle_id,
                              strategy=self.strategy.name,
                              reason=f"分配车位 {spot.spot_id} 从入口不可达，无法入位")
                    continue
                self.waiting_queue.remove(vehicle)
                vehicle.wait_end = self.env.now
                self._log(self.env.now, EventType.WAIT_END, vehicle.vehicle_id)
                # 同步占位（避免循环内后续车重复分配到同一车位），异步行驶入位
                self._occupy(vehicle, spot)
                self.env.process(self._drive_and_depart(vehicle, spot))

    # ========== 离场（场景 A 离场让行） ==========

    def _vehicle_departure(self, vehicle: Vehicle, dep_time: float):
        """车辆离场处理（含场景 A 移位让行 + 时间片碰撞检测）"""
        yield self.env.timeout(dep_time - self.env.now)

        spot = self.parking_lot.get_spot(vehicle.assigned_spot)
        blockers = self.parking_lot.get_blockers(spot)

        if not blockers:
            # 无阻挡，直接离场（时间片：车位 → 该车出口；出口不可达回退入口）
            path_out, exit_node, degraded = self._leave_path(vehicle, spot)
            if degraded:
                self._log(self.env.now, EventType.DEGRADATION, vehicle.vehicle_id,
                          reason="出口不可达，离场回退入口")
            yield from self._reserve_drive(vehicle, path_out, "leave", self.env.now)
            self.parking_lot.free(spot)
            self._log(self.env.now, EventType.DEPARTURE, vehicle.vehicle_id,
                      spot.spot_id, had_blocking=False, exit=exit_node)
            self._dispatch_waiting()  # 车位空出，调度等待队列
            return

        # 有阻挡，执行场景 A 移位让行
        self._log(self.env.now, EventType.DEPARTURE, vehicle.vehicle_id,
                  spot.spot_id, had_blocking=True, blocker_count=len(blockers),
                  exit=self._exit_for(vehicle),
                  reason=f"被 {len(blockers)} 辆外侧车辆阻挡，需移位后离场")

        for blk_spot, blk_vid in blockers:
            blocker = self._vehicle_by_id(blk_vid)
            buffer = self.parking_lot.select_buffer()
            if buffer is None:
                self._log(self.env.now, EventType.BUFFER_FAILED, blk_vid,
                          blocked_vehicle=vehicle.vehicle_id, reason="无可用缓冲位，无法移位")
                continue

            # 移位
            dist = self.path_engine.shortest_distance(blk_spot.node_id, buffer.node_id)
            if not math.isfinite(dist):
                self.parking_lot.release_buffer(buffer.spot_id)
                self._log(self.env.now, EventType.BUFFER_FAILED, blk_vid,
                          blocked_vehicle=vehicle.vehicle_id,
                          reason=f"缓冲位 {buffer.spot_id} 与阻挡车位 {blk_spot.spot_id} 不连通，无法移位")
                continue
            path_shift = self.path_engine.shortest_path(blk_spot.node_id, buffer.node_id)
            self._log(self.env.now, EventType.SHIFT_START, blk_vid,
                      from_spot=blk_spot.spot_id, to_spot=buffer.spot_id,
                      blocked_vehicle=vehicle.vehicle_id, distance=dist,
                      reason=f"为让行内层车辆 {vehicle.vehicle_id} 离场而临时移位")
            self.shift_count += 1
            self.total_shift_dist += dist * 2

            if blocker is not None:
                ok, _ = yield from self._reserve_drive(blocker, path_shift, "shift", self.env.now)
                if not ok:
                    self.parking_lot.release_buffer(buffer.spot_id)
                    continue
            # 外层车可能在移位行驶期间已自行离场（此时无阻挡，直接让里层车离场）
            if blk_spot.occupied_by != blk_vid:
                self.parking_lot.free(spot)
                self.parking_lot.release_buffer(buffer.spot_id)
                continue
            self.parking_lot.move_vehicle(blk_spot, buffer)

            # 被阻挡车离场（时间片：车位 → 该车出口；出口不可达回退入口）
            path_out, exit_node, degraded = self._leave_path(vehicle, spot)
            if degraded:
                self._log(self.env.now, EventType.DEGRADATION, vehicle.vehicle_id,
                          reason="出口不可达，离场回退入口")
            ok, _ = yield from self._reserve_drive(vehicle, path_out, "leave", self.env.now)
            self.parking_lot.free(spot)

            # 阻挡车归位（或前移）。回位前/后各检查一次：行驶期间若已被
            # 其它进程移走（并发让行竞态），则跳过回位，防止 move_vehicle 断言崩溃。
            if buffer.occupied_by != blk_vid:
                self.parking_lot.release_buffer(buffer.spot_id)
                continue
            path_back = self.path_engine.shortest_path(buffer.node_id, blk_spot.node_id)
            if blocker is not None and path_back:
                yield from self._reserve_drive(blocker, path_back, "shift", self.env.now)
            if buffer.occupied_by != blk_vid:
                self.parking_lot.release_buffer(buffer.spot_id)
                continue
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
