from __future__ import annotations
"""车辆到达与入库（含场景 B 入库让行）mixin。"""
import math

from ..domain.spot import Vehicle, Spot, EventType, SpotType


class ArrivalMixin:
    """车辆到达处理、同步占位、入库行驶（场景 B：外行车移位让行）。"""

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
            # 移位行驶期间，阻挡车可能已自行离场（并发竞态）：跳过移位，避免空车位断言
            if blk_spot.occupied_by != blk_vid:
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
