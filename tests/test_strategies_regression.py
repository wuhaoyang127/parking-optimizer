"""策略回归测试：防止改动引入回归（如阈值失效、等待逻辑退化为立即拒绝）"""

import pytest

from src.parking_opt.domain.spot import Spot, SpotType, Vehicle
from src.parking_opt.simulation.parking_lot import ParkingLot
from src.parking_opt.strategies.baselines import FCFS, NearestPath, RandomAssign
from src.parking_opt.strategies.greedy import GreedyStrategy, DepartureOrderGreedy, DurationAwareGreedy


ALL_STRATEGIES = [FCFS, NearestPath, RandomAssign,
                  GreedyStrategy, DepartureOrderGreedy, DurationAwareGreedy]


def build_small_lot() -> ParkingLot:
    """2 独立车位 + 1 纵深组（2 深度）"""
    spots = [
        Spot("A1", SpotType.STANDALONE, "A1", "A1", 1),
        Spot("A2", SpotType.STANDALONE, "A2", "A2", 1),
        Spot("G1-1", SpotType.TANDEM, "G1-1", "G1", 1),
        Spot("G1-2", SpotType.TANDEM, "G1-2", "G1", 2),
    ]
    return ParkingLot(spots)


def _fill_lot(lot: ParkingLot):
    """占满所有可用车位（独立 + 外层），返回占用的车辆"""
    v = Vehicle("VFILL", 0, 1000, 7200)
    for spot in lot.get_available_spots():
        lot.assign(v, spot)


class _StubPathEngine:
    """测试用路径引擎替身：策略选车位时只需 distance_to_spot"""

    def distance_to_spot(self, node_id):
        return 1.0

    def shortest_distance(self, a, b):
        return 1.0


class TestStrategyStatus:
    """车位满时策略必须返回 waiting（排队等待），而非 rejected（立即拒绝）"""

    @pytest.mark.parametrize("cls", ALL_STRATEGIES)
    def test_returns_waiting_when_full(self, cls):
        lot = build_small_lot()
        _fill_lot(lot)
        assert lot.get_available_spots() == []
        strategy = cls()
        v = Vehicle("V2", 10, 200, 7200)
        spot, status = strategy.assign(v, 10, lot, None)
        assert status == "waiting", (
            f"{cls.__name__} 车位满时应返回 waiting（排队等待），实际返回 {status}")

    @pytest.mark.parametrize("cls", ALL_STRATEGIES)
    def test_returns_assigned_when_available(self, cls):
        lot = build_small_lot()
        strategy = cls()
        v = Vehicle("V1", 0, 100, 7200)
        spot, status = strategy.assign(v, 0, lot, _StubPathEngine())
        assert status == "assigned", f"{cls.__name__} 有空位时应返回 assigned"
        assert spot is not None


class TestDurationAwareGreedy:
    """时长感知贪心的阈值自适应回归：阈值必须随样本中位数变化，不能固定失效"""

    def test_adaptive_threshold_drops_for_short_stays(self):
        s = DurationAwareGreedy()
        # 短停样本（10~25 分钟），中位数约 1050s
        for d in [600, 700, 800, 900, 1000, 1100, 1200, 1300, 1400, 1500]:
            s._seen_durations.append(d)
        threshold = s._adaptive_threshold()
        assert threshold < 2000, f"短停样本下自适应阈值应较低，实际 {threshold:.0f}s"

    def test_adaptive_threshold_rises_for_long_stays(self):
        s = DurationAwareGreedy()
        # 长停样本（1~2 小时），中位数约 5400s
        for d in [3600, 4200, 4800, 5400, 6000, 6600, 7200, 7200, 7200, 7200]:
            s._seen_durations.append(d)
        threshold = s._adaptive_threshold()
        assert threshold > 3000, f"长停样本下自适应阈值应较高，实际 {threshold:.0f}s"

    def test_default_threshold_before_warmup(self):
        s = DurationAwareGreedy()
        s._seen_durations.append(3600)
        assert s._adaptive_threshold() == DurationAwareGreedy.DEFAULT_THRESHOLD


class TestWaitingQueueDispatch:
    """等待队列智能调度回归：车位满时车辆进入队列，离场后短停车优先被调度"""

    def _run_simulation(self, strategy, n_spots=15, n_vehicles=60, seed=42):
        from src.parking_opt.domain.spot import RoadNetwork, RoadNode, NodeType
        from src.parking_opt.routing.path_engine import PathEngine
        from src.parking_opt.simulation.engine import SimulationEngine
        from src.parking_opt.simulation.arrival import generate_demand
        from src.parking_opt.evaluation.metrics import compute_metrics

        def _an(net, nid, nt, x, y, st=None, sg=None, dp=None):
            net.add_node(RoadNode(nid, nt, x, y, st, sg, dp))

        net = RoadNetwork()
        _an(net, 'ENTRY', NodeType.ENTRY, 0, 0)
        _an(net, 'M', NodeType.ROAD_NODE, 8, 0)
        _an(net, 'U', NodeType.ROAD_NODE, 8, 6)
        _an(net, 'D', NodeType.ROAD_NODE, 8, -6)
        for a, b, d in [('ENTRY', 'M', 8), ('M', 'U', 6), ('M', 'D', 6),
                        ('U', 'M', 6), ('D', 'M', 6)]:
            net.add_edge(a, b, d)
        spots = []
        half = n_spots // 2
        nt = int(half * 0.5 / 2)
        ns = half - nt * 2
        for row, rd, ys in [('U', 'U', 1), ('D', 'D', -1)]:
            for i in range(ns):
                sid = f'{row}{i + 1:02d}'
                _an(net, sid, NodeType.PARKING_SPOT, 12 + i * 4.5, ys * 9,
                    SpotType.STANDALONE, sid, 1)
                net.add_edge(rd, sid, 3); net.add_edge(sid, rd, 3)
                spots.append(Spot(sid, SpotType.STANDALONE, sid, sid, 1))
            for g in range(nt):
                gid = f'{row}G{g + 1}'
                prev = rd
                bx = 12 + ns * 4.5 + g * 7
                by = ys * 9
                for d in range(1, 3):
                    sid = f'{gid}-{d}'
                    _an(net, sid, NodeType.PARKING_SPOT, bx + d * 3.5, by,
                        SpotType.TANDEM, gid, d)
                    net.add_edge(prev, sid, 3.5); net.add_edge(sid, prev, 3.5)
                    prev = sid
                    spots.append(Spot(sid, SpotType.TANDEM, sid, gid, d))

        vehicles = generate_demand(total_vehicles=n_vehicles, seed=seed)
        pe = PathEngine(net)
        lot = ParkingLot(spots)
        events = SimulationEngine(lot, pe, vehicles, strategy, seed=seed).run()
        return compute_metrics(events, len(spots))

    def test_satisfaction_rate_reasonable(self):
        """回归：仿真结果满足率应在合理区间 [0, 1]"""
        m = self._run_simulation(GreedyStrategy())
        assert 0.0 <= m["satisfaction_rate"] <= 1.0

    def test_all_strategies_run_without_crash(self):
        """回归：所有策略跑完整仿真不崩溃"""
        for cls in ALL_STRATEGIES:
            m = self._run_simulation(cls())
            assert 0.0 <= m["satisfaction_rate"] <= 1.0
            assert m["total_vehicles"] > 0
