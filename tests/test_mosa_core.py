"""MOSA：注册、assign 回退、prepare 计划、引擎 prepare 钩子。"""

from src.parking_opt.domain.spot import Vehicle, Spot, SpotType
from src.parking_opt.routing.path_engine import PathEngine
from src.parking_opt.simulation.parking_lot import ParkingLot
from src.parking_opt.simulation.engine import SimulationEngine
from src.parking_opt.simulation.arrival import generate_demand
from src.parking_opt.strategies import StrategyRegistry
from src.parking_opt.strategies.mosa import MosaStrategy
from src.parking_opt.strategies.baselines import FCFS

from tests._mosa_helpers import build_net_spots, run_sim, _PrepareProbe


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

    def test_no_scale_guard_runs_optimization_for_large(self):
        """取消规模保护后：70 车位也应照常运行 NSGA-II（小代数保持测试快速）。"""
        net, spots = build_net_spots(8)
        big_spots = []
        for i in range(70):
            big_spots.append(Spot(f"S{i:02d}", SpotType.STANDALONE,
                                  f"S{i:02d}", f"S{i:02d}", 1))
        pe = PathEngine(net)  # 路网不含这些车位，距离为 inf → 计划可能为空，但优化必须运行
        lot = ParkingLot(big_spots)
        vehicles = generate_demand(total_vehicles=100, seed=42)
        s = MosaStrategy(pop_size=4, generations=2)
        s.prepare(vehicles, lot, pe)
        assert s._plan is not None  # 优化已运行（不再因规模跳过）


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
