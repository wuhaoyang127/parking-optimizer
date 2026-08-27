"""回归测试：引擎移位让行的并发竞态。

背景：实验脚本（scripts/exp_risk_scoring.py）重跑时发现
`nearest` × 中需求(100辆) × seed42 触发 `move_vehicle(buffer, target)`
断言失败——同一辆阻挡车在“被挡车离场/入库行驶”的 yield 期间被另一个
让行进程移走，原进程回位时缓冲位已空。

修复后要求：多 seed、多策略跑通不崩溃（结果确定性由实验脚本另行核对）。
"""

from src.parking_opt.simulation.arrival import generate_demand
from src.parking_opt.strategies.baselines import NearestPath
from src.parking_opt.strategies.risk_scoring import RiskScoringStrategy

from scripts.exp_risk_scoring import build_layout, run_once


def test_nearest_mid_demand_multi_seed_no_crash():
    """曾崩溃组合：nearest × 中需求（100 辆）× seeds 42–46。"""
    net, spots = build_layout()
    for seed in (42, 43, 44, 45, 46):
        demands = generate_demand(total_vehicles=100, seed=seed)
        run_once(net, spots, demands, NearestPath(), seed)


def test_risk_scoring_all_intensities_multi_seed_no_crash():
    """算法二在三档需求强度 × 5 seed 下与引擎配合不崩溃。"""
    net, spots = build_layout()
    for nveh in (60, 100, 140):
        for seed in (42, 43, 44, 45, 46):
            demands = generate_demand(total_vehicles=nveh, seed=seed)
            run_once(net, spots, demands, RiskScoringStrategy(), seed)
