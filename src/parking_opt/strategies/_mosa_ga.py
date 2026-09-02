from __future__ import annotations
"""MOSA NSGA-II：支配排序/拥挤度/选择/交叉/变异 mixin。"""

import random


class MosaGaMixin:
    """Pareto 支配排序、拥挤距离、锦标赛选择、均匀交叉、场景变异。"""

    def _dominates(self, a, b) -> bool:
        better = False
        for i in range(3):
            if a.objectives[i] > b.objectives[i]:
                return False
            if a.objectives[i] < b.objectives[i]:
                better = True
        return better

    def _nondominated_sort(self, pop: list) -> list[list]:
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

    def _crowding_distance(self, front: list) -> None:
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

    def _tournament(self, pop: list, rng: random.Random):
        a, b = rng.sample(pop, 2)
        return a if (a.rank, -a.crowding) < (b.rank, -b.crowding) else b

    def _crossover(self, a, b, rng: random.Random) -> tuple:
        """均匀交叉：每个可变基因以 50% 概率交换（车位可重复，无需 PMX 修复）。"""
        ca = a.chromosome.copy()
        cb = b.chromosome.copy()
        for i in range(len(ca)):
            if rng.random() < 0.5:
                ca[i], cb[i] = cb[i], ca[i]
        return self._Individual(ca), self._Individual(cb)

    def _mutate(self, ind, rng: random.Random, scene: str):
        """变异：随机改一个基因，按场景引导选新车位（与原算法 mutate 对齐）。"""
        chrom = ind.chromosome.copy()
        if not chrom:
            return ind
        i = rng.randrange(len(chrom))
        feasible = self._feasible_spots_for_chrom(chrom, i)
        chrom[i] = self._pick_by_scene(feasible, chrom, i, scene, rng)
        return self._Individual(chrom)
