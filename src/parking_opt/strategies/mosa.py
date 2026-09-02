from __future__ import annotations
"""MOSA：多目标智能车位分配（算法一接入）。

算法来源：新算法接入/算法一/mosa_full.py（NSGA-II 离线全信息多目标优化）。

接入说明（离线预分配策略）
----------------------------
MOSA 是离线全信息算法：需要完整车辆需求序列做全局优化，与在线策略的
信息条件不同。本文件按项目「离线预分配策略」模式接入：

  - 重写 BaseStrategy.prepare()：仿真开始前（SimulationEngine.run 开头自动调用）
    用 NSGA-II 对完整需求做多目标优化，把最优分配方案缓存到 self._plan；
  - assign() 只做「查表执行」：按计划车位分配，计划车位暂时被占则返回
    waiting 交给引擎排队重试，计划不可用/超规模时回退为贪心规则。

信息边界声明（项目硬约束）：prepare 会读取未来到达与真实停车时长
（parking_duration），因此本策略标注为「离线全信息对照基准」，与在线策略
对比时应视为上界参考（与 CP-SAT 离线基准定位一致），不是同信息条件的公平对比。

目标（与算法一文档一致）
------------------------
  f1: 总行驶时间（含移位与等待）
  f2: 总行驶距离（含移位）
  f3: 车位利用率均衡（STANDALONE / TANDEM 两类利用率方差越小越均衡）

场景权重：高峰重时间、平峰重距离、饱和重利用率（scene 可手动指定或 auto 判定）。
"""

import math

from ..domain.spot import Spot, SpotType, Vehicle
from ..simulation.parking_lot import ParkingLot
from .baselines import BaseStrategy
from ._mosa_constants import (PREPARE_TIME_BUDGET, SCENE_WEIGHTS,  # noqa: F401
                              SCENE_LABELS, REJECT_PENALTY)
from ._mosa_init import MosaInitMixin
from ._mosa_ops import MosaOpsMixin
from ._mosa_ga import MosaGaMixin
from ._mosa_scene import estimate_scene, resolve_scene  # noqa: F401


class MosaStrategy(MosaInitMixin, MosaOpsMixin, MosaGaMixin, BaseStrategy):
    """MOSA 多目标优化（离线全信息预分配）。

    prepare() 阶段用 NSGA-II 求 Pareto 前沿，再按场景权重选最优方案；
    assign() 阶段查表执行。规模超限或未 prepare 时回退为贪心规则。
    """

    name = "mosa"
    label = "MOSA 多目标优化（离线）"
    DESCRIPTION = (
        "**MOSA 多目标优化（离线全信息）**\n\n"
        "仿真开始前用 **NSGA-II** 对完整需求序列做全局多目标优化：\n"
        "f1 总行驶时间、f2 总行驶距离（含移位）、f3 车位利用率均衡；\n"
        "场景权重：高峰重时间、平峰重距离、饱和重利用率（可自动判定）。\n\n"
        "> ⚠️ 本算法为**离线全信息对照基准**（可读未来到达与真实停车时长），"
        "与在线策略（FCFS/贪心/时长感知等）信息条件不同，对比时作为上界参考，"
        "与 CP-SAT 离线基准定位一致。"
    )

    PARAMS = [
        {"key": "pop_size", "label": "种群规模", "type": "int",
         "min": 8, "max": 60, "step": 2, "default": 30,
         "help": "NSGA-II 种群个体数（原算法默认 30，越大越充分，耗时越长）"},
        {"key": "generations", "label": "进化代数", "type": "int",
         "min": 4, "max": 100, "step": 2, "default": 50,
         "help": "NSGA-II 进化代数（原算法默认 50，越大越充分，耗时越长）"},
        {"key": "scene", "label": "场景模式（自动判定）", "type": "choice",
         "options": [("auto", "自动判定（绑定车位/车辆/时间）"), ("peak", "高峰（重时间）"),
                     ("normal", "平峰（重距离）"), ("saturated", "饱和（重利用率）")],
         "default": "auto", "locked": True,
         "help": "场景权重由车位数、车辆数、停车时长自动判定（共 3 种：高峰重时间/平峰重距离/饱和重利用率），此控件不可手动调节"},
        {"key": "max_wait", "label": "评估等待上限(秒)", "type": "float",
         "min": 60.0, "max": 3600.0, "step": 60.0, "default": 1800.0,
         "help": "离线评估中车辆等待目标车位空出的时间上限（与引擎排队上限一致）"},
    ]

    def __init__(self, pop_size: int = 30, generations: int = 50,
                 scene: str = "auto", max_wait: float = 1800.0,
                 time_budget: float = PREPARE_TIME_BUDGET):
        self.pop_size = pop_size
        self.generations = generations
        self.scene = scene
        self.max_wait = max_wait
        self._time_budget = time_budget
        # prepare() 后生效：{vehicle_id: spot_id} 离线预分配方案；None 表示未优化（回退贪心）
        self._plan: dict[str, str] | None = None
        # {entry_id: {spot_id: dist}}：多入口下按车辆入口查表的预计算距离
        self._entry_dist: dict[str, dict[str, float]] = {}
        self._default_entry: str | None = None
        self._shift_dist_est: dict[str, float] = {}
        self._vehicles: list[Vehicle] = []
        self._spots: list[Spot] = []
        self._spots_by_id: dict[str, Spot] = {}

    # ========== 离线准备（全信息） ==========

    def prepare(self, vehicles: list[Vehicle], parking_lot: ParkingLot,
                path_engine) -> None:
        """仿真开始前调用：NSGA-II 全局优化，缓存最优分配方案。"""
        self._vehicles = list(vehicles)
        self._spots = list(parking_lot.spots.values())
        self._spots_by_id = {s.spot_id: s for s in self._spots}

        n_spots = len(self._spots)
        if n_spots == 0:
            self._plan = None  # 无车位：跳过优化，assign 回退贪心
            return

        # 预计算距离（评估器只查表，避免反复 Dijkstra）：按入口分表，车辆按自身入口查
        self._default_entry = path_engine.entry_id
        self._entry_dist = {}
        entry_ids = path_engine.entry_ids or [self._default_entry]
        for eid in entry_ids:
            table = {}
            for s in self._spots:
                d = path_engine.distance_to_spot(s.node_id, eid)
                table[s.spot_id] = d if math.isfinite(d) else float("inf")
            self._entry_dist[eid] = table

        self._shift_dist_est = self._build_shift_dist_est(path_engine)

        scene = self._resolve_scene(vehicles)
        self._plan = self._run_nsga2(scene, path_engine)

    def _dist_for(self, vehicle: Vehicle, spot_id: str) -> float:
        """该车按其入口查预计算距离；入口非法或无表时回退默认入口表。"""
        entry = getattr(vehicle, "entry_id", None)
        table = self._entry_dist.get(entry) if entry else None
        if table is None:
            table = self._entry_dist.get(self._default_entry, {})
        return table.get(spot_id, float("inf"))

    def _build_shift_dist_est(self, path_engine) -> dict[str, float]:
        """估计每个车位一次移位的往返距离（移到最近可用缓冲位再回位）。"""
        est = {}
        buffers = [s for s in self._spots
                   if s.spot_type == SpotType.STANDALONE or s.depth == 1]
        for s in self._spots:
            best = float("inf")
            for b in buffers:
                if b.spot_id == s.spot_id or b.stack_group_id == s.stack_group_id:
                    continue
                d = path_engine.shortest_distance(s.node_id, b.node_id)
                if math.isfinite(d) and d < best:
                    best = d
            if not math.isfinite(best):
                best = 10.0  # 兜底：找不到缓冲位时按 10m 估
            est[s.spot_id] = best * 2.0  # 往返
        return est

    def _resolve_scene(self, vehicles: list[Vehicle]) -> str:
        """scene=auto 时按真实车位与车辆需求判定：饱和 / 高峰 / 平峰。"""
        if self.scene != "auto":
            return self.scene
        return resolve_scene(len(self._spots), vehicles)

    # ========== 在线执行（查表） ==========

    def assign(self, vehicle: Vehicle, time: float, parking_lot: ParkingLot,
               path_engine) -> tuple[Spot | None, str]:
        """按离线方案查表分配；计划车位暂被占返回 waiting（等引擎重试），无计划回退贪心。"""
        if self._plan is not None and vehicle.vehicle_id in self._plan:
            spot_id = self._plan[vehicle.vehicle_id]
            spot = parking_lot.spots.get(spot_id)
            if spot is not None and not spot.is_occupied:
                return (spot, "assigned")
            if spot is None:
                # 计划车位不存在（理论不应发生）：回退贪心
                return self._greedy_assign(vehicle, parking_lot, path_engine)
            # 计划车位被占：排队等待（引擎会在车位空出后重试）
            return (None, "waiting")

        return self._greedy_assign(vehicle, parking_lot, path_engine)

    def _greedy_assign(self, vehicle: Vehicle, parking_lot: ParkingLot, path_engine):
        """回退贪心：独立车位 → 纵深外层 → 纵深里层，同类选最近。"""
        available = parking_lot.get_available_spots()
        if not available:
            return (None, "waiting")
        entry = getattr(vehicle, "entry_id", None)  # 多入口：按该车入口计距离
        standalone = [s for s in available if s.spot_type == SpotType.STANDALONE]
        depth1 = [s for s in available
                  if s.spot_type == SpotType.TANDEM and s.depth == 1]
        depth_n = [s for s in available
                   if s.spot_type == SpotType.TANDEM and s.depth > 1]
        for group in (standalone, depth1, depth_n):
            if group:
                best = min(group, key=lambda s: path_engine.distance_to_spot(s.node_id, entry))
                return (best, "assigned")
        return (available[0], "assigned")
