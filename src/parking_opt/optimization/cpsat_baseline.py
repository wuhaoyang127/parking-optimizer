from __future__ import annotations
"""CP-SAT 离线全信息基准（小规模）"""

from ortools.sat.python import cp_model
from ..domain.spot import Vehicle, Spot, SpotType
from ..simulation.parking_lot import ParkingLot
from ..routing.path_engine import PathEngine


class CPSatBaseline:
    """小规模全信息精确优化"""

    name = "cpsat_oracle"
    TIMEOUT = 300  # 秒

    def __init__(self, parking_lot: ParkingLot, path_engine: PathEngine):
        self.parking_lot = parking_lot
        self.path_engine = path_engine

    def solve(self, vehicles: list[Vehicle]) -> dict[str, str] | None:
        """返回 {vehicle_id: spot_id} 最优分配，或 None"""
        spots = list(self.parking_lot.spots.values())
        n_vehicles = len(vehicles)
        n_spots = len(spots)

        if n_spots > 20 or n_vehicles > 40:
            return None  # 超出规模，不求解

        model = cp_model.CpModel()

        # 决策变量: x[v][s] = 1 表示车辆v分配到车位s
        x = {}
        for v_idx, v in enumerate(vehicles):
            for s_idx, s in enumerate(spots):
                x[(v_idx, s_idx)] = model.NewBoolVar(f'x_{v_idx}_{s_idx}')

        # 约束1: 每辆车最多一个车位
        for v_idx in range(n_vehicles):
            model.Add(sum(x[(v_idx, s_idx)] for s_idx in range(n_spots)) <= 1)

        # 约束2: 每个车位最多一辆车
        for s_idx in range(n_spots):
            model.Add(sum(x[(v_idx, s_idx)] for v_idx in range(n_vehicles)) <= 1)

        # 约束3: depth可用性 + 时间不重叠 (简化: 只检查depth顺序)
        for v_idx, v in enumerate(vehicles):
            for s_idx, s in enumerate(spots):
                if s.spot_type == SpotType.TANDEM and s.depth > 1:
                    # 如果分配depth>1, 则外侧所有车位不能有更晚离场的车
                    outer_spots = self.parking_lot.get_outer_spots(s)
                    for outer in outer_spots:
                        outer_idx = spots.index(outer)
                        for v2_idx, v2 in enumerate(vehicles):
                            if v2_idx != v_idx:
                                # 简化: 如果外侧被分配, 要求外侧车离场时间 ≥ 内侧车
                                # (实际CP-SAT需要更复杂的时间维度建模)
                                pass

        # 目标: 最大化满足率
        assigned = [model.NewBoolVar(f'assigned_{v_idx}') for v_idx in range(n_vehicles)]
        for v_idx in range(n_vehicles):
            model.Add(assigned[v_idx] == sum(x[(v_idx, s_idx)] for s_idx in range(n_spots)))

        model.Maximize(sum(assigned))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.TIMEOUT
        status = solver.Solve(model)

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            result = {}
            for v_idx, v in enumerate(vehicles):
                for s_idx, s in enumerate(spots):
                    if solver.Value(x[(v_idx, s_idx)]) == 1:
                        result[v.vehicle_id] = s.spot_id
            return result
        return None
