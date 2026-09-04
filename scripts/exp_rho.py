"""第一版实验：RHO 滚动时域动态修正（算法三）与在线基线的公平对比。

- 同一需求序列（相同 seed）喂给所有策略，避免随机需求造成不公平；
- 三档需求强度（低/中/高）× 多 seed 取均值；
- RHO 为在线策略：只统计已到达车辆做滚动预测，不读未来需求与真实停车时长，
  与 nearest / duration_greedy / risk_scoring 同属在线信息条件，公平可比；
- 附 RHO 阈值小扫描，用于据均值（不挑 seed）校验默认 (0.2, 0.5)。

用法：
    python scripts/exp_rho.py
产出：
    outputs/exp_rho_summary.md   # 汇总对比表（markdown）
    outputs/exp_rho_raw.csv      # 每 (强度,策略,seed) 明细
"""

import csv
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.exp_risk_scoring_lib import build_layout, run_once, avg, METRIC_KEYS  # noqa: E402
from src.parking_opt.simulation.arrival import generate_demand  # noqa: E402
from src.parking_opt.strategies.baselines import NearestPath  # noqa: E402
from src.parking_opt.strategies.greedy import DurationAwareGreedy  # noqa: E402
from src.parking_opt.strategies.risk_scoring import RiskScoringStrategy  # noqa: E402
from src.parking_opt.strategies.rho import RhoRollingStrategy  # noqa: E402

STRATS = ["nearest", "duration_greedy", "risk_scoring", "rho_rolling"]


def strategy_factories():
    return {
        "nearest": lambda: NearestPath(),
        "duration_greedy": lambda: DurationAwareGreedy(),
        "risk_scoring": lambda: RiskScoringStrategy(),
        "rho_rolling": lambda: RhoRollingStrategy(),
    }


def fmt_table(rows):
    header = ("| 策略 | 满足率 | 利用率 | 移位次数 | 移位距离(m) | "
              "行驶距离(m) | 平均等待(s) | 拒绝数 |")
    sep = "|---|---|---|---|---|---|---|---|"
    lines = [header, sep]
    for strat in STRATS:
        m = rows[strat]
        lines.append(
            f"| {strat} | {m['satisfaction_rate']:.3f} | "
            f"{m['spatial_utilization']:.3f} | {m['shift_count']:.1f} | "
            f"{m['shift_distance_m']:.0f} | {m['total_drive_distance_m']:.0f} | "
            f"{m['avg_wait_time_s']:.1f} | {m['rejected_count']:.1f} |")
    return "\n".join(lines)


def main():
    net, spots = build_layout()
    n_spots = len(spots)
    intensities = {"低": 60, "中": 100, "高": 140}
    seeds = [42, 43, 44, 45, 46]
    factories = strategy_factories()

    raw_rows = []
    summary = {}
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

    # ---- RHO 阈值扫描（中强度，均值）----
    sweep = []
    nveh = intensities["中"]
    demands = {s: generate_demand(total_vehicles=nveh, seed=s) for s in seeds}
    for mild, severe in [(0.1, 0.5), (0.2, 0.5), (0.3, 0.6), (0.2, 0.4)]:
        per_seed = []
        for s in seeds:
            m = run_once(net, spots, demands[s],
                         RhoRollingStrategy(mild_threshold=mild,
                                            severe_threshold=severe), s)
            per_seed.append({k: m[k] for k in METRIC_KEYS})
        sweep.append(((mild, severe), {k: avg(per_seed, k) for k in METRIC_KEYS}))

    os.makedirs("outputs", exist_ok=True)
    md = [f"# RHO 滚动时域动态修正（算法三）第一版实验汇总\n",
          f"- 车位数：{n_spots}；seeds：{seeds}（每格取均值）；同一 seed 下四策略"
          f"喂相同需求序列；RHO 默认参数 roll_step=10min / window=60min / "
          f"阈值(0.2, 0.5)。\n"]
    for iname, nveh in intensities.items():
        md.append(f"\n## {iname}需求强度（{nveh} 辆车，车位 {n_spots}）\n")
        md.append(fmt_table({s: summary[(iname, s)] for s in STRATS}))
    md.append("\n\n## RHO 阈值扫描（中强度，均值）\n")
    md.append("| (mild,severe) | 满足率 | 利用率 | 移位次数 | 移位距离(m) | "
              "行驶距离(m) | 平均等待(s) | 拒绝数 |")
    md.append("|---|---|---|---|---|---|---|---|")
    for w, m in sweep:
        md.append(
            f"| {w} | {m['satisfaction_rate']:.3f} | {m['spatial_utilization']:.3f} | "
            f"{m['shift_count']:.1f} | {m['shift_distance_m']:.0f} | "
            f"{m['total_drive_distance_m']:.0f} | {m['avg_wait_time_s']:.1f} | "
            f"{m['rejected_count']:.1f} |")
    with open("outputs/exp_rho_summary.md", "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")

    with open("outputs/exp_rho_raw.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["intensity", "n_vehicles", "strategy",
                                          "seed"] + METRIC_KEYS)
        w.writeheader()
        w.writerows(raw_rows)

    print(f"\n=== RHO（算法三）第一版实验（车位 {n_spots}）===")
    for iname, nveh in intensities.items():
        print(f"\n--- {iname}需求（{nveh} 辆）---")
        print(fmt_table({s: summary[(iname, s)] for s in STRATS}))
    print("\n--- RHO 阈值扫描（中强度均值）---")
    for w, m in sweep:
        print(f"{w}: sat={m['satisfaction_rate']:.3f} util={m['spatial_utilization']:.3f} "
              f"shifts={m['shift_count']:.1f} shiftdist={m['shift_distance_m']:.0f} "
              f"drive={m['total_drive_distance_m']:.0f} wait={m['avg_wait_time_s']:.1f} "
              f"rej={m['rejected_count']:.1f}")


if __name__ == "__main__":
    main()
