from __future__ import annotations
"""等待队列调度与离场（含场景 A 离场让行）mixin。"""
import math

from ..domain.spot import Vehicle, Spot, EventType


class DepartureMixin:
    """等待队列调度、超时拒绝、离场处理（场景 A：外层车移位让行）。"""

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
            # 缓冲位可能在行驶期间被等待车辆分配占用：放弃本次移位，避免覆盖他人占用
            if buffer.is_occupied:
                self.parking_lot.release_buffer(buffer.spot_id)
                self._log(self.env.now, EventType.BUFFER_FAILED, blk_vid,
                          blocked_vehicle=vehicle.vehicle_id,
                          reason=f"缓冲位 {buffer.spot_id} 在移位行驶期间被占用")
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
