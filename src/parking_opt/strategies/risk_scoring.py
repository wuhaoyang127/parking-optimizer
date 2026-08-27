from __future__ import annotations
"""风险感知多准则评分分配策略（评分式在线分配，单算法）。

对每个空闲候选车位打一个综合代价分，选代价最小者：

    C(s | v, t) = w_d · D̂(s) + w_r · R̂(s, v, t) + w_p · P̂(s)
    s* = argmin_s C(s | v, t)

三项均“越小越好”，先在当前候选集内做 min–max 归一化到 [0,1] 再加权求和：

  - D(s) 距离：入口到车位的最短路径距离（path_engine.distance_to_spot）。
  - R(s,v,t) 阻挡风险 = 预期移位次数：把车 v 放到 s 会引发的移位估计——
      · v 会挡住的已占内层车数量（v 比它们晚走 → 它们离场时要为 v 移位）；
      · 会挡住 v 的已占外层车数量（它们比 v 晚走 → v 离场时要为它们移位）。
    只用“预估离场时刻”edep(x)=arrival_time+estimated_duration（在线可得），
    不读真实停车时长 parking_duration（未来真值）。
  - P(s) 结构惩罚：s 后方更深车位的个数 len(get_inner_spots(s))，静态量，
    惩罚“占用有阻挡潜力的位置”，为短停车保留浅位。

设计依据（文献）：
  - Abdeen, Nemer & Sheltami (2021), Sensors 21(9):3148, doi:10.3390/s21093148——
    停车分配的多准则加权和评分 U_i=Σ w_j·d̄_ij + min–max 归一化。本策略把该评分
    机制从“选停车场（inter-lot，无纵深阻挡）”适配为“场内含纵深阻挡的车位选择”。
  - Kim & Hong (2006), Comput. Oper. Res. 33(4):940–954, doi:10.1016/j.cor.2004.08.005——
    以“堆栈预期额外移位次数”的估计量做决策，支撑 R 项。

与 duration_greedy 的本质区别：后者是硬优先级 tier（独立位永远压过纵深、二值
短/长分流）；本策略无 tier，是距离/风险/结构的连续权衡——较远的独立位可能输给
低风险的近纵深外层。详见 docs/algorithms/risk_scoring.md。
"""

import math

from ..domain.spot import Spot, Vehicle
from ..simulation.parking_lot import ParkingLot
from .baselines import BaseStrategy


class RiskScoringStrategy(BaseStrategy):
    """风险感知多准则评分分配（单算法，评分式在线分配）。"""

    name = "risk_scoring"
    label = "风险感知多准则评分"
    DESCRIPTION = (
        "**风险感知多准则评分**\n\n"
        "对每个空闲车位打一个综合代价分 `C = w_d·距离 + w_r·阻挡风险 + w_p·结构惩罚`，"
        "三项在当前候选车位间归一化后加权，选代价最小的车位。\n\n"
        "- **距离**：入口到车位的最短路；\n"
        "- **阻挡风险**：预期移位次数（用**预估**离场时刻估计，不读真实停车时长）；\n"
        "- **结构惩罚**：车位后方更深车位数，为短停车保留浅位。\n\n"
        "区别于时长感知贪心的硬优先级分层，本策略是距离/风险/结构的**连续权衡**，"
        "三个权重可在下方调节（w_r=w_p=0 时退化为最近路径）。"
    )

    PARAMS = [
        {"key": "w_distance", "label": "距离权重 w_d", "type": "float",
         "min": 0.0, "max": 3.0, "step": 0.1, "default": 1.0,
         "help": "入口到车位距离的权重；单独为正、其余为 0 时退化为最近路径"},
        {"key": "w_risk", "label": "阻挡风险权重 w_r", "type": "float",
         "min": 0.0, "max": 3.0, "step": 0.1, "default": 1.5,
         "help": "预期移位次数的权重；越大越回避会造成阻挡/移位的车位"},
        {"key": "w_depth", "label": "结构惩罚权重 w_p", "type": "float",
         "min": 0.0, "max": 3.0, "step": 0.1, "default": 0.5,
         "help": "车位后方更深车位数的权重；越大越倾向独立位/最深位，保留可阻挡的浅位"},
    ]

    def __init__(self, w_distance: float = 1.0, w_risk: float = 1.5,
                 w_depth: float = 0.5):
        self.w_distance = w_distance
        self.w_risk = w_risk
        self.w_depth = w_depth

    # ---------- 单项原始代价（均“越小越好”） ----------

    @staticmethod
    def _est_departure(v: Vehicle) -> float:
        """预估离场时刻（在线可得）：到达时刻 + 预估时长。绝不使用真实停车时长。"""
        est = getattr(v, "estimated_duration", 0.0) or 0.0
        return v.arrival_time + max(est, 0.0)

    def _risk_cost(self, spot: Spot, vehicle: Vehicle,
                   parking_lot: ParkingLot) -> float:
        """预期移位次数：v 会挡住的已占内层车 + 会挡住 v 的已占外层车。"""
        edep_v = self._est_departure(vehicle)
        risk = 0.0
        # v 放在 spot 会挡住“比 v 早走的已占内层车”（v 走得更晚 → 需为它们移位）
        for inner in parking_lot.get_inner_spots(spot):
            if inner.is_occupied and inner.occupied_by:
                u = parking_lot.vehicles.get(inner.occupied_by)
                if u is not None and edep_v > self._est_departure(u):
                    risk += 1.0
        # 已占外层车会挡住 v：若它们比 v 晚走 → v 离场时需为它们移位
        for outer in parking_lot.get_outer_spots(spot):
            if outer.is_occupied and outer.occupied_by:
                o = parking_lot.vehicles.get(outer.occupied_by)
                if o is not None and self._est_departure(o) > edep_v:
                    risk += 1.0
        return risk

    def _depth_cost(self, spot: Spot, parking_lot: ParkingLot) -> float:
        """结构惩罚：该车位后方更深车位的个数（静态，反映阻挡潜力）。"""
        return float(len(parking_lot.get_inner_spots(spot)))

    # ---------- 分配 ----------

    def assign(self, vehicle: Vehicle, time: float, parking_lot: ParkingLot,
               path_engine) -> tuple[Spot | None, str]:
        available = parking_lot.get_available_spots()
        if not available:
            return (None, "waiting")

        # 一趟收集三项原始代价
        dist_raw: list[float] = []
        risk_raw: list[float] = []
        depth_raw: list[float] = []
        for s in available:
            dist_raw.append(path_engine.distance_to_spot(s.node_id))
            risk_raw.append(self._risk_cost(s, vehicle, parking_lot))
            depth_raw.append(self._depth_cost(s, parking_lot))

        dist_n = self._normalize(dist_raw)
        risk_n = self._normalize(risk_raw)
        depth_n = self._normalize(depth_raw)

        best_idx = 0
        best_key: tuple | None = None
        for i, s in enumerate(available):
            cost = (self.w_distance * dist_n[i]
                    + self.w_risk * risk_n[i]
                    + self.w_depth * depth_n[i])
            # tie-break：(综合代价, 原始距离, depth, spot_id) 升序，完全确定
            raw_d = dist_raw[i] if math.isfinite(dist_raw[i]) else math.inf
            key = (cost, raw_d, s.depth, s.spot_id)
            if best_key is None or key < best_key:
                best_key = key
                best_idx = i

        return (available[best_idx], "assigned")

    @staticmethod
    def _normalize(values: list[float]) -> list[float]:
        """min–max 归一化到 [0,1]（越小越好，保序），防 NaN/inf：

        - 非有限值（如不可达车位的 inf 距离）记 1.0（最差），不产生 NaN；
        - 有限值全相等（含全 0）→ 该项对所有候选记 0（不参与区分）。
        """
        finite = [v for v in values if math.isfinite(v)]
        if not finite:
            return [0.0 for _ in values]
        lo = min(finite)
        hi = max(finite)
        if hi <= lo:
            return [0.0 if math.isfinite(v) else 1.0 for v in values]
        span = hi - lo
        return [((v - lo) / span) if math.isfinite(v) else 1.0 for v in values]
