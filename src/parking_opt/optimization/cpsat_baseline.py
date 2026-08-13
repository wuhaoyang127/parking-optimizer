from __future__ import annotations
"""CP-SAT 离线全信息基准（区间调度 + 纵深离场顺序约束）"""

from ortools.sat.python import cp_model
from ..domain.spot import Vehicle, Spot
from ..simulation.parking_lot import ParkingLot
from ..routing.path_engine import PathEngine


class CPSatBaseline:
    """离线全信息精确优化基准（小规模）。

    假设：
      - 已知每辆车的到达/离场时间（离线全信息，用 parking_duration 计算 departure_time）
      - 车位可复用：同一车位可先后服务多辆时间不重叠的车
      - 纵深约束：同组里层车离场时，外层车必须已离开（否则移位）

    输出：{vehicle_id: spot_id} 的可行分配，最大化满足率。
    """

    name = "cpsat_oracle"
    TIMEOUT = 15  # 秒

    def __init__(self, parking_lot: ParkingLot, path_engine: PathEngine):
        self.parking_lot = parking_lot
        self.path_engine = path_engine

    def solve(self, vehicles: list[Vehicle]) -> dict[str, str] | None:
        """返回 {vehicle_id: spot_id} 最优分配，或 None（超规模/无解）"""
        spots = list(self.parking_lot.spots.values())
        n_vehicles = len(vehicles)
        n_spots = len(spots)

        if n_spots > 40 or n_vehicles > 120:
            return None

        model = cp_model.CpModel()

        # 决策变量: x[(v_idx, s_idx)] = 1 表示车辆v分配到车位s
        x = {}
        for v_idx in range(n_vehicles):
            for s_idx in range(n_spots):
                x[(v_idx, s_idx)] = model.NewBoolVar(f'x_{v_idx}_{s_idx}')

        # 约束1: 每辆车至多一个车位
        for v_idx in range(n_vehicles):
            model.Add(sum(x[(v_idx, s_idx)] for s_idx in range(n_spots)) <= 1)

        # 约束2: 同一车位不能同时停两辆时间重叠的车
        for s_idx in range(n_spots):
            for v1_idx, v1 in enumerate(vehicles):
                for v2_idx in range(v1_idx + 1, n_vehicles):
                    v2 = vehicles[v2_idx]
                    # 时间重叠判断: 任一辆车到达时另一辆还没走
                    if v1.arrival_time < v2.departure_time and v2.arrival_time < v1.departure_time:
                        model.Add(x[(v1_idx, s_idx)] + x[(v2_idx, s_idx)] <= 1)

        # 约束3: 纵深离场顺序 —— 里层车离场时外层车必须已离开
        for gid, group in self.parking_lot.stack_groups.items():
            if len(group) < 2:
                continue
            for outer in group:
                for inner in group:
                    if inner.depth <= outer.depth:
                        continue
                    o_idx = spots.index(outer)
                    i_idx = spots.index(inner)
                    for v1_idx, v1 in enumerate(vehicles):
                        for v2_idx, v2 in enumerate(vehicles):
                            if v1_idx == v2_idx:
                                continue
                            # v2(里层) 离场时 v1(外层) 还没走，且 v2 到达时 v1 还在 → 移位
                            if (v2.departure_time < v1.departure_time
                                    and v2.arrival_time < v1.departure_time
                                    and v1.arrival_time < v2.departure_time):
                                model.Add(x[(v1_idx, o_idx)] + x[(v2_idx, i_idx)] <= 1)

        # 目标: 最大化满足率
        assigned = []
        for v_idx in range(n_vehicles):
            a = model.NewBoolVar(f'assigned_{v_idx}')
            model.Add(a == sum(x[(v_idx, s_idx)] for s_idx in range(n_spots)))
            assigned.append(a)
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
