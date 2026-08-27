"""引擎时间片碰撞检测 + 场景 A/B 双向移位让行测试。"""

import math

from src.parking_opt.domain.spot import (RoadNetwork, RoadNode, NodeType,
                                         Spot, SpotType, Vehicle)
from src.parking_opt.routing.path_engine import PathEngine
from src.parking_opt.simulation.parking_lot import ParkingLot
from src.parking_opt.simulation.engine import SimulationEngine, TimeSlice


def build_tandem_net():
    """ENTRY-N0；A1 独立缓冲位；G1-1(外)-G1-2(里) 纵深组。"""
    net = RoadNetwork()
    net.add_node(RoadNode("ENTRY", NodeType.ENTRY, 0, 0))
    net.add_node(RoadNode("N0", NodeType.ROAD_NODE, 5, 0))
    net.add_node(RoadNode("A1", NodeType.PARKING_SPOT, 8, 3,
                          SpotType.STANDALONE, "A1", 1))
    net.add_node(RoadNode("G1-1", NodeType.PARKING_SPOT, 10, -3,
                          SpotType.TANDEM, "G1", 1))
    net.add_node(RoadNode("G1-2", NodeType.PARKING_SPOT, 14, -3,
                          SpotType.TANDEM, "G1", 2))
    for a, b, d in [("ENTRY", "N0", 5), ("N0", "ENTRY", 5),
                    ("N0", "A1", 3), ("A1", "N0", 3),
                    ("N0", "G1-1", 4), ("G1-1", "N0", 4),
                    ("G1-1", "G1-2", 4), ("G1-2", "G1-1", 4)]:
        net.add_edge(a, b, d)
    spots = [Spot("A1", SpotType.STANDALONE, "A1", "A1", 1),
             Spot("G1-1", SpotType.TANDEM, "G1-1", "G1", 1),
             Spot("G1-2", SpotType.TANDEM, "G1-2", "G1", 2)]
    return net, spots


class _FixedPlan:
    """按到达顺序分配指定车位序列的测试策略。"""

    name = "fixed_plan"

    def __init__(self, sequence):
        self.sequence = list(sequence)
        self.i = 0

    def assign(self, vehicle, time, parking_lot, path_engine):
        sid = self.sequence[self.i % len(self.sequence)]
        self.i += 1
        return (parking_lot.get_spot(sid), "assigned")


def test_scenario_b_entry_shift_events():
    """场景 B：新车停里层车位被外层车挡 → 外层车入库让行移位。"""
    net, spots = build_tandem_net()
    pe = PathEngine(net)
    lot = ParkingLot(spots)
    vehicles = [Vehicle("V1", 0, 5000, 5000), Vehicle("V2", 10, 5000, 5000)]
    engine = SimulationEngine(lot, pe, vehicles, _FixedPlan(["G1-1", "G1-2"]), seed=1)
    events = engine.run()

    assert engine.shift_count == 1
    shift_starts = [e for e in events if e.event_type.value == "shift_start"]
    assert len(shift_starts) == 1
    assert "入库" in shift_starts[0].metadata.get("reason", "")
    assert shift_starts[0].metadata["from_spot"] == "G1-1"
    assert shift_starts[0].metadata["to_spot"] == "A1"
    # 新车最终入位
    entries = [e for e in events if e.event_type.value == "spot_entry"
               and e.vehicle_id == "V2"]
    assert entries and entries[0].spot_id == "G1-2"
    # 所有事件时间有限
    assert all(math.isfinite(e.time) for e in events)


def test_scenario_a_leave_shift_events():
    """场景 A：里层车离场被外层车挡 → 外层车离场让行移位。"""
    net, spots = build_tandem_net()
    pe = PathEngine(net)
    lot = ParkingLot(spots)
    # V2 停里层且先离场（停车 100s）；V1 停外层 5000s
    vehicles = [Vehicle("V1", 0, 5000, 5000), Vehicle("V2", 10, 100, 100)]
    engine = SimulationEngine(lot, pe, vehicles, _FixedPlan(["G1-1", "G1-2"]), seed=1)
    events = engine.run()

    shift_starts = [e for e in events if e.event_type.value == "shift_start"]
    reasons = [e.metadata.get("reason", "") for e in shift_starts]
    assert any("入库" in r for r in reasons), "应有一次入库让行移位（场景 B）"
    assert any("离场" in r for r in reasons), "应有一次离场让行移位（场景 A）"
    # 里层车离场时被外层阻挡
    departures = [e for e in events if e.event_type.value == "departure"
                  and e.vehicle_id == "V2"]
    assert departures and departures[0].metadata.get("had_blocking") is True


def test_edge_timeslices_no_overlap():
    """时间片硬约束：同一有向边上的时间片不重叠（含 GAP）。"""
    net = RoadNetwork()
    net.add_node(RoadNode("ENTRY", NodeType.ENTRY, 0, 0))
    net.add_node(RoadNode("N0", NodeType.ROAD_NODE, 5, 0))
    net.add_node(RoadNode("A1", NodeType.PARKING_SPOT, 8, 3,
                          SpotType.STANDALONE, "A1", 1))
    net.add_node(RoadNode("A2", NodeType.PARKING_SPOT, 8, -3,
                          SpotType.STANDALONE, "A2", 1))
    for a, b, d in [("ENTRY", "N0", 5), ("N0", "ENTRY", 5),
                    ("N0", "A1", 3), ("A1", "N0", 3),
                    ("N0", "A2", 3), ("A2", "N0", 3)]:
        net.add_edge(a, b, d)
    spots = [Spot("A1", SpotType.STANDALONE, "A1", "A1", 1),
             Spot("A2", SpotType.STANDALONE, "A2", "A2", 1)]
    pe = PathEngine(net)
    lot = ParkingLot(spots)
    # 两辆车同时到达，共享 ENTRY→N0 边
    vehicles = [Vehicle("V1", 0, 1000, 1000), Vehicle("V2", 0, 1000, 1000)]
    engine = SimulationEngine(lot, pe, vehicles, _FixedPlan(["A1", "A2"]), seed=1)
    engine.run()

    shared = [ts for ts in engine.time_slices if ts.edge == ("ENTRY", "N0")]
    assert len(shared) == 2
    for i in range(len(shared)):
        for j in range(i + 1, len(shared)):
            a, b = shared[i], shared[j]
            overlap = not (a.end + engine.EDGE_GAP <= b.start
                           or b.end + engine.EDGE_GAP <= a.start)
            assert not overlap, f"时间片重叠: {a} vs {b}"
    # 第二辆车应等待 GAP 后通过（时间片间隔 >= GAP）
    gap = abs(shared[1].start - shared[0].end)
    assert gap >= engine.EDGE_GAP - 1e-9


def test_timeslice_dataclass_fields():
    """TimeSlice 结构完整性（供 UI/调试读取）。"""
    ts = TimeSlice("V1", ("A", "B"), 1.0, 2.0, "enter")
    assert ts.vehicle_id == "V1"
    assert ts.edge == ("A", "B")
    assert ts.start == 1.0 and ts.end == 2.0
    assert ts.kind == "enter"
