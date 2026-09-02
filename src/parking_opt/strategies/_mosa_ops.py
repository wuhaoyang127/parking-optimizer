from __future__ import annotations
"""MOSA NSGA-II：染色体可行位/场景选择与评估 mixin。"""

import math
import random

from ..domain.spot import SpotType
from ..simulation.defaults import CAR_SPEED
from ._mosa_constants import REJECT_PENALTY


class MosaOpsMixin:
    """可行车位筛选、场景引导选择、时间轴评估。"""

    def _spot_by_id(self, spot_id: str):
        return self._spots_by_id.get(spot_id)

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
                dist = self._dist_for(veh, gene)
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
            dist = self._dist_for(v, s.spot_id)
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

    def _evaluate(self, ind) -> None:
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
            dist = self._dist_for(v, gene)
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
