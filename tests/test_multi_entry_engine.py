"""引擎按车辆口进出、策略按入口选位、动态路径页提取测试。"""

from src.parking_opt.domain.spot import RoadNetwork, RoadNode, NodeType, Spot, SpotType
from src.parking_opt.routing.path_engine import PathEngine
from src.parking_opt.simulation.parking_lot import ParkingLot
from src.parking_opt.simulation.engine import SimulationEngine
from src.parking_opt.strategies.baselines import NearestPath, FCFS
from src.ui.common import build_vehicle_phases, interp_path_segment

from tests._multi_entry_helpers import build_two_entry_net, spots_from_net, make_veh, _ev


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


def test_build_vehicle_phases_extracts_enter_leave_shift_and_helpers():
    net = build_two_entry_net()
    pe = PathEngine(net)
    events = [
        _ev(10, "parking_assigned", "V1", "A"),
        _ev(20, "spot_entry", "V1", "A", {"entry": "E1"}),
        # 另一辆车为 V1 让行（辅助移位轨迹）
        _ev(30, "shift_start", "V2", "", {"from_spot": "B", "to_spot": "A",
                                          "blocked_vehicle": "V1"}),
        _ev(35, "shift_end", "V2"),
        # V1 自己作为移位车
        _ev(50, "shift_start", "V1", "", {"from_spot": "A", "to_spot": "B"}),
        _ev(55, "shift_end", "V1"),
        _ev(100, "departure", "V1", "A", {"exit": "X2", "had_blocking": False}),
    ]
    phases = build_vehicle_phases(net, pe, events, "V1")

    # 入库段：实际入口 E1 → A
    assert phases["enter"] is not None
    assert phases["enter"]["entry_id"] == "E1"
    assert phases["enter"]["path"][0] == "E1" and phases["enter"]["path"][-1] == "A"
    assert phases["enter"]["t_start"] == 10 and phases["enter"]["t_end"] == 20

    # 离场段：A → 出口 X2；t_start 应不早于自身移位回位（55）与 departure（100）
    assert phases["leave"] is not None
    assert phases["leave"]["exit_id"] == "X2"
    assert phases["leave"]["path"][0] == "A" and phases["leave"]["path"][-1] == "X2"
    assert phases["leave"]["t_start"] == 100
    # 让行轨迹：V2 为 V1 移位
    assert len(phases["leave"]["helper_shifts"]) == 1
    assert phases["leave"]["helper_shifts"][0]["vehicle_id"] == "V2"

    # 移位段：V1 从 A → B，并含回位段 B → A
    assert len(phases["shifts"]) == 2
    assert phases["shifts"][0]["kind"] == "shift"
    assert phases["shifts"][0]["from_spot"] == "A" and phases["shifts"][0]["to_spot"] == "B"
    assert phases["shifts"][0]["t_start"] == 50 and phases["shifts"][0]["t_end"] == 55
    assert phases["shifts"][0]["path"][0] == "A" and phases["shifts"][0]["path"][-1] == "B"
    back = phases["shifts"][1]
    assert back["kind"] == "return"
    assert back["from_spot"] == "B" and back["to_spot"] == "A"
    assert back["t_end"] == 55 and 50 <= back["t_start"] < 55
    assert back["path"][0] == "B" and back["path"][-1] == "A"


def test_build_vehicle_phases_departure_starts_from_shifted_spot():
    """移位后未回位（无 shift_end）时，离场起点应是移位后的缓冲位。"""
    net = build_two_entry_net()
    pe = PathEngine(net)
    events = [
        _ev(10, "parking_assigned", "V1", "A"),
        _ev(20, "spot_entry", "V1", "A", {"entry": "E1"}),
        _ev(50, "shift_start", "V1", "", {"from_spot": "A", "to_spot": "B"}),
        _ev(100, "departure", "V1", "A", {"exit": "X2", "had_blocking": False}),
    ]
    phases = build_vehicle_phases(net, pe, events, "V1")

    assert phases["leave"] is not None
    assert phases["leave"]["spot_id"] == "B"
    assert phases["leave"]["path"][0] == "B" and phases["leave"]["path"][-1] == "X2"
    # 未回位则只有去程移位段，没有回位段
    assert len(phases["shifts"]) == 1
    assert phases["shifts"][0]["kind"] == "shift"
    assert phases["shifts"][0]["from_spot"] == "A" and phases["shifts"][0]["to_spot"] == "B"


def test_interp_path_segment_endpoints_and_midpoint():
    net = build_two_entry_net()
    path = ["E1", "A"]  # E1(0,0) → A(10,0)
    x0, y0 = interp_path_segment(net, path, 0.0, 10.0, 0.0)
    x1, y1 = interp_path_segment(net, path, 0.0, 10.0, 10.0)
    xm, ym = interp_path_segment(net, path, 0.0, 10.0, 5.0)
    assert (x0, y0) == (0.0, 0.0)
    assert (x1, y1) == (10.0, 0.0)
    assert abs(xm - 5.0) < 1e-9 and abs(ym) < 1e-9
    # 越界夹取
    xc, yc = interp_path_segment(net, path, 0.0, 10.0, 99.0)
    assert (xc, yc) == (10.0, 0.0)
