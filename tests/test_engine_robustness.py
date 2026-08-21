# -*- coding: utf-8 -*-
"""引擎稳健性回归：不可达车位不得产生非有限事件时间（inf/nan 传播崩溃）"""

import math

from src.parking_opt.domain.spot import (RoadNetwork, RoadNode, NodeType,
                                         Spot, SpotType, Vehicle)
from src.parking_opt.routing.path_engine import PathEngine
from src.parking_opt.simulation.parking_lot import ParkingLot
from src.parking_opt.simulation.engine import SimulationEngine
from src.parking_opt.strategies.greedy import DurationAwareGreedy


def _build_layout_with_unreachable_spot():
    """ENTRY-R1-S01 连通；S02 无任何边（从入口不可达）"""
    net = RoadNetwork()
    net.add_node(RoadNode("ENTRY", NodeType.ENTRY, 0, 0))
    net.add_node(RoadNode("R1", NodeType.ROAD_NODE, 5, 0))
    net.add_node(RoadNode("S01", NodeType.PARKING_SPOT, 8, 0,
                          SpotType.STANDALONE, "S01", 1))
    net.add_node(RoadNode("S02", NodeType.PARKING_SPOT, 8, -3,
                          SpotType.STANDALONE, "S02", 1))
    net.add_edge("ENTRY", "R1", 5)
    net.add_edge("R1", "ENTRY", 5)
    net.add_edge("R1", "S01", 3)
    net.add_edge("S01", "R1", 3)
    spots = [Spot("S01", SpotType.STANDALONE, "S01", "S01", 1),
             Spot("S02", SpotType.STANDALONE, "S02", "S02", 1)]
    return net, spots


def test_unreachable_spot_no_nonfinite_event_time():
    """回归：坏布局（含不可达车位）跑仿真，所有事件时间必须有限。"""
    net, spots = _build_layout_with_unreachable_spot()
    pe = PathEngine(net)
    lot = ParkingLot(spots)
    vehicles = [Vehicle(f"V{i+1}", i * 100, 7200, 7200) for i in range(5)]
    engine = SimulationEngine(lot, pe, vehicles, DurationAwareGreedy(), seed=1)
    events = engine.run()
    assert len(events) > 0
    bad = [e.time for e in events if not math.isfinite(e.time)]
    assert bad == [], f"存在非有限事件时间: {bad[:5]}"


def test_unreachable_spot_vehicle_rejected_not_occupied():
    """不可达车位的车辆应被拒绝，且不可达车位不应被占用。"""
    net, spots = _build_layout_with_unreachable_spot()
    pe = PathEngine(net)
    lot = ParkingLot(spots)
    # 只有一辆车，最近策略可能分到可达车位；用多辆车保证不可达车位被尝试分配
    vehicles = [Vehicle(f"V{i+1}", 0, 7200, 7200) for i in range(8)]
    engine = SimulationEngine(lot, pe, vehicles, DurationAwareGreedy(), seed=1)
    engine.run()
    s02 = lot.get_spot("S02")
    assert s02.is_occupied is False
    assert any(v.rejected for v in vehicles)
