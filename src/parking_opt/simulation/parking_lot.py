from __future__ import annotations
"""停车场状态管理：占用跟踪、可用性判断、阻挡检测"""

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
        """所有当前可分配车位"""
        return [s for s in self.spots.values() if self.is_available(s)]

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
        """征用一个空闲车位作为缓冲位（排除已在缓冲位使用中的）"""
        for spot in self.spots.values():
            if (not spot.is_occupied
                    and spot.spot_id not in self.buffer_in_use
                    and (spot.spot_type == SpotType.STANDALONE or spot.depth == 1)):
                self.buffer_in_use.add(spot.spot_id)
                return spot
        return None

    def release_buffer(self, spot_id: str):
        """释放缓冲位"""
        self.buffer_in_use.discard(spot_id)

    # ========== 状态变更 ==========

    def assign(self, vehicle: Vehicle, spot: Spot):
        """分配车位"""
        spot.is_occupied = True
        spot.occupied_by = vehicle.vehicle_id
        vehicle.assigned_spot = spot.spot_id
        self.vehicles[vehicle.vehicle_id] = vehicle

    def free(self, spot: Spot):
        """释放车位"""
        vid = spot.occupied_by
        spot.is_occupied = False
        spot.occupied_by = None
        if vid and vid in self.vehicles:
            del self.vehicles[vid]

    def move_vehicle(self, from_spot: Spot, to_spot: Spot):
        """将车辆从 from_spot 移到 to_spot"""
        vid = from_spot.occupied_by
        assert vid is not None
        to_spot.is_occupied = True
        to_spot.occupied_by = vid
        from_spot.is_occupied = False
        from_spot.occupied_by = None
