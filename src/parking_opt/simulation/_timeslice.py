from __future__ import annotations
"""时间片碰撞检测（SimPy 引擎 mixin）。"""
from dataclasses import dataclass


@dataclass
class TimeSlice:
    """道路时间片：车辆在一条有向边上的占用区间（路口碰撞检测单元）。"""
    vehicle_id: str
    edge: tuple[str, str]  # (from_node, to_node)
    start: float
    end: float
    kind: str              # enter / leave / shift


class TimeSliceMixin:
    """路口碰撞检测：同一边时间片不重叠（EDGE_GAP 间隔），冲突时等待推进。"""

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

    def _reserve_drive(self, vehicle, path_nodes: list[str], kind: str,
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
