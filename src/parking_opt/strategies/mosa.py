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
import random

from ..domain.spot import Spot, SpotType, Vehicle
from ..simulation.parking_lot import ParkingLot
from ..simulation.defaults import CAR_SPEED
from .baselines import BaseStrategy

# 规模保护：超过上限跳过 NSGA-II（回退贪心），保证网页交互不卡死
MAX_SPOTS = 60
MAX_VEHICLES = 120

# 场景权重（f1 时间 / f2 距离 / f3 利用率均衡）
SCENE_WEIGHTS = {
    "peak": {"f1": 0.6, "f2": 0.2, "f3": 0.2},
    "normal": {"f1": 0.2, "f2": 0.6, "f3": 0.2},
    "saturated": {"f1": 0.2, "f2": 0.2, "f3": 0.6},
}

SCENE_LABELS = {
    "peak": "高峰（重时间）",
    "normal": "平峰（重距离）",
    "saturated": "饱和（重利用率）",
}

REJECT_PENALTY = 1000.0  # 拒绝一辆车的惩罚（加到 f1/f2，与原算法 mosa_full.py 一致）


def estimate_scene(n_spots: int, n_vehicles: int, sim_duration: float,
                   avg_duration: float) -> str:
    """按车位数/车辆数/时间预估场景权重模式（与 _resolve_scene 同一判定规则）。

    三种情况：高峰（重时间）/ 平峰（重距离）/ 饱和（重利用率）。
    UI 在运行前用本函数做预估展示；运行时 MosaStrategy 按真实生成车辆精确判定。
    """
    if n_spots <= 0 or n_vehicles <= 0 or sim_duration <= 0:
        return "normal"
    total_demand_time = n_vehicles * max(avg_duration, 1.0)
    span = sim_duration + max(avg_duration, 1.0)  # 近似时间跨度（最后到达 + 平均停车）
    demand_ratio = total_demand_time / (n_spots * span)
    if demand_ratio >= 0.85:
        return "saturated"
    if demand_ratio >= 0.6:
        return "peak"
    return "normal"


class MosaStrategy(BaseStrategy):
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
                 scene: str = "auto", max_wait: float = 1800.0):
        self.pop_size = pop_size
        self.generations = generations
        self.scene = scene
        self.max_wait = max_wait
        # prepare() 后生效：{vehicle_id: spot_id} 离线预分配方案；None 表示未优化（回退贪心）
        self._plan: dict[str, str] | None = None
        self._entry_dist: dict[str, float] = {}
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

        n_vehicles = len(vehicles)
        n_spots = len(self._spots)
        if n_spots == 0 or n_spots > MAX_SPOTS or n_vehicles > MAX_VEHICLES:
            self._plan = None  # 超规模：跳过优化，assign 回退贪心
            return

        # 预计算距离（评估器只查表，避免反复 Dijkstra）
        self._entry_dist = {}
        for s in self._spots:
            d = path_engine.distance_to_spot(s.node_id)
            self._entry_dist[s.spot_id] = d if math.isfinite(d) else float("inf")

        self._shift_dist_est = self._build_shift_dist_est(path_engine)

        scene = self._resolve_scene(vehicles)
        self._plan = self._run_nsga2(scene, path_engine)

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
        """scene=auto 时按需求密度判定：饱和 / 高峰 / 平峰。"""
        if self.scene != "auto":
            return self.scene
        if not vehicles:
            return "normal"
        n_spots = len(self._spots)
        if n_spots == 0:
            return "normal"
        total_demand_time = sum(v.parking_duration for v in vehicles)
        span = (max(v.departure_time for v in vehicles)
                - min(v.arrival_time for v in vehicles))
        if span <= 0:
            return "peak"
        demand_ratio = total_demand_time / (n_spots * span)
        if demand_ratio >= 0.85:
            return "saturated"
        if demand_ratio >= 0.6:
            return "peak"
        return "normal"

    # ========== NSGA-II ==========

    class _Individual:
        __slots__ = ("chromosome", "objectives", "rank", "crowding")

        def __init__(self, chromosome):
            self.chromosome = chromosome  # list[spot_id | None]，与按到达排序的车辆对齐
            self.objectives = [0.0, 0.0, 0.0]
            self.rank = 0
            self.crowding = 0.0

    def _run_nsga2(self, scene: str, path_engine) -> dict[str, str]:
        """NSGA-II 主循环，返回 {vehicle_id: spot_id} 最优分配方案。

        与原算法 mosa_full.py 一致：进化过程按 Pareto 支配排序，最终从
        Pareto 前沿（rank 0）按场景权重做 min-max 归一化加权选最优解。
        """
        rng = random.Random(42)  # 固定种子：相同需求序列可复现

        # 初始种群注入高质量贪心启发式解（最早空出车位），其余按场景引导随机
        pop: list["MosaStrategy._Individual"] = []
        pop.append(self._Individual(self._greedy_chromosome(rng, tie_break="nearest")))
        pop.append(self._Individual(self._greedy_chromosome(rng, tie_break="random")))
        while len(pop) < self.pop_size:
            pop.append(self._random_individual(rng, scene))
        for ind in pop:
            self._evaluate(ind)

        for _gen in range(self.generations):
            fronts = self._nondominated_sort(pop)
            for f in fronts:
                self._crowding_distance(f)
            offspring = []
            while len(offspring) < self.pop_size:
                pa = self._tournament(pop, rng)
                pb = self._tournament(pop, rng)
                ca, cb = self._crossover(pa, pb, rng)
                ca = self._mutate(ca, rng, scene)
                cb = self._mutate(cb, rng, scene)
                self._evaluate(ca)
                self._evaluate(cb)
                offspring.extend([ca, cb])
            combined = pop + offspring[:self.pop_size]
            fronts = self._nondominated_sort(combined)
            for f in fronts:
                self._crowding_distance(f)
            new_pop = []
            for f in fronts:
                if len(new_pop) + len(f) <= self.pop_size:
                    new_pop.extend(f)
                else:
                    f.sort(key=lambda x: -x.crowding)
                    new_pop.extend(f[:self.pop_size - len(new_pop)])
                    break
            pop = new_pop

        pareto = [p for p in pop if p.rank == 0] or pop
        best = self._select_best(pareto, scene)
        return self._chromosome_to_plan(best.chromosome)

    def _chromosome_to_plan(self, chromosome: list) -> dict[str, str]:
        """染色体 → {vehicle_id: spot_id}（跳过拒绝位 None）。"""
        plan = {}
        for v, gene in zip(self._vehicles, chromosome):
            if gene is not None:
                plan[v.vehicle_id] = gene
        return plan

    def _select_best(self, pareto: list["_Individual"], scene: str) -> "_Individual":
        """按场景权重从 Pareto 前沿选最优：三目标先 min-max 归一化再加权（与原算法一致）。"""
        w = SCENE_WEIGHTS.get(scene, SCENE_WEIGHTS["normal"])
        f1s = [p.objectives[0] for p in pareto]
        f2s = [p.objectives[1] for p in pareto]
        f3s = [p.objectives[2] for p in pareto]
        min_f1, max_f1 = min(f1s), max(f1s)
        min_f2, max_f2 = min(f2s), max(f2s)
        min_f3, max_f3 = min(f3s), max(f3s)

        def score(ind: "_Individual") -> float:
            n1 = 0.0 if max_f1 == min_f1 else (ind.objectives[0] - min_f1) / (max_f1 - min_f1)
            n2 = 0.0 if max_f2 == min_f2 else (ind.objectives[1] - min_f2) / (max_f2 - min_f2)
            n3 = 0.0 if max_f3 == min_f3 else (ind.objectives[2] - min_f3) / (max_f3 - min_f3)
            return (w["f1"] * n1 + w["f2"] * n2 + w["f3"] * n3)

        return min(pareto, key=score)

    def _random_individual(self, rng: random.Random, scene: str) -> "_Individual":
        """按场景引导的随机初始化（与原算法 create_individual 对齐）：

        peak 选最近可行、saturated 选类型均衡、normal 随机可行；无可行车位则拒绝（None）。
        """
        chrom = []
        occupied_until: dict[str, float] = {}
        for idx, v in enumerate(self._vehicles):
            feasible = self._feasible_spots_for_chrom(chrom, idx, occupied_until)
            gene = self._pick_by_scene(feasible, chrom, idx, scene, rng)
            chrom.append(gene)
            if gene is not None:
                dist = self._entry_dist.get(gene, 0.0)
                enter = (max(v.arrival_time, occupied_until.get(gene, -1.0))
                         + dist / CAR_SPEED)
                occupied_until[gene] = enter + v.parking_duration
        return self._Individual(chrom)

    def _spot_by_id(self, spot_id: str) -> Spot | None:
        return self._spots_by_id.get(spot_id)

    def _greedy_chromosome(self, rng: random.Random,
                           tie_break: str = "nearest") -> list:
        """高质量启发式解：按到达顺序把每辆车分到「最早空出」的可行车位。"""
        occupied_until: dict[str, float] = {}
        chrom = []
        for v in self._vehicles:
            options = []
            for s in self._spots:
                dist = self._entry_dist.get(s.spot_id, float("inf"))
                if not math.isfinite(dist):
                    continue
                prev_end = occupied_until.get(s.spot_id, -1.0)
                if prev_end <= v.arrival_time:
                    wait = 0.0
                    new_end = v.arrival_time + dist / CAR_SPEED + v.parking_duration
                else:
                    wait = prev_end - v.arrival_time
                    if wait > self.max_wait:
                        continue
                    new_end = prev_end + dist / CAR_SPEED + v.parking_duration
                options.append((wait, dist, s.spot_id, new_end))
            if not options:
                chrom.append(None)
                continue
            if tie_break == "random":
                rng.shuffle(options)
                options.sort(key=lambda x: x[0])
            else:  # nearest：等待最少优先，其次距离近
                options.sort(key=lambda x: (x[0], x[1]))
            gene = options[0][2]
            chrom.append(gene)
            occupied_until[gene] = options[0][3]
        return chrom

    def _feasible_spots_for_chrom(self, chrom: list, idx: int,
                                  occupied_until: dict | None = None) -> list:
        """为 idx 车辆返回可行车位列表 [(spot_id, wait, dist)]（等待 ≤ max_wait）。

        传入 occupied_until 时直接使用（初始化逐步构建）；否则按 chrom 重建时间轴。
        """
        v = self._vehicles[idx]
        if occupied_until is None:
            occupied_until = {}
            for j, (veh, gene) in enumerate(zip(self._vehicles, chrom)):
                if j == idx or gene is None:
                    continue
                dist = self._entry_dist.get(gene, float("inf"))
                if not math.isfinite(dist):
                    continue
                prev_end = occupied_until.get(gene, -1.0)
                wait = max(0.0, prev_end - veh.arrival_time)
                if wait > self.max_wait:
                    continue
                occupied_until[gene] = (max(veh.arrival_time, prev_end)
                                        + dist / CAR_SPEED + veh.parking_duration)

        out = []
        for s in self._spots:
            dist = self._entry_dist.get(s.spot_id, float("inf"))
            if not math.isfinite(dist):
                continue
            prev_end = occupied_until.get(s.spot_id, -1.0)
            wait = max(0.0, prev_end - v.arrival_time)
            if wait > self.max_wait:
                continue
            out.append((s.spot_id, wait, dist))
        return out

    def _pick_by_scene(self, feasible: list, chrom: list, idx: int,
                       scene: str, rng: random.Random):
        """按场景从可行车位中选一个（与原算法 create_individual/mutate 对齐）：

        peak 选最近、saturated 选类型均衡、normal 随机；无可行返回 None（拒绝）。
        """
        if not feasible:
            return None
        if scene == "peak":
            # 高峰重时间：选距离入口最近的可行车位
            return min(feasible, key=lambda x: (x[2], x[1]))[0]
        if scene == "saturated":
            # 饱和重利用率：选类型剩余容量最多的可行车位
            return self._balanced_pick(feasible, chrom, idx, rng)
        # 平峰：随机可行
        return rng.choice(feasible)[0]

    def _balanced_pick(self, feasible: list, chrom: list, idx: int,
                       rng: random.Random):
        """类型均衡选择（原算法 _balanced_spot）：统计当前染色体各类型占用，
        选剩余容量最多的类型，再从该类型可行车位中随机选。"""
        cap = {SpotType.STANDALONE: 0, SpotType.TANDEM: 0}
        used = {SpotType.STANDALONE: 0, SpotType.TANDEM: 0}
        for s in self._spots:
            cap[s.spot_type] += 1
        for j, gene in enumerate(chrom):
            if j == idx or gene is None:
                continue
            sp = self._spot_by_id(gene)
            if sp is not None:
                used[sp.spot_type] += 1
        remaining = {t: cap[t] - used[t] for t in cap}
        max_rem = max(remaining.values())
        cand_types = [t for t, rem in remaining.items() if rem == max_rem]
        chosen_type = rng.choice(cand_types)
        of_type = [x for x in feasible
                   if self._spot_by_id(x[0]).spot_type == chosen_type]
        pool = of_type if of_type else feasible
        return rng.choice(pool)[0]

    def _evaluate(self, ind: "_Individual") -> None:
        """轻量时间轴模拟：车位独占 + 等待 + 纵深移位估计。"""
        n_rejected = 0
        total_drive_dist = 0.0
        total_wait = 0.0
        occupied_until: dict[str, float] = {}
        records: list[dict] = []  # {spot_id, depth, group, enter, leave}

        for v, gene in zip(self._vehicles, ind.chromosome):
            if gene is None:
                n_rejected += 1
                continue
            dist = self._entry_dist.get(gene, float("inf"))
            if not math.isfinite(dist):
                n_rejected += 1
                continue
            spot = self._spot_by_id(gene)
            if spot is None:
                n_rejected += 1
                continue

            drive_time = dist / CAR_SPEED
            prev_end = occupied_until.get(gene, -1.0)
            if prev_end <= v.arrival_time:
                wait = 0.0
                enter = v.arrival_time + drive_time
            else:
                wait = prev_end - v.arrival_time
                if wait > self.max_wait:
                    n_rejected += 1
                    continue
                enter = prev_end + drive_time
            leave = enter + v.parking_duration
            occupied_until[gene] = leave

            total_drive_dist += dist
            total_wait += wait
            records.append({"spot_id": gene, "spot_type": spot.spot_type,
                            "stack_group_id": spot.stack_group_id,
                            "depth": spot.depth, "enter": enter, "leave": leave})

        # 移位估计：里层车离场时，同组外层车仍在场 → 需要移位让行
        shift_count = 0
        shift_dist = 0.0
        by_group: dict[str, list[dict]] = {}
        for r in records:
            if r["spot_type"] == SpotType.TANDEM:
                by_group.setdefault(r["stack_group_id"], []).append(r)
        for group_recs in by_group.values():
            for inner in group_recs:
                for outer in group_recs:
                    if outer["depth"] >= inner["depth"]:
                        continue
                    # 外层车在里层车离场时刻仍在场（阻挡）
                    if outer["enter"] <= inner["leave"] < outer["leave"]:
                        shift_count += 1
                        shift_dist += self._shift_dist_est.get(
                            outer["spot_id"], 20.0)

        total_dist = total_drive_dist + shift_dist
        total_time = (total_drive_dist + shift_dist) / CAR_SPEED + total_wait

        # f3：类型利用率均衡（占用时间 / 类型容量 × 时间跨度）
        balance = self._type_balance(records)

        penalty = n_rejected * REJECT_PENALTY
        ind.objectives[0] = total_time + penalty
        ind.objectives[1] = total_dist + penalty
        ind.objectives[2] = -balance

    def _type_balance(self, records: list[dict]) -> float:
        """两类车位利用率均衡度：1/(1+sqrt(var))，越均衡越大。"""
        if not records:
            return 0.0
        t_min = min(r["enter"] for r in records)
        t_max = max(r["leave"] for r in records)
        span = max(t_max - t_min, 1.0)
        cap = {SpotType.STANDALONE: 0, SpotType.TANDEM: 0}
        used = {SpotType.STANDALONE: 0.0, SpotType.TANDEM: 0.0}
        for s in self._spots:
            cap[s.spot_type] += 1
        for r in records:
            used[r["spot_type"]] += r["leave"] - r["enter"]
        utils = []
        for t in (SpotType.STANDALONE, SpotType.TANDEM):
            if cap[t] > 0:
                utils.append(used[t] / (cap[t] * span))
        if not utils:
            return 0.0
        mean = sum(utils) / len(utils)
        var = sum((u - mean) ** 2 for u in utils) / len(utils)
        return 1.0 / (1.0 + math.sqrt(var))

    def _dominates(self, a: "_Individual", b: "_Individual") -> bool:
        better = False
        for i in range(3):
            if a.objectives[i] > b.objectives[i]:
                return False
            if a.objectives[i] < b.objectives[i]:
                better = True
        return better

    def _nondominated_sort(self, pop: list["_Individual"]) -> list[list["_Individual"]]:
        fronts: list[list] = [[]]
        dom_count = [0] * len(pop)
        dom_set: list[list] = [[] for _ in pop]
        for i, p in enumerate(pop):
            for j, q in enumerate(pop):
                if i == j:
                    continue
                if self._dominates(p, q):
                    dom_set[i].append(j)
                elif self._dominates(q, p):
                    dom_count[i] += 1
            if dom_count[i] == 0:
                p.rank = 0
                fronts[0].append(p)
        k = 0
        while fronts[k]:
            nxt = []
            for i, p in enumerate(pop):
                if p in fronts[k]:
                    for j in dom_set[i]:
                        dom_count[j] -= 1
                        if dom_count[j] == 0:
                            pop[j].rank = k + 1
                            nxt.append(pop[j])
            k += 1
            fronts.append(nxt)
        return fronts[:-1]

    def _crowding_distance(self, front: list["_Individual"]) -> None:
        if len(front) <= 2:
            for ind in front:
                ind.crowding = float("inf")
            return
        for ind in front:
            ind.crowding = 0.0
        for m in range(3):
            front.sort(key=lambda x: x.objectives[m])
            front[0].crowding = float("inf")
            front[-1].crowding = float("inf")
            fmin = front[0].objectives[m]
            fmax = front[-1].objectives[m]
            if fmax - fmin <= 0:
                continue
            for i in range(1, len(front) - 1):
                front[i].crowding += (
                    front[i + 1].objectives[m] - front[i - 1].objectives[m]
                ) / (fmax - fmin)

    def _tournament(self, pop: list["_Individual"], rng: random.Random) -> "_Individual":
        a, b = rng.sample(pop, 2)
        return a if (a.rank, -a.crowding) < (b.rank, -b.crowding) else b

    def _crossover(self, a: "_Individual", b: "_Individual",
                   rng: random.Random) -> tuple["_Individual", "_Individual"]:
        """均匀交叉：每个可变基因以 50% 概率交换（车位可重复，无需 PMX 修复）。"""
        ca = a.chromosome.copy()
        cb = b.chromosome.copy()
        for i in range(len(ca)):
            if rng.random() < 0.5:
                ca[i], cb[i] = cb[i], ca[i]
        return self._Individual(ca), self._Individual(cb)

    def _mutate(self, ind: "_Individual", rng: random.Random,
                scene: str) -> "_Individual":
        """变异：随机改一个基因，按场景引导选新车位（与原算法 mutate 对齐）。"""
        chrom = ind.chromosome.copy()
        if not chrom:
            return ind
        i = rng.randrange(len(chrom))
        feasible = self._feasible_spots_for_chrom(chrom, i)
        chrom[i] = self._pick_by_scene(feasible, chrom, i, scene, rng)
        return self._Individual(chrom)

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
                return self._greedy_assign(parking_lot, path_engine)
            # 计划车位被占：排队等待（引擎会在车位空出后重试）
            return (None, "waiting")

        return self._greedy_assign(parking_lot, path_engine)

    def _greedy_assign(self, parking_lot: ParkingLot, path_engine):
        """回退贪心：独立车位 → 纵深外层 → 纵深里层，同类选最近。"""
        available = parking_lot.get_available_spots()
        if not available:
            return (None, "waiting")
        standalone = [s for s in available if s.spot_type == SpotType.STANDALONE]
        depth1 = [s for s in available
                  if s.spot_type == SpotType.TANDEM and s.depth == 1]
        depth_n = [s for s in available
                   if s.spot_type == SpotType.TANDEM and s.depth > 1]
        for group in (standalone, depth1, depth_n):
            if group:
                best = min(group, key=lambda s: path_engine.distance_to_spot(s.node_id))
                return (best, "assigned")
        return (available[0], "assigned")
