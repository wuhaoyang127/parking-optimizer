"""回归测试：引擎移位让行的并发竞态。

背景：实验脚本（scripts/exp_risk_scoring.py）重跑时发现
`nearest` × 中需求(100辆) × seed42 触发 `move_vehicle(buffer, target)`
断言失败——同一辆阻挡车在“被挡车离场/入库行驶”的 yield 期间被另一个
让行进程移走，原进程回位时缓冲位已空。

修复后要求：多 seed、多策略跑通不崩溃（结果确定性由实验脚本另行核对）。
"""

from src.parking_opt.domain.spot import (RoadNetwork, RoadNode, NodeType, Spot,
                                          SpotType, Vehicle)
from src.parking_opt.routing.path_engine import PathEngine
from src.parking_opt.simulation.parking_lot import ParkingLot
from src.parking_opt.simulation.engine import SimulationEngine
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


def test_move_vehicle_updates_assigned_spot_and_free_releases_buffer():
    """移位后车辆实际车位应同步；缓冲位被离场释放后不再占用。"""
    lot = ParkingLot([
        Spot("A", SpotType.STANDALONE, "A", "A", 1),
        Spot("B", SpotType.STANDALONE, "B", "B", 1),
    ])
    v = Vehicle("V1", 0.0, 100.0, 100.0)
    lot.assign(v, lot.get_spot("A"))
    assert v.assigned_spot == "A"

    lot.buffer_in_use.add("B")
    lot.move_vehicle(lot.get_spot("A"), lot.get_spot("B"))
    assert v.assigned_spot == "B"

    lot.free(lot.get_spot("B"))
    assert "B" not in lot.buffer_in_use
    assert "V1" not in lot.vehicles


def test_scene_b_blocker_departs_during_shift_no_crash():
    """曾崩溃组合：入库让行（场景 B）中，阻挡车在移位行驶期间自行离场。

    根因：阻挡车移位去缓冲位的 yield 期间，其自身离场进程释放了原车位，
    随后 move_vehicle(blk_spot, buffer) 对空车位断言失败（线上 AssertionError）。
    修复后要求：跳过本次移位、释放缓冲位，新车仍正常入位，仿真不崩溃。
    """
    net = RoadNetwork()
    for nid, ntype in [("ENTRY", NodeType.ENTRY), ("A", NodeType.PARKING_SPOT),
                       ("B", NodeType.PARKING_SPOT), ("S", NodeType.PARKING_SPOT)]:
        net.add_node(RoadNode(nid, ntype))
    for a, b, length in [("ENTRY", "A", 5), ("A", "ENTRY", 5), ("A", "B", 5),
                         ("B", "A", 5), ("A", "S", 25), ("S", "A", 25)]:
        net.add_edge(a, b, length)

    spots = [
        Spot("A", SpotType.TANDEM, "A", "G1", 1),
        Spot("B", SpotType.TANDEM, "B", "G1", 2),
        Spot("S", SpotType.STANDALONE, "S", "S", 1),
    ]
    # V1 先占外层 A，停车 8s 后自行离场；V2 随后分到里层 B，触发场景 B：
    # V1 移位去缓冲位 S 需 25s，期间 V1 在 t≈13s 离场释放 A。
    vehicles = [
        Vehicle("V1", 0.0, 8.0, 8.0),
        Vehicle("V2", 6.0, 100.0, 100.0),
    ]
    engine = SimulationEngine(ParkingLot(spots), PathEngine(net), vehicles,
                              NearestPath(), seed=42, car_speed=1.0)
    events = engine.run()  # 修复前在此抛 AssertionError

    entered = [e for e in events
               if e.vehicle_id == "V2" and e.event_type.value == "spot_entry"]
    assert entered, "V2 应正常入位"
    assert entered[0].spot_id == "B"
