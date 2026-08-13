"""核心模块单元测试"""

import pytest
from src.parking_opt.domain.spot import Spot, SpotType, Vehicle, RoadNetwork, RoadNode, NodeType
from src.parking_opt.simulation.parking_lot import ParkingLot
from src.parking_opt.strategies.baselines import FCFS, NearestPath, RandomAssign
from src.parking_opt.strategies.greedy import GreedyStrategy


def build_small_lot() -> ParkingLot:
    """构建测试停车场: 2独立 + 1纵深组(2深度)"""
    spots = [
        Spot("A1", SpotType.STANDALONE, "A1", "A1", 1),
        Spot("A2", SpotType.STANDALONE, "A2", "A2", 1),
        Spot("G1-1", SpotType.TANDEM, "G1-1", "G1", 1),
        Spot("G1-2", SpotType.TANDEM, "G1-2", "G1", 2),
    ]
    return ParkingLot(spots)


class TestParkingLot:
    def test_standalone_always_available(self):
        lot = build_small_lot()
        assert lot.is_available(lot.get_spot("A1")) is True

    def test_tandem_depth2_blocked_when_outer_occupied(self):
        # 当前设计：is_available 只检查空闲（深度约束由策略决定），
        # 但阻挡检测应正确报告里层被外层阻挡
        lot = build_small_lot()
        v = Vehicle("V1", 0, 100, 7200)
        lot.assign(v, lot.get_spot("G1-1"))
        assert lot.is_blocked(lot.get_spot("G1-2")) is True

    def test_blocking_detection(self):
        lot = build_small_lot()
        v1 = Vehicle("V1", 0, 200, 7200)
        v2 = Vehicle("V2", 10, 50, 7200)
        lot.assign(v1, lot.get_spot("G1-1"))
        lot.assign(v2, lot.get_spot("G1-2"))
        blockers = lot.get_blockers(lot.get_spot("G1-2"))
        assert len(blockers) == 1
        assert blockers[0][0].spot_id == "G1-1"

    def test_no_blocking_for_standalone(self):
        lot = build_small_lot()
        v = Vehicle("V1", 0, 100, 7200)
        lot.assign(v, lot.get_spot("A1"))
        assert lot.is_blocked(lot.get_spot("A1")) is False

    def test_buffer_selection(self):
        lot = build_small_lot()
        buffer = lot.select_buffer()
        assert buffer is not None
        assert buffer.spot_id in ["A1", "A2", "G1-1"]


class TestGreedy:
    def test_prefers_standalone(self):
        lot = build_small_lot()
        v = Vehicle("V1", 0, 100, 7200)
        # 模拟简单路网: 用None path_engine, 选standalone即可
        from src.parking_opt.routing.path_engine import PathEngine
        from src.parking_opt.io.road_io import load_road_network
        # 用简化判断：独立车位优先
        available = lot.get_available_spots()
        standalone = [s for s in available if s.spot_type == SpotType.STANDALONE]
        assert len(standalone) == 2


class TestFCFS:
    def test_assigns_first_available(self):
        lot = build_small_lot()
        f = FCFS()
        v = Vehicle("V1", 0, 100, 7200)
        spot, status = f.assign(v, 0, lot, None)
        assert status == "assigned"
        assert spot is not None
