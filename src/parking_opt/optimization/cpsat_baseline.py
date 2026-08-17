from __future__ import annotations
"""CP-SAT 离线全信息基准（区间调度：允许排队等待 + 车位复用）"""

from ortools.sat.python import cp_model
from ..domain.spot import Vehicle
from ..simulation.parking_lot import ParkingLot
from ..routing.path_engine import PathEngine


class CPSatBaseline:
    """离线全信息精确优化基准（满足率上界）。

    建模：用 CP-SAT 区间变量，每辆车有一个可选停车区间
      - 停车开始时间可在 [到达时间, 到达时间 + 等待上限] 内后移（即允许排队等待）
      - 停车时长为固定值 parking_duration
      - 同一车位上的停车区间不重叠（车位复用）

    这给出「忽略移位代价、允许排队等待」的满足率上界，是真正的上界（≥ 任何在线策略）。
    """

    name = "cpsat_oracle"
    TIMEOUT = 10  # 秒（默认值）
    MAX_WAIT = 1800  # 等待上限（秒，默认值），与引擎 SimulationEngine.MAX_WAIT_TIME 一致

    def __init__(self, parking_lot: ParkingLot, path_engine: PathEngine,
                 timeout: float = 10, max_wait: float = 1800):
        self.parking_lot = parking_lot
        self.path_engine = path_engine
        self.timeout = timeout
        self.max_wait = max_wait

    def solve(self, vehicles: list[Vehicle]) -> dict[str, str] | None:
        """返回 {vehicle_id: spot_id} 最优分配，或 None（超规模/无解）"""
        spots = list(self.parking_lot.spots.values())
        n_vehicles = len(vehicles)
        n_spots = len(spots)

        if n_spots > 40 or n_vehicles > 120:
            return None

        model = cp_model.CpModel()

        # 决策变量：x[(v,s)] 是否分配；start[v] 停车开始时间（可等待）；interval 可选区间
        x = {}
        start = {}
        intervals = {}
        for v_idx, v in enumerate(vehicles):
            s_var = model.NewIntVar(int(v.arrival_time),
                                    int(v.arrival_time) + int(self.max_wait),
                                    f'start_{v_idx}')
            start[v_idx] = s_var
            dur = max(1, int(v.parking_duration))
            for s_idx in range(n_spots):
                x[(v_idx, s_idx)] = model.NewBoolVar(f'x_{v_idx}_{s_idx}')
                intervals[(v_idx, s_idx)] = model.NewOptionalIntervalVar(
                    s_var, dur, s_var + dur, x[(v_idx, s_idx)], f'iv_{v_idx}_{s_idx}')

        # 约束1: 每辆车至多一个车位
        for v_idx in range(n_vehicles):
            model.Add(sum(x[(v_idx, s_idx)] for s_idx in range(n_spots)) <= 1)

        # 约束2: 同一车位上停车区间不重叠（车位复用）
        for s_idx in range(n_spots):
            model.AddNoOverlap([intervals[(v_idx, s_idx)] for v_idx in range(n_vehicles)])

        # 目标: 最大化满足率（分配车辆数）
        model.Maximize(sum(x[(v_idx, s_idx)]
                           for v_idx in range(n_vehicles) for s_idx in range(n_spots)))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.timeout
        status = solver.Solve(model)

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            result = {}
            for v_idx, v in enumerate(vehicles):
                for s_idx, s in enumerate(spots):
                    if solver.Value(x[(v_idx, s_idx)]) == 1:
                        result[v.vehicle_id] = s.spot_id
            return result
        return None
