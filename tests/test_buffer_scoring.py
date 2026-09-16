"""缓冲位评分选位 + 二次移位层级 + 回位就近移动测试。"""

import math

from src.parking_opt.domain.spot import (EventType, NodeType, RoadNetwork,
                                          RoadNode, Spot, SpotType, Vehicle)
from src.parking_opt.evaluation.metrics import compute_metrics
from src.parking_opt.routing.path_engine import PathEngine
from src.parking_opt.simulation.engine import SimulationEngine
from src.parking_opt.simulation.parking_lot import ParkingLot


def _net_with_spots(spot_specs, edges=None):
    """spot_specs: [(spot_id, spot_type, group, depth, x, y), ...]"""
    net = RoadNetwork()
    net.add_node(RoadNode("ENTRY", NodeType.ENTRY, 0, 0))
    net.add_node(RoadNode("N0", NodeType.ROAD_NODE, 5, 0))
    for sid, stype, group, depth, x, y in spot_specs:
        net.add_node(RoadNode(sid, NodeType.PARKING_SPOT, x, y, stype, group, depth))
    default_edges = [("ENTRY", "N0", 5), ("N0", "ENTRY", 5)]
    for sid, _stype, _group, _depth, _x, _y in spot_specs:
        default_edges += [(sid, "N0", 3), ("N0", sid, 3)]
    for a, b, d in (edges if edges is not None else default_edges):
        net.add_edge(a, b, d)
    spots = [Spot(sid, stype, sid, group, depth) for sid, stype, group, depth, _, _ in spot_specs]
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


def test_scored_prefers_nearest_spot():
    """距离优先：两个独立位都久空闲时，选路网距离更近的。"""
    net, spots = _net_with_spots([
        ("A1", SpotType.STANDALONE, "A1", 1, 8, 3),
        ("A2", SpotType.STANDALONE, "A2", 1, 8, -3),
    ], edges=[("ENTRY", "N0", 5), ("N0", "ENTRY", 5),
              ("N0", "A1", 3), ("A1", "N0", 3),
              ("N0", "A2", 20), ("A2", "N0", 20)])
    lot = ParkingLot(spots)
    chosen, score = lot.select_buffer_scored(lot.get_spot("A1"), PathEngine(net), 100.0)
    assert chosen is not None
    assert chosen.spot_id == "A1"
    assert score < 1.0


def test_scored_idle_time_penalty():
    """空闲时间：刚空出的近位 vs 久空闲的远位，只考虑空闲时间时应选久空闲的。"""
    net, spots = _net_with_spots([
        ("A1", SpotType.STANDALONE, "A1", 1, 8, 3),
        ("A2", SpotType.STANDALONE, "A2", 1, 8, -3),
    ], edges=[("ENTRY", "N0", 5), ("N0", "ENTRY", 5),
              ("N0", "A1", 3), ("A1", "N0", 3),
              ("N0", "A2", 20), ("A2", "N0", 20)])
    lot = ParkingLot(spots)
    lot.get_spot("A1").last_freed_at = 99.0  # 刚空出 1 秒 → 空闲代价 ≈1
    chosen, _ = lot.select_buffer_scored(lot.get_spot("A1"), PathEngine(net), 100.0,
                                         w_d=0.0, w_t=1.0)
    assert chosen is not None and chosen.spot_id == "A2"


def test_scored_waiting_queue_pressure():
    """等待队列非空时，空闲时间代价加 0.3 压力（同一位评分变高）。"""
    net, spots = _net_with_spots([
        ("A1", SpotType.STANDALONE, "A1", 1, 8, 3),
    ], edges=[("ENTRY", "N0", 5), ("N0", "ENTRY", 5),
              ("N0", "A1", 3), ("A1", "N0", 3)])
    lot = ParkingLot(spots)
    chosen0, score0 = lot.select_buffer_scored(lot.get_spot("A1"), PathEngine(net), 100.0)
    lot.release_buffer(chosen0.spot_id)
    chosen1, score1 = lot.select_buffer_scored(lot.get_spot("A1"), PathEngine(net), 100.0,
                                               waiting_len=3)
    assert chosen0 is not None and chosen1 is not None
    assert score1 > score0


def test_scored_secondary_shift_penalty():
    """二次移位惩罚：近的纵深外层位会挡内层车，惩罚重时选远的独立位；无惩罚时选近的。"""
    net, spots = _net_with_spots([
        ("G2-1", SpotType.TANDEM, "G2", 1, 8, 3),
        ("G2-2", SpotType.TANDEM, "G2", 2, 12, 3),
        ("A1", SpotType.STANDALONE, "A1", 1, 8, -3),
    ], edges=[("ENTRY", "N0", 5), ("N0", "ENTRY", 5),
              ("N0", "G2-1", 3), ("G2-1", "N0", 3),
              ("G2-1", "G2-2", 4), ("G2-2", "G2-1", 4),
              ("N0", "A1", 20), ("A1", "N0", 20)])
    lot = ParkingLot(spots)
    lot.assign(Vehicle("Y", 0, 5000, 5000), lot.get_spot("G2-2"))  # 内层有车
    chosen, _ = lot.select_buffer_scored(lot.get_spot("G2-1"), PathEngine(net), 100.0)
    assert chosen is not None and chosen.spot_id == "A1"  # w_q=2 惩罚避开 G2-1
    lot.release_buffer(chosen.spot_id)
    chosen2, _ = lot.select_buffer_scored(lot.get_spot("G2-1"), PathEngine(net), 100.0,
                                          w_q=0.0)
    assert chosen2 is not None and chosen2.spot_id == "G2-1"  # 无惩罚时选近的


def test_last_freed_at_updated():
    """free/move_vehicle 携带时刻时更新 last_freed_at。"""
    lot = ParkingLot([
        Spot("A", SpotType.STANDALONE, "A", "A", 1),
        Spot("B", SpotType.STANDALONE, "B", "B", 1),
    ])
    v = Vehicle("V1", 0, 100, 100)
    lot.assign(v, lot.get_spot("A"))
    lot.move_vehicle(lot.get_spot("A"), lot.get_spot("B"), 12.0)
    assert lot.get_spot("A").last_freed_at == 12.0
    lot.free(lot.get_spot("B"), 20.0)
    assert lot.get_spot("B").last_freed_at == 20.0


def test_find_innermost_available():
    """就近回位目标：同组最内侧空闲位。"""
    spots = [Spot("G1-1", SpotType.TANDEM, "G1-1", "G1", 1),
             Spot("G1-2", SpotType.TANDEM, "G1-2", "G1", 2),
             Spot("G1-3", SpotType.TANDEM, "G1-3", "G1", 3)]
    lot = ParkingLot(spots)
    lot.get_spot("G1-3").is_occupied = True
    target = lot.find_innermost_available(lot.get_spot("G1-1"))
    assert target is not None and target.spot_id == "G1-2"


def test_scene_b_return_shift_goes_innermost():
    """场景 B 回位就近移动：3 深组里层被新车占后，移位车回位到中间空位。"""
    net, spots = _net_with_spots([
        ("A1", SpotType.STANDALONE, "A1", 1, 8, 6),
        ("G1-1", SpotType.TANDEM, "G1", 1, 8, 3),
        ("G1-2", SpotType.TANDEM, "G1", 2, 12, 3),
        ("G1-3", SpotType.TANDEM, "G1", 3, 16, 3),
    ], edges=[("ENTRY", "N0", 5), ("N0", "ENTRY", 5),
              ("N0", "A1", 4), ("A1", "N0", 4),
              ("N0", "G1-1", 4), ("G1-1", "N0", 4),
              ("G1-1", "G1-2", 4), ("G1-2", "G1-1", 4),
              ("G1-2", "G1-3", 4), ("G1-3", "G1-2", 4)])
    pe = PathEngine(net)
    lot = ParkingLot(spots)
    vehicles = [Vehicle("V1", 0, 5000, 5000), Vehicle("V2", 10, 5000, 5000)]
    engine = SimulationEngine(lot, pe, vehicles, _FixedPlan(["G1-1", "G1-3"]), seed=1)
    events = engine.run()

    ends = [e for e in events if e.event_type == EventType.SHIFT_END]
    assert ends, "应有回位事件"
    assert ends[0].metadata["final_spot"] == "G1-2"


def test_secondary_shift_level_and_metrics():
    """二次移位：移位车停在纵深外层缓冲位挡住内层车，内层车离场触发 level=2 再移位。"""
    net, spots = _net_with_spots([
        ("G1-1", SpotType.TANDEM, "G1", 1, 8, 3),
        ("G1-2", SpotType.TANDEM, "G1", 2, 12, 3),
        ("G2-1", SpotType.TANDEM, "G2", 1, 8, -3),
        ("G2-2", SpotType.TANDEM, "G2", 2, 12, -3),
    ], edges=[("ENTRY", "N0", 5), ("N0", "ENTRY", 5),
              ("N0", "G1-1", 4), ("G1-1", "N0", 4),
              ("G1-1", "G1-2", 4), ("G1-2", "G1-1", 4),
              ("N0", "G2-1", 4), ("G2-1", "N0", 4),
              ("G2-1", "G2-2", 4), ("G2-2", "G2-1", 4)])
    pe = PathEngine(net)
    lot = ParkingLot(spots)
    vehicles = [
        Vehicle("X", 0, 10000, 10000),   # 停 G1-1，被两次移位
        Vehicle("Z", 0, 100, 100),       # 停 G1-2，先离场触发 X 首次移位
        Vehicle("Y", 0, 125, 125),       # 停 G2-2，再离场触发 X 二次移位
    ]
    engine = SimulationEngine(lot, pe, vehicles,
                              _FixedPlan(["G1-1", "G1-2", "G2-2"]),
                              seed=1, car_speed=1.0)
    events = engine.run()

    starts = [e for e in events if e.event_type == EventType.SHIFT_START]
    levels = sorted(e.metadata.get("shift_level", 1) for e in starts)
    assert 1 in levels, "应有首次移位 level=1"
    assert 2 in levels, "应有二次移位 level=2"
    assert all(e.metadata.get("buffer_score") is not None for e in starts)
    m = compute_metrics(events, len(spots))
    assert m["secondary_shift_count"] >= 1
    assert m["secondary_shift_distance_m"] > 0
    assert all(math.isfinite(e.time) for e in events)


def test_select_buffer_legacy_compat():
    """旧版 select_buffer 字典序逻辑保持可用。"""
    lot = ParkingLot([
        Spot("A1", SpotType.STANDALONE, "A1", "A1", 1),
        Spot("A2", SpotType.STANDALONE, "A2", "A2", 1),
    ])
    buffer = lot.select_buffer()
    assert buffer is not None and buffer.spot_id == "A1"
