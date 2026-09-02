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

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.exp_risk_scoring_lib import (build_layout, run_once, METRIC_KEYS,  # noqa: E402
                                          strategy_factories, avg, _write_outputs,
                                          _print_console)
from src.parking_opt.simulation.arrival import generate_demand  # noqa: E402
from src.parking_opt.strategies.risk_scoring import RiskScoringStrategy  # noqa: E402


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


if __name__ == "__main__":
    main()
