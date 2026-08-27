"""MOSA（算法一）接入测试：离线预分配策略 + prepare 钩子 + 端到端仿真。"""

import pytest

from src.parking_opt.domain.spot import RoadNetwork, RoadNode, NodeType, Spot, SpotType, Vehicle
from src.parking_opt.routing.path_engine import PathEngine
from src.parking_opt.simulation.parking_lot import ParkingLot
from src.parking_opt.simulation.engine import SimulationEngine
from src.parking_opt.simulation.arrival import generate_demand
from src.parking_opt.evaluation.metrics import compute_metrics
from src.parking_opt.strategies import StrategyRegistry
from src.parking_opt.strategies.mosa import MosaStrategy, estimate_scene
from src.parking_opt.strategies.baselines import FCFS


def build_net_spots(n_spots=15, tandem_ratio=0.5):
    """构建小规模测试路网（矩形），返回 (RoadNetwork, list[Spot])。"""

    def _an(net, nid, nt, x, y, st=None, sg=None, dp=None):
        net.add_node(RoadNode(nid, nt, x, y, st, sg, dp))

    net = RoadNetwork()
    _an(net, "ENTRY", NodeType.ENTRY, 0, 0)
    _an(net, "M", NodeType.ROAD_NODE, 8, 0)
    _an(net, "U", NodeType.ROAD_NODE, 8, 6)
    _an(net, "D", NodeType.ROAD_NODE, 8, -6)
    for a, b, d in [("ENTRY", "M", 8), ("M", "U", 6), ("M", "D", 6),
                    ("U", "M", 6), ("D", "M", 6)]:
        net.add_edge(a, b, d)
    spots = []
    half = n_spots // 2
    nt = int(half * tandem_ratio / 2)
    ns = half - nt * 2
    for row, rd, ys in [("U", "U", 1), ("D", "D", -1)]:
        for i in range(ns):
            sid = f"{row}{i + 1:02d}"
            _an(net, sid, NodeType.PARKING_SPOT, 12 + i * 4.5, ys * 9,
                SpotType.STANDALONE, sid, 1)
            net.add_edge(rd, sid, 3)
            net.add_edge(sid, rd, 3)
            spots.append(Spot(sid, SpotType.STANDALONE, sid, sid, 1))
        for g in range(nt):
            gid = f"{row}G{g + 1}"
            prev = rd
            bx = 12 + ns * 4.5 + g * 7
            by = ys * 9
            for d in range(1, 3):
                sid = f"{gid}-{d}"
                _an(net, sid, NodeType.PARKING_SPOT, bx + d * 3.5, by,
                    SpotType.TANDEM, gid, d)
                net.add_edge(prev, sid, 3.5)
                net.add_edge(sid, prev, 3.5)
                prev = sid
                spots.append(Spot(sid, SpotType.TANDEM, sid, gid, d))
    return net, spots


def run_sim(strategy, n_spots=15, n_vehicles=60, seed=42):
    """跑一次完整仿真，返回 metrics dict。"""
    net, spots = build_net_spots(n_spots)
    pe = PathEngine(net)
    lot = ParkingLot(spots)
    vehicles = generate_demand(total_vehicles=n_vehicles, seed=seed)
    events = SimulationEngine(lot, pe, vehicles, strategy, seed=seed).run()
    return compute_metrics(events, len(spots))


class _PrepareProbe:
    """验证引擎调用 prepare 钩子的探针策略。"""

    name = "prepare_probe"

    def __init__(self):
        self.prepare_calls = 0
        self.seen_vehicles = 0

    def prepare(self, vehicles, parking_lot, path_engine):
        self.prepare_calls += 1
        self.seen_vehicles = len(vehicles)

    def assign(self, vehicle, time, parking_lot, path_engine):
        available = parking_lot.get_available_spots()
        if not available:
            return (None, "waiting")
        return (available[0], "assigned")


class TestMosaRegistration:
    def test_registered_in_registry(self):
        assert "mosa" in StrategyRegistry.all()

    def test_no_arg_construction(self):
        s = MosaStrategy()
        assert s.name == "mosa"
        assert s.pop_size > 0 and s.generations > 0

    def test_params_keys_match_constructor(self):
        import inspect
        params = inspect.signature(MosaStrategy.__init__).parameters
        declared = {p["key"] for p in MosaStrategy.PARAMS}
        for key in declared:
            assert key in params, f"PARAMS 中的 {key} 不在构造函数参数中"


class TestMosaAssign:
    def test_assign_without_prepare_falls_back_to_greedy(self):
        """未 prepare 时直接 assign，也应能分配（回退贪心），不崩溃。"""
        net, spots = build_net_spots(8)
        pe = PathEngine(net)
        lot = ParkingLot(spots)
        s = MosaStrategy()
        v = Vehicle("V1", 0, 100, 7200)
        spot, status = s.assign(v, 0, lot, pe)
        assert status == "assigned"
        assert spot is not None

    def test_assign_waiting_when_full(self):
        net, spots = build_net_spots(8)
        pe = PathEngine(net)
        lot = ParkingLot(spots)
        s = MosaStrategy()
        filler = Vehicle("VF", 0, 100, 7200)
        for spot in lot.get_available_spots():
            lot.assign(filler, spot)
        assert lot.get_available_spots() == []
        v = Vehicle("V2", 10, 200, 7200)
        spot, status = s.assign(v, 10, lot, pe)
        assert status == "waiting"


class TestMosaPrepare:
    def test_prepare_builds_plan(self):
        net, spots = build_net_spots(12)
        pe = PathEngine(net)
        lot = ParkingLot(spots)
        vehicles = generate_demand(total_vehicles=40, seed=42)
        s = MosaStrategy(pop_size=8, generations=6)
        s.prepare(vehicles, lot, pe)
        assert s._plan is not None
        assert len(s._plan) >= 30  # 大部分车辆应在计划内
        # 计划中的 spot_id 必须是真实车位
        valid_ids = {sp.spot_id for sp in spots}
        assert all(sid in valid_ids for sid in s._plan.values())

    def test_scale_guard_skips_optimization(self):
        """超过规模上限时跳过 NSGA-II（回退贪心），不卡死。"""
        net, spots = build_net_spots(8)
        # 构造 70 个车位的假停车场（> MAX_SPOTS=60）
        big_spots = []
        for i in range(70):
            big_spots.append(Spot(f"S{i:02d}", SpotType.STANDALONE,
                                  f"S{i:02d}", f"S{i:02d}", 1))
        pe = PathEngine(net)  # 路网不含这些车位也没关系，prepare 会提前跳过
        lot = ParkingLot(big_spots)
        vehicles = generate_demand(total_vehicles=100, seed=42)
        s = MosaStrategy()
        s.prepare(vehicles, lot, pe)
        assert s._plan is None


class TestPrepareHook:
    def test_engine_calls_prepare_before_simulation(self):
        """引擎 run() 开头应调用策略的 prepare 钩子（在线策略无此方法时自动跳过）。"""
        net, spots = build_net_spots(8)
        pe = PathEngine(net)
        lot = ParkingLot(spots)
        vehicles = generate_demand(total_vehicles=30, seed=42)
        probe = _PrepareProbe()
        SimulationEngine(lot, pe, vehicles, probe, seed=42).run()
        assert probe.prepare_calls == 1
        assert probe.seen_vehicles == 30

    def test_online_strategy_without_prepare_still_runs(self):
        """在线策略未实现 prepare 时，引擎运行不受影响（向后兼容）。"""
        m = run_sim(FCFS(), n_spots=12, n_vehicles=40)
        assert 0.0 <= m["satisfaction_rate"] <= 1.0


class TestMosaEndToEnd:
    def test_runs_without_crash(self):
        m = run_sim(MosaStrategy(pop_size=8, generations=6), n_spots=15, n_vehicles=60)
        assert 0.0 <= m["satisfaction_rate"] <= 1.0
        assert m["total_vehicles"] > 0

    def test_offline_plan_not_worse_than_fcfs(self):
        """离线全信息预分配在同一需求下，满足率应不低于 FCFS（对照基准）。"""
        mosa_m = run_sim(MosaStrategy(pop_size=10, generations=8),
                         n_spots=15, n_vehicles=60)
        fcfs_m = run_sim(FCFS(), n_spots=15, n_vehicles=60)
        assert mosa_m["satisfaction_rate"] >= fcfs_m["satisfaction_rate"] - 0.05


class TestSceneAutoBinding:
    """场景权重与车位数/车辆数/时间自动绑定（共 3 种情况）。"""

    def test_estimate_binds_spots_vehicles_time(self):
        # 车少 → 平峰（重距离）
        assert estimate_scene(20, 30, 21600, 3900) == "normal"
        # 车多 → 饱和（重利用率）
        assert estimate_scene(20, 120, 21600, 3900) == "saturated"
        # 中等压力 → 高峰（重时间）
        assert estimate_scene(20, 90, 21600, 3900) == "peak"
        # 短停车时长下同样车辆数压力更低 → 平峰
        assert estimate_scene(20, 90, 21600, 600) == "normal"

    def test_scene_param_locked_in_ui(self):
        """scene 参数应标记为 locked（网页渲染为灰色不可调）。"""
        scene_spec = next(p for p in MosaStrategy.PARAMS if p["key"] == "scene")
        assert scene_spec.get("locked") is True
        assert scene_spec["default"] == "auto"

    def test_estimate_invalid_inputs_fallback_normal(self):
        assert estimate_scene(0, 10, 21600, 3900) == "normal"
        assert estimate_scene(20, 0, 21600, 3900) == "normal"
        assert estimate_scene(20, 10, 0, 3900) == "normal"
