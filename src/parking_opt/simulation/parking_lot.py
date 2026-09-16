from __future__ import annotations
"""停车场状态管理：占用跟踪、可用性判断、阻挡检测、缓冲位评分选位"""
import math

from ..domain.spot import Spot, SpotType, Vehicle


class ParkingLot:
    """停车场运行时状态"""

    def __init__(self, spots: list[Spot]):
        self.spots: dict[str, Spot] = {s.spot_id: s for s in spots}
        self.vehicles: dict[str, Vehicle] = {}

        # 纵深组索引
        self.stack_groups: dict[str, list[Spot]] = {}
        for spot in spots:
            gid = spot.stack_group_id
            if gid not in self.stack_groups:
                self.stack_groups[gid] = []
            self.stack_groups[gid].append(spot)
        # 每组按 depth 排序
        for spots_in_group in self.stack_groups.values():
            spots_in_group.sort(key=lambda s: s.depth)

        # 缓冲位追踪
        self.buffer_in_use: set[str] = set()

    # ========== 车位查询 ==========

    def get_spot(self, spot_id: str) -> Spot:
        return self.spots[spot_id]

    def get_group_spots(self, spot: Spot) -> list[Spot]:
        """获取同纵深组的所有车位（按depth排序）"""
        return self.stack_groups.get(spot.stack_group_id, [spot])

    def get_outer_spots(self, spot: Spot) -> list[Spot]:
        """获取 depth < spot.depth 的同组车位"""
        return [s for s in self.get_group_spots(spot) if s.depth < spot.depth]

    def get_inner_spots(self, spot: Spot) -> list[Spot]:
        """获取 depth > spot.depth 的同组车位"""
        return [s for s in self.get_group_spots(spot) if s.depth > spot.depth]

    # ========== 可用性 ==========

    def is_available(self, spot: Spot) -> bool:
        """车位是否可分配（只要空闲即可，深度约束由策略决定）"""
        return not spot.is_occupied

    def get_available_spots(self) -> list[Spot]:
        """所有当前可分配车位（不含已征用为缓冲位的车位，避免分配竞态）"""
        return [s for s in self.spots.values()
                if self.is_available(s) and s.spot_id not in self.buffer_in_use]

    # ========== 阻挡检测 ==========

    def get_blockers(self, spot: Spot) -> list[tuple[Spot, str]]:
        """获取阻挡spot离场的车辆列表，返回 [(阻挡车位, vehicle_id), ...]（从外到内）"""
        if spot.spot_type == SpotType.STANDALONE:
            return []
        blockers = []
        for outer in self.get_outer_spots(spot):
            if outer.is_occupied and outer.occupied_by:
                blockers.append((outer, outer.occupied_by))
        return blockers  # 已按depth从小到大排序

    def is_blocked(self, spot: Spot) -> bool:
        """spot 是否被阻挡"""
        return len(self.get_blockers(spot)) > 0

    # ========== 缓冲位 ==========

    def select_buffer(self) -> Spot | None:
        """征用一个空闲车位作为缓冲位（排除已在缓冲位使用中的）。

        旧版字典序选取逻辑，保留向后兼容（无路网/时刻信息时仍可用）。
        引擎实际移位请使用 select_buffer_scored（距离+空闲时间+二次移位评分）。
        """
        for spot in self.spots.values():
            if (not spot.is_occupied
                    and spot.spot_id not in self.buffer_in_use
                    and (spot.spot_type == SpotType.STANDALONE or spot.depth == 1)):
                self.buffer_in_use.add(spot.spot_id)
                return spot
        return None

    def _secondary_shift_cost(self, spot: Spot) -> float:
        """二次移位/妨碍代价：停进该缓冲位后可能挡住内层车 → 极可能被要求再次让行。

        - 独立车位：0（不挡任何车，天然不会引起二次移位）；
        - 纵深外层位且同组内层当前有车：1（会挡住内层车）；
        - 纵深外层位且同组内层全空：0。
        """
        if spot.spot_type == SpotType.STANDALONE:
            return 0.0
        inner_occupied = any(s.is_occupied for s in self.get_inner_spots(spot))
        return 1.0 if inner_occupied else 0.0

    def select_buffer_scored(self, from_spot: Spot, path_engine, now: float,
                             waiting_len: int = 0,
                             w_d: float = 1.0, w_t: float = 1.0,
                             w_q: float = 2.0, tau: float = 300.0):
        """按综合代价选缓冲位：C = w_d·D̂ + w_t·T̂ + w_q·Q̂，返回 (spot, score)。

        - D̂ 距离：from_spot 到候选缓冲位的路网最短距离，候选集内 min–max 归一化；
        - T̂ 空闲时间：1/(1+idle/τ)，idle=now-last_freed_at；等待队列非空时 +0.3 压力；
        - Q̂ 二次移位：见 _secondary_shift_cost（0/1）。
        全部候选不可达或不存在时返回 (None, inf)。
        """
        candidates = [s for s in self.spots.values()
                      if (not s.is_occupied
                          and s.spot_id not in self.buffer_in_use
                          and (s.spot_type == SpotType.STANDALONE or s.depth == 1))]
        if not candidates:
            return None, float("inf")
        dists: dict[str, float] = {}
        for s in candidates:
            d = path_engine.shortest_distance(from_spot.node_id, s.node_id)
            if math.isfinite(d):
                dists[s.spot_id] = d
        reachable = [s for s in candidates if s.spot_id in dists]
        if not reachable:
            return None, float("inf")
        d_min, d_max = min(dists.values()), max(dists.values())
        best, best_key = None, None
        for s in reachable:
            d_hat = ((dists[s.spot_id] - d_min) / (d_max - d_min)) if d_max > d_min else 0.0
            if s.last_freed_at is None:
                t_hat = 0.0  # 从未被占用过：视为空闲很久，无空闲时间风险
            else:
                idle = max(0.0, now - s.last_freed_at)
                t_hat = 1.0 / (1.0 + idle / tau)
            if waiting_len > 0:
                t_hat = min(1.0, t_hat + 0.3)
            q_hat = self._secondary_shift_cost(s)
            cost = w_d * d_hat + w_t * t_hat + w_q * q_hat
            key = (cost, dists[s.spot_id], q_hat, s.spot_id)
            if best_key is None or key < best_key:
                best_key, best = key, (s, cost)
        if best is None:
            return None, float("inf")
        self.buffer_in_use.add(best[0].spot_id)
        return best

    def release_buffer(self, spot_id: str):
        """释放缓冲位"""
        self.buffer_in_use.discard(spot_id)

    def find_innermost_available(self, spot: Spot) -> Spot | None:
        """找纵深组中最内侧的空闲车位（用于移位后就近前移归位）。"""
        for s in reversed(self.get_group_spots(spot)):  # 从内到外
            if not s.is_occupied:
                return s
        return None

    # ========== 状态变更 ==========

    def assign(self, vehicle: Vehicle, spot: Spot):
        """分配车位"""
        spot.is_occupied = True
        spot.occupied_by = vehicle.vehicle_id
        vehicle.assigned_spot = spot.spot_id
        self.vehicles[vehicle.vehicle_id] = vehicle

    def free(self, spot: Spot, now: float = None):
        """释放车位"""
        vid = spot.occupied_by
        spot.is_occupied = False
        spot.occupied_by = None
        if now is not None:
            spot.last_freed_at = now
        # 任何车位被释放都不再视为缓冲位占用（含移位车直接从缓冲位离场的竞态）
        self.buffer_in_use.discard(spot.spot_id)
        if vid and vid in self.vehicles:
            del self.vehicles[vid]

    def move_vehicle(self, from_spot: Spot, to_spot: Spot, now: float = None):
        """将车辆从 from_spot 移到 to_spot（同步车辆的实际车位）"""
        vid = from_spot.occupied_by
        assert vid is not None
        to_spot.is_occupied = True
        to_spot.occupied_by = vid
        from_spot.is_occupied = False
        from_spot.occupied_by = None
        if now is not None:
            from_spot.last_freed_at = now
        veh = self.vehicles.get(vid)
        if veh is not None:
            veh.assigned_spot = to_spot.spot_id
