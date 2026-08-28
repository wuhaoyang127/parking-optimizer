from __future__ import annotations
"""多入口/多出口改造的单元与集成测试。

覆盖：
- PathEngine 多入口解析、默认入口/默认出口规则、按指定入口计距离；
- generate_demand 入口/出口随机分配（seed 可复现、主随机流不受污染）；
- 需求 JSON 的 entry_id/exit_id 导出导入往返与旧文件兼容；
- 引擎按车辆入口入库、按车辆出口离场（事件元数据）；
- 策略 NearestPath 按车辆入口选位；
- 出口不可达回退入口（DEGRADATION）。
"""

import json
import math

from src.parking_opt.domain.spot import RoadNetwork, RoadNode, NodeType, Spot, SpotType, Vehicle
from src.parking_opt.routing.path_engine import PathEngine
from src.parking_opt.simulation.parking_lot import ParkingLot
from src.parking_opt.simulation.arrival import generate_demand
from src.parking_opt.simulation.engine import SimulationEngine, TimeSlice
from src.parking_opt.io.demand_io import export_demand_json, parse_demand_json
from src.parking_opt.strategies.baselines import NearestPath, FCFS


def build_two_entry_net(with_exits: bool = True) -> RoadNetwork:
    """两个入口 E1/E2，两个出口 X1/X2，两个独立车位 A/B。

    拓扑：E1-A(10m)，E2-B(10m)；A/B 均可到 X1/X2（交叉出口，验证进出可不同）。
    E1 离 A 近，E2 离 B 近。
    """
    net = RoadNetwork()
    net.add_node(RoadNode("E1", NodeType.ENTRY, 0, 0))
    net.add_node(RoadNode("E2", NodeType.ENTRY, 100, 0))
    if with_exits:
        net.add_node(RoadNode("X1", NodeType.EXIT, 0, 50))
        net.add_node(RoadNode("X2", NodeType.EXIT, 100, 50))
    net.add_node(RoadNode("A", NodeType.PARKING_SPOT, 10, 0, SpotType.STANDALONE, "A", 1))
    net.add_node(RoadNode("B", NodeType.PARKING_SPOT, 90, 0, SpotType.STANDALONE, "B", 1))
    edges = [("E1", "A", 10), ("A", "E1", 10), ("E2", "B", 10), ("B", "E2", 10)]
    if with_exits:
        # A/B 都能到 X1/X2（交叉出口，验证进出可不同）
        edges += [("A", "X1", 5), ("X1", "A", 5), ("A", "X2", 15), ("X2", "A", 15),
                  ("B", "X1", 15), ("X1", "B", 15), ("B", "X2", 5), ("X2", "B", 5)]
    for a, b, d in edges:
        net.add_edge(a, b, d)
    return net


def spots_from_net(net: RoadNetwork) -> list[Spot]:
    return [Spot(n.node_id, n.spot_type, n.node_id, n.stack_group_id or n.node_id, n.depth or 1)
            for n in net.nodes.values() if n.node_type == NodeType.PARKING_SPOT]


def make_veh(vid, entry=None, exit_=None, arrival=0.0, park=100.0):
    return Vehicle(vehicle_id=vid, arrival_time=arrival, parking_duration=park,
                   estimated_duration=park, entry_id=entry, exit_id=exit_)


# ---------- PathEngine ----------

def test_path_engine_collects_multiple_entries_and_default_entry():
    net = build_two_entry_net()
    pe = PathEngine(net)
    assert set(pe.entry_ids) == {"E1", "E2"}
    # 没有名为 ENTRY 的节点 → 默认入口为第一个 entry（遍历顺序 E1）
    assert pe.entry_id == "E1"
    assert pe.distance_to_spot("A") == 10.0
    assert pe.distance_to_spot("B", "E2") == 10.0
    # 交叉出口边使 E1 可绕行到 B（经 X2），距离应大于直连入口
    assert pe.distance_to_spot("B", "E1") == 30.0
    assert pe.distance_to_spot("A", "E2") == 30.0


def test_path_engine_default_entry_prefers_named_entry():
    net = RoadNetwork()
    net.add_node(RoadNode("E2", NodeType.ENTRY, 0, 0))
    net.add_node(RoadNode("ENTRY", NodeType.ENTRY, 50, 0))
    net.add_node(RoadNode("A", NodeType.PARKING_SPOT, 60, 0, SpotType.STANDALONE, "A", 1))
    net.add_edge("ENTRY", "A", 10); net.add_edge("A", "ENTRY", 10)
    pe = PathEngine(net)
    assert pe.entry_ids == ["E2", "ENTRY"]
    assert pe.entry_id == "ENTRY"  # 命名 ENTRY 优先
    assert pe.distance_to_spot("A") == 10.0


def test_path_engine_exit_rules_and_fallback():
    # 无出口布局：default_exit_id None，resolve_exit 回退入口
    net = build_two_entry_net(with_exits=False)
    pe = PathEngine(net)
    assert pe.exit_ids == []
    assert pe.default_exit_id is None
    assert pe.resolve_exit(None) == "E1"  # 回退默认入口
    assert pe.resolve_exit("X1") == "E1"  # 非法出口也回退入口

    # 有出口布局：默认出口优先 EXIT，否则第一个
    net2 = build_two_entry_net()
    pe2 = PathEngine(net2)
    assert set(pe2.exit_ids) == {"X1", "X2"}
    assert pe2.default_exit_id == "X1"  # 无命名 EXIT → 第一个
    assert pe2.resolve_exit("X2") == "X2"
    assert pe2.resolve_exit(None) == "X1"


# ---------- 需求生成与 IO ----------

def test_generate_demand_entry_exit_assignment_reproducible_and_inscope():
    entries = ["E1", "E2"]
    exits = ["X1", "X2"]
    v1 = generate_demand(total_vehicles=60, seed=42, entry_ids=entries, exit_ids=exits)
    v2 = generate_demand(total_vehicles=60, seed=42, entry_ids=entries, exit_ids=exits)
    assert [v.entry_id for v in v1] == [v.entry_id for v in v2]
    assert [v.exit_id for v in v1] == [v.exit_id for v in v2]
    for v in v1:
        assert v.entry_id in entries
        assert v.exit_id in exits
    # 两个口都至少被分配到（60 辆车等概率，几乎必然）
    assert len({v.entry_id for v in v1}) == 2
    assert len({v.exit_id for v in v1}) == 2


def test_generate_demand_single_entry_keeps_old_sequence():
    """单入口（旧行为）：同 seed 生成的需求序列与不传口列表完全一致。"""
    old = generate_demand(total_vehicles=50, seed=7)
    new = generate_demand(total_vehicles=50, seed=7, entry_ids=["ENTRY"], exit_ids=[])
    assert [v.arrival_time for v in old] == [v.arrival_time for v in new]
    assert [v.parking_duration for v in old] == [v.parking_duration for v in new]
    assert all(v.entry_id is None and v.exit_id is None for v in new)


def test_demand_json_roundtrip_with_entry_exit():
    vehicles = [make_veh("V1", entry="E1", exit_="X2"),
                make_veh("V2", entry=None, exit_=None)]
    text = export_demand_json(vehicles, seed=42)
    data = json.loads(text)
    assert data["vehicles"][0]["entry_id"] == "E1"
    assert data["vehicles"][0]["exit_id"] == "X2"
    assert "entry_id" not in data["vehicles"][1]  # None 不输出
    back, meta = parse_demand_json(text)
    assert back[0].entry_id == "E1" and back[0].exit_id == "X2"
    assert back[1].entry_id is None and back[1].exit_id is None


def test_demand_json_old_file_without_entry_exit_still_parses():
    text = json.dumps({
        "schema_version": 1,
        "vehicles": [
            {"vehicle_id": "V1", "arrival_time": 0, "parking_duration": 100,
             "estimated_duration": 100},
        ],
    }, ensure_ascii=False)
    vehicles, meta = parse_demand_json(text)
    assert vehicles[0].entry_id is None and vehicles[0].exit_id is None


# ---------- 引擎按车辆口进出 ----------

def test_engine_uses_vehicle_entry_and_exit():
    net = build_two_entry_net()
    spots = spots_from_net(net)
    lot = ParkingLot(spots)
    pe = PathEngine(net)
    # 两辆车同时到达：一辆 E1 进 X2 出，另一辆 E2 进 X1 出
    vehicles = [make_veh("V1", entry="E1", exit_="X2", arrival=0.0, park=200),
                make_veh("V2", entry="E2", exit_="X1", arrival=1.0, park=200)]
    engine = SimulationEngine(lot, pe, vehicles, NearestPath(), seed=1)
    events = engine.run()

    spot_entry_1 = next(e for e in events if e.event_type.value == "spot_entry" and e.vehicle_id == "V1")
    spot_entry_2 = next(e for e in events if e.event_type.value == "spot_entry" and e.vehicle_id == "V2")
    assert spot_entry_1.metadata.get("entry") == "E1"
    assert spot_entry_2.metadata.get("entry") == "E2"
    assert spot_entry_1.spot_id == "A"  # E1 最近 A
    assert spot_entry_2.spot_id == "B"  # E2 最近 B

    dep_1 = next(e for e in events if e.event_type.value == "departure" and e.vehicle_id == "V1")
    dep_2 = next(e for e in events if e.event_type.value == "departure" and e.vehicle_id == "V2")
    assert dep_1.metadata.get("exit") == "X2"
    assert dep_2.metadata.get("exit") == "X1"


def test_engine_exit_unreachable_falls_back_to_entry_with_degradation():
    net = RoadNetwork()
    net.add_node(RoadNode("E1", NodeType.ENTRY, 0, 0))
    net.add_node(RoadNode("X9", NodeType.EXIT, 500, 500))  # 孤立出口
    net.add_node(RoadNode("A", NodeType.PARKING_SPOT, 10, 0, SpotType.STANDALONE, "A", 1))
    net.add_edge("E1", "A", 10); net.add_edge("A", "E1", 10)
    lot = ParkingLot([Spot("A", SpotType.STANDALONE, "A", "A", 1)])
    pe = PathEngine(net)
    vehicles = [make_veh("V1", entry="E1", exit_="X9", arrival=0.0, park=100)]
    engine = SimulationEngine(lot, pe, vehicles, FCFS(), seed=1)
    events = engine.run()
    degraded = [e for e in events if e.event_type.value == "degradation"]
    assert degraded, "出口不可达应记录 DEGRADATION"
    dep = next(e for e in events if e.event_type.value == "departure")
    assert dep.metadata.get("exit") == "E1"  # 回退入口


# ---------- 策略按车辆入口选位 ----------

def test_nearest_path_uses_vehicle_entry():
    net = build_two_entry_net()
    spots = spots_from_net(net)
    lot = ParkingLot(spots)
    pe = PathEngine(net)
    strategy = NearestPath()

    v_from_e1 = make_veh("V1", entry="E1")
    spot, status = strategy.assign(v_from_e1, 0.0, lot, pe)
    assert status == "assigned" and spot.spot_id == "A"

    v_from_e2 = make_veh("V2", entry="E2")
    spot2, _ = strategy.assign(v_from_e2, 0.0, lot, pe)
    assert spot2.spot_id == "B"
