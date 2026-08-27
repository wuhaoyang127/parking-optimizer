"""第一版实验：risk_scoring 与 nearest / greedy / duration_greedy 的公平对比。

- 同一需求序列（相同 seed）喂给所有策略，避免随机需求造成不公平；
- 三档需求强度（低/中/高）× 多 seed 取均值；
- 附 risk_scoring 权重小扫描，用于据均值（不挑 seed）确定默认权重。

用法：
    python scripts/exp_risk_scoring.py
产出：
    outputs/exp_risk_scoring_summary.md   # 汇总对比表（markdown）
    outputs/exp_risk_scoring_raw.csv      # 每 (强度,策略,seed) 明细
"""

from __future__ import annotations

import csv
import os
import statistics
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.parking_opt.domain.spot import (RoadNetwork, RoadNode, NodeType,
                                         Spot, SpotType)
from src.parking_opt.routing.path_engine import PathEngine
from src.parking_opt.simulation.parking_lot import ParkingLot
from src.parking_opt.simulation.engine import SimulationEngine
from src.parking_opt.simulation.arrival import generate_demand
from src.parking_opt.evaluation.metrics import compute_metrics
from src.parking_opt.strategies.baselines import NearestPath
from src.parking_opt.strategies.greedy import GreedyStrategy, DurationAwareGreedy
from src.parking_opt.strategies.risk_scoring import RiskScoringStrategy


def build_layout(n_standalone: int = 50, n_tandem_groups: int = 25):
    """构造约 100 车位的混合布局：独立位 + 2 深纵深组，双侧挂在中央通道上。

    返回 (RoadNetwork, list[Spot])，保证每个车位从入口可达且可返回入口。
    """
    net = RoadNetwork()

    def an(nid, nt, x, y, st=None, sg=None, dp=None):
        net.add_node(RoadNode(nid, nt, x, y, st, sg, dp))

    an("ENTRY", NodeType.ENTRY, 0, 0)
    spots: list[Spot] = []

    # 中央通道脊柱：ENTRY - M0 - M1 - ... 每段 6m（越深越远）
    n_cols = max(1, (n_standalone + n_tandem_groups + 1) // 2)
    prev = "ENTRY"
    aisle = []
    for c in range(n_cols):
        mid = f"M{c}"
        an(mid, NodeType.ROAD_NODE, 6 * (c + 1), 0)
        net.add_edge(prev, mid, 6.0)
        net.add_edge(mid, prev, 6.0)
        aisle.append(mid)
        prev = mid

    # 交替把独立位/纵深组挂到通道节点两侧
    stand_left = n_standalone
    tandem_left = n_tandem_groups
    col = 0
    side = 1
    si = 0
    gi = 0
    while stand_left > 0 or tandem_left > 0:
        mid = aisle[col % n_cols]
        y = 4 * side
        put_tandem = (tandem_left > 0) and (stand_left == 0 or (si + gi) % 3 == 2)
        if put_tandem:
            gid = f"G{gi}"
            outer = f"{gid}-1"
            inner = f"{gid}-2"
            an(outer, NodeType.PARKING_SPOT, aisle_x(mid, net) + 3, y,
               SpotType.TANDEM, gid, 1)
            an(inner, NodeType.PARKING_SPOT, aisle_x(mid, net) + 6, y,
               SpotType.TANDEM, gid, 2)
            net.add_edge(mid, outer, 3.0)
            net.add_edge(outer, mid, 3.0)
            net.add_edge(outer, inner, 3.0)
            net.add_edge(inner, outer, 3.0)
            spots.append(Spot(outer, SpotType.TANDEM, outer, gid, 1))
            spots.append(Spot(inner, SpotType.TANDEM, inner, gid, 2))
            tandem_left -= 1
            gi += 1
        else:
            sid = f"S{si}"
            an(sid, NodeType.PARKING_SPOT, aisle_x(mid, net) + 3, y,
               SpotType.STANDALONE, sid, 1)
            net.add_edge(mid, sid, 3.0)
            net.add_edge(sid, mid, 3.0)
            spots.append(Spot(sid, SpotType.STANDALONE, sid, sid, 1))
            stand_left -= 1
            si += 1
        side *= -1
        if side == 1:
            col += 1
    return net, spots


def aisle_x(node_id: str, net: RoadNetwork) -> float:
    return net.nodes[node_id].x


def run_once(net, spots, vehicles, strategy, seed):
    pe = PathEngine(net)
    lot = ParkingLot([Spot(s.spot_id, s.spot_type, s.node_id, s.stack_group_id,
                           s.depth) for s in spots])
    events = SimulationEngine(lot, pe, vehicles, strategy, seed=seed).run()
    return compute_metrics(events, len(spots))


METRIC_KEYS = ["satisfaction_rate", "spatial_utilization", "shift_count",
               "shift_distance_m", "total_drive_distance_m", "avg_wait_time_s",
               "rejected_count"]


def strategy_factories():
    return {
        "nearest": lambda: NearestPath(),
        "greedy": lambda: GreedyStrategy(),
        "duration_greedy": lambda: DurationAwareGreedy(),
        "risk_scoring": lambda: RiskScoringStrategy(),  # 默认权重
    }


def avg(rows, key):
    return statistics.mean(r[key] for r in rows)


def main():
    net, spots = build_layout()
    n_spots = len(spots)
    intensities = {"低": 60, "中": 100, "高": 140}
    seeds = [42, 43, 44, 45, 46]
    factories = strategy_factories()

    raw_rows = []
    summary = {}  # (intensity, strat) -> averaged metrics

    for iname, nveh in intensities.items():
        demands = {s: generate_demand(total_vehicles=nveh, seed=s) for s in seeds}
        for strat, factory in factories.items():
            per_seed = []
            for s in seeds:
                m = run_once(net, spots, demands[s], factory(), s)
                m2 = {k: m[k] for k in METRIC_KEYS}
                per_seed.append(m2)
                raw_rows.append({"intensity": iname, "n_vehicles": nveh,
                                 "strategy": strat, "seed": s, **m2})
            summary[(iname, strat)] = {k: avg(per_seed, k) for k in METRIC_KEYS}

    # ---- 权重扫描（中强度，据均值确定默认，不挑 seed）----
    sweep = []
    nveh = intensities["中"]
    demands = {s: generate_demand(total_vehicles=nveh, seed=s) for s in seeds}
    weight_grid = [(1, 0, 0), (1, 1, 0), (1, 1.5, 0.5), (1, 2, 1),
                   (0.5, 2, 0.5), (1, 3, 1), (0, 1, 0)]
    for wd, wr, wp in weight_grid:
        per_seed = []
        for s in seeds:
            m = run_once(net, spots, demands[s],
                         RiskScoringStrategy(wd, wr, wp), s)
            per_seed.append({k: m[k] for k in METRIC_KEYS})
        sweep.append(((wd, wr, wp), {k: avg(per_seed, k) for k in METRIC_KEYS}))

    _write_outputs(n_spots, intensities, seeds, summary, sweep, raw_rows)
    _print_console(n_spots, intensities, summary, sweep)


def _fmt_table(strats, rows):
    header = ("| 策略 | 满足率 | 利用率 | 移位次数 | 移位距离(m) | "
              "行驶距离(m) | 平均等待(s) | 拒绝数 |")
    sep = "|---|---|---|---|---|---|---|---|"
    lines = [header, sep]
    for strat in strats:
        m = rows[strat]
        lines.append(
            f"| {strat} | {m['satisfaction_rate']:.3f} | "
            f"{m['spatial_utilization']:.3f} | {m['shift_count']:.1f} | "
            f"{m['shift_distance_m']:.0f} | {m['total_drive_distance_m']:.0f} | "
            f"{m['avg_wait_time_s']:.1f} | {m['rejected_count']:.1f} |")
    return "\n".join(lines)


def _write_outputs(n_spots, intensities, seeds, summary, sweep, raw_rows):
    os.makedirs("outputs", exist_ok=True)
    strats = list(strategy_factories().keys())
    md = [f"# risk_scoring 第一版实验汇总\n",
          f"- 车位数：{n_spots}；seeds：{seeds}（每格取均值）；同一 seed 下四策略"
          f"喂相同需求序列。\n"]
    for iname, nveh in intensities.items():
        md.append(f"\n## {iname}需求强度（{nveh} 辆车，车位 {n_spots}）\n")
        md.append(_fmt_table(strats, {s: summary[(iname, s)] for s in strats}))
    md.append("\n\n## risk_scoring 权重扫描（中强度，均值）\n")
    md.append("| (w_d,w_r,w_p) | 满足率 | 利用率 | 移位次数 | 移位距离(m) | "
              "行驶距离(m) | 平均等待(s) | 拒绝数 |")
    md.append("|---|---|---|---|---|---|---|---|")
    for w, m in sweep:
        md.append(
            f"| {w} | {m['satisfaction_rate']:.3f} | {m['spatial_utilization']:.3f} | "
            f"{m['shift_count']:.1f} | {m['shift_distance_m']:.0f} | "
            f"{m['total_drive_distance_m']:.0f} | {m['avg_wait_time_s']:.1f} | "
            f"{m['rejected_count']:.1f} |")
    with open("outputs/exp_risk_scoring_summary.md", "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")

    with open("outputs/exp_risk_scoring_raw.csv", "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["intensity", "n_vehicles", "strategy",
                                          "seed"] + METRIC_KEYS)
        w.writeheader()
        w.writerows(raw_rows)


def _print_console(n_spots, intensities, summary, sweep):
    strats = list(strategy_factories().keys())
    print(f"\n=== risk_scoring 第一版实验（车位 {n_spots}）===")
    for iname, nveh in intensities.items():
        print(f"\n--- {iname}需求（{nveh} 辆）---")
        print(_fmt_table(strats, {s: summary[(iname, s)] for s in strats}))
    print("\n--- 权重扫描（中强度均值）---")
    for w, m in sweep:
        print(f"{w}: sat={m['satisfaction_rate']:.3f} util={m['spatial_utilization']:.3f} "
              f"shifts={m['shift_count']:.1f} shiftdist={m['shift_distance_m']:.0f} "
              f"drive={m['total_drive_distance_m']:.0f} wait={m['avg_wait_time_s']:.1f} "
              f"rej={m['rejected_count']:.1f}")


if __name__ == "__main__":
    main()
