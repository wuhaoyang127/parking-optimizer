from __future__ import annotations
"""MOSA NSGA-II：初始化与主循环 mixin。"""

import math
import random
import time

from ..domain.spot import Spot, SpotType, Vehicle
from ..simulation.defaults import CAR_SPEED
from ._mosa_constants import SCENE_WEIGHTS


class MosaInitMixin:
    """NSGA-II 主循环、初始化解、染色体→方案转换。"""

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
        start_time = time.time()  # 时间熔断计时

        # 初始种群注入高质量贪心启发式解（最早空出车位），其余按场景引导随机
        pop: list = []
        pop.append(self._Individual(self._greedy_chromosome(rng, tie_break="nearest")))
        pop.append(self._Individual(self._greedy_chromosome(rng, tie_break="random")))
        while len(pop) < self.pop_size:
            pop.append(self._random_individual(rng, scene))
        for ind in pop:
            self._evaluate(ind)

        for _gen in range(self.generations):
            if time.time() - start_time > self._time_budget:
                break  # 时间熔断：停止进化，用当前种群选最优
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

    def _select_best(self, pareto: list, scene: str):
        """按场景权重从 Pareto 前沿选最优：三目标先 min-max 归一化再加权（与原算法一致）。"""
        w = SCENE_WEIGHTS.get(scene, SCENE_WEIGHTS["normal"])
        f1s = [p.objectives[0] for p in pareto]
        f2s = [p.objectives[1] for p in pareto]
        f3s = [p.objectives[2] for p in pareto]
        min_f1, max_f1 = min(f1s), max(f1s)
        min_f2, max_f2 = min(f2s), max(f2s)
        min_f3, max_f3 = min(f3s), max(f3s)

        def score(ind) -> float:
            n1 = 0.0 if max_f1 == min_f1 else (ind.objectives[0] - min_f1) / (max_f1 - min_f1)
            n2 = 0.0 if max_f2 == min_f2 else (ind.objectives[1] - min_f2) / (max_f2 - min_f2)
            n3 = 0.0 if max_f3 == min_f3 else (ind.objectives[2] - min_f3) / (max_f3 - min_f3)
            return (w["f1"] * n1 + w["f2"] * n2 + w["f3"] * n3)

        return min(pareto, key=score)

    def _random_individual(self, rng: random.Random, scene: str):
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
                dist = self._dist_for(v, gene)
                enter = (max(v.arrival_time, occupied_until.get(gene, -1.0))
                         + dist / CAR_SPEED)
                occupied_until[gene] = enter + v.parking_duration
        return self._Individual(chrom)

    def _greedy_chromosome(self, rng: random.Random,
                           tie_break: str = "nearest") -> list:
        """高质量启发式解：按到达顺序把每辆车分到「最早空出」的可行车位。"""
        occupied_until: dict[str, float] = {}
        chrom = []
        for v in self._vehicles:
            options = []
            for s in self._spots:
                dist = self._dist_for(v, s.spot_id)
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
