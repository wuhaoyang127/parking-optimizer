"""ML 时长预测树：CART 回归树 + 策略注册/训练/分流行为。"""

import numpy as np

import src.parking_opt.strategies  # noqa: F401  触发注册
from src.parking_opt.domain.spot import Spot, SpotType, Vehicle
from src.parking_opt.simulation.parking_lot import ParkingLot
from src.parking_opt.strategies import StrategyRegistry
from src.parking_opt.strategies._cart import CartRegressor
from src.parking_opt.strategies.ml_duration import MlDurationTreeStrategy
from src.parking_opt.strategies.registry import CATEGORY_ML

from tests._risk_helpers import StubPathEngine, veh


def _tandem_lot():
    """仅含 1 个 2 深纵深组（G1-1 外层, G1-2 里层），无独立位。"""
    spots = [
        Spot("G1-1", SpotType.TANDEM, "G1-1", "G1", 1),
        Spot("G1-2", SpotType.TANDEM, "G1-2", "G1", 2),
    ]
    return ParkingLot(spots)


# ── CART 回归树 ──

def test_cart_learns_constant():
    """标签全同时，树退化为常数叶节点并预测均值。"""
    X = np.array([[1.0], [2.0], [3.0], [4.0]])
    y = np.array([10.0, 10.0, 10.0, 10.0])
    tree = CartRegressor(max_depth=3, min_samples_leaf=1).fit(X, y)
    assert tree.root.feature is None
    assert tree.predict_one([99.0]) == 10.0


def test_cart_fits_piecewise_constant():
    """能学出「前段均值 8 / 后段均值 2」的分段规律。"""
    X = np.array([[1.0], [2.0], [3.0], [4.0], [9.0], [10.0], [11.0], [12.0]])
    y = np.array([8.0, 8.0, 8.0, 8.0, 2.0, 2.0, 2.0, 2.0])
    tree = CartRegressor(max_depth=3, min_samples_leaf=1).fit(X, y)
    assert tree.predict_one([0.0]) == 8.0
    assert tree.predict_one([15.0]) == 2.0


def test_cart_respects_leaf_size():
    """min_samples_leaf=5 时叶节点输出为区间均值，预测在合理范围内。"""
    X = np.arange(20.0).reshape(-1, 1)
    y = np.arange(20.0)
    tree = CartRegressor(max_depth=5, min_samples_leaf=5).fit(X, y)
    assert tree.root.feature is not None  # 发生了分裂
    preds = tree.predict(X)
    assert np.all(preds >= 0.0) and np.all(preds <= 19.0)
    # 第一片叶覆盖 0~4，输出其均值 2.0
    assert tree.predict_one([1.0]) == 2.0


# ── 策略注册与构造 ──

def test_strategy_registered_as_ml():
    cls = StrategyRegistry.get("ml_duration_tree")
    assert cls is MlDurationTreeStrategy
    assert cls.category == CATEGORY_ML


def test_strategy_no_arg_construct():
    """无参构造（cls()）可用，向后兼容。"""
    s = MlDurationTreeStrategy()
    assert s.max_depth == 4
    assert s.min_samples_leaf == 5
    assert s.use_entry is True


def test_strategy_params_declared():
    specs = StrategyRegistry.specs("ml_duration_tree")
    keys = [p["key"] for p in specs]
    assert keys == ["max_depth", "min_samples_leaf", "use_entry"]


# ── 在线分流行为 ──

def test_degenerate_tree_falls_back_to_outer_first():
    """训练时长与到达无关（全同标签）→ 预测退化 → 外层优先贪心。"""
    lot = _tandem_lot()
    strat = MlDurationTreeStrategy(max_depth=3, min_samples_leaf=2, use_entry=False)
    trains = [veh("T1", arrival=100 * i, real=1800.0, est=1800.0) for i in range(6)]
    strat.prepare(trains, lot, StubPathEngine())
    assert strat._degenerate is True
    spot, status = strat.assign(veh("V1", arrival=50.0, real=1000.0, est=1000.0),
                                0.0, lot, StubPathEngine())
    assert status == "assigned"
    assert spot.spot_id == "G1-1"  # 外层优先


def test_tree_split_routes_by_arrival_period():
    """早到长停→里层、晚到短停→外层（树学到时段规律）。"""
    lot = _tandem_lot()
    strat = MlDurationTreeStrategy(max_depth=3, min_samples_leaf=2, use_entry=False)
    trains = [veh("T1", arrival=100, real=7200.0),
              veh("T2", arrival=200, real=7200.0),
              veh("T3", arrival=5000, real=600.0),
              veh("T4", arrival=5100, real=600.0)]
    strat.prepare(trains, lot, StubPathEngine())
    assert strat._degenerate is False

    early = veh("E1", arrival=0.0, real=7200.0, est=7200.0)
    late = veh("L1", arrival=6000.0, real=600.0, est=600.0)
    spot_e, _ = strat.assign(early, 0.0, lot, StubPathEngine())
    spot_l, _ = strat.assign(late, 0.0, lot, StubPathEngine())
    assert spot_e.spot_id == "G1-2"  # 预测长停 → 里层
    assert spot_l.spot_id == "G1-1"  # 预测短停 → 外层


def test_predict_duration_non_negative():
    """预测值恒非负；未见入口时也能安全预测。"""
    lot = _tandem_lot()
    strat = MlDurationTreeStrategy()
    trains = [veh("T1", arrival=100 * i, real=600.0 + 100 * i) for i in range(6)]
    strat.prepare(trains, lot, StubPathEngine())
    v = Vehicle("VX", arrival_time=99999.0, parking_duration=600.0,
                estimated_duration=600.0, entry_id="NEW_ENTRY")
    assert strat._predict_duration(v) >= 1.0


def test_entry_feature_builds_onehot():
    """use_entry=True 且多入口时，特征维度 = 1 + 入口数。"""
    lot = _tandem_lot()
    strat = MlDurationTreeStrategy(use_entry=True)
    trains = [veh("T1", arrival=100 * i, real=1800.0) for i in range(4)]
    for i, v in enumerate(trains):
        v.entry_id = "E0" if i % 2 == 0 else "E1"
    X, y = strat._build_dataset(trains)
    assert X.shape == (4, 3)  # 到达时刻 + 2 个入口 one-hot
    assert y.shape == (4,)
