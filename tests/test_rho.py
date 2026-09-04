"""算法三 RHO 滚动时域动态修正策略测试（注册契约 + 预测器 + 分级行为）。"""

from src.parking_opt.strategies.registry import StrategyRegistry
from src.parking_opt.strategies.rho import RhoRollingStrategy
from src.parking_opt.strategies._rho_forecast import SarimaLite

# 确保策略已登记（导入包触发注册）
import src.parking_opt.strategies  # noqa: F401

from tests._risk_helpers import StubPathEngine, build_lot, veh


# ---------- 注册表契约 ----------

def test_registry_create():
    s = StrategyRegistry.create("rho_rolling")
    assert isinstance(s, RhoRollingStrategy)
    assert s.name == "rho_rolling"


def test_default_construction():
    s = RhoRollingStrategy()
    assert s.roll_step == 10 and s.window_min == 60
    assert s.mild_threshold == 0.2 and s.severe_threshold == 0.5
    assert s.burst_threshold == 10
    assert s._mode == "plan"


def test_params_match_constructor():
    keys = {p["key"] for p in RhoRollingStrategy.PARAMS}
    assert keys == {"roll_step", "window_min", "mild_threshold", "severe_threshold",
                    "burst_threshold", "plan_strategy", "high_load_strategy",
                    "low_load_strategy", "fallback_strategy"}
    defaults = {p["key"]: p["default"] for p in RhoRollingStrategy.PARAMS}
    RhoRollingStrategy(**defaults)  # 不报错


def test_registered_in_registry():
    assert StrategyRegistry.get("rho_rolling") is RhoRollingStrategy


def test_no_prepare_override():
    """在线策略：不得重写 prepare（不读未来需求）。"""
    assert "prepare" not in RhoRollingStrategy.__dict__


def test_self_reference_guard():
    """子算法选成自己时不得递归。"""
    s = RhoRollingStrategy(plan_strategy="rho_rolling")
    assert s._plan.name == "nearest"


# ---------- SARIMA-lite 预测器 ----------

def test_forecast_initial_zero():
    f = SarimaLite()
    assert f.predict(6) == [0.0] * 6


def test_forecast_learns_constant_level():
    f = SarimaLite()
    for _ in range(5):
        f.update(10.0)
    preds = f.predict(3)
    assert all(p >= 0.0 for p in preds)
    assert abs(preds[0] - 10.0) < 2.0


def test_forecast_follows_trend():
    """纯 Holt（phi=0，alpha=beta=1 完全跟踪）时预测随正趋势递增。"""
    f = SarimaLite(alpha=1.0, beta=1.0, phi=0.0)
    for a in (5.0, 6.0, 7.0, 8.0):
        f.update(a)
    preds = f.predict(3)
    assert preds[2] >= preds[1] >= preds[0] >= 8.0


# ---------- 偏差与分级 ----------

def test_deviation():
    s = RhoRollingStrategy()
    assert abs(s._deviation(8.0, 10.0) - 0.2) < 1e-9
    assert s._deviation(0.0, 10.0) == 1.0
    assert s._deviation(5.0, 0.0) == 5.0
    assert s._deviation(0.0, 0.0) == 0.0


def test_classify_boundaries():
    s = RhoRollingStrategy(mild_threshold=0.2, severe_threshold=0.5)
    assert s._classify(0.2) == 1
    assert s._classify(0.21) == 2
    assert s._classify(0.5) == 2
    assert s._classify(0.51) == 3


# ---------- 分配与模式切换 ----------

def test_assign_plan_mode_within_same_bucket():
    s = RhoRollingStrategy()
    lot = build_lot()
    pe = StubPathEngine()
    spot, status = s.assign(veh("V1", arrival=0.0), 0.0, lot, pe)
    assert status == "assigned" and spot is not None
    assert s._mode == "plan"


def test_waiting_when_full():
    s = RhoRollingStrategy()
    lot = build_lot()
    filler = veh("VFILL")
    for spot in lot.get_available_spots():
        lot.assign(filler, spot)
    spot, status = s.assign(veh("V1", arrival=0.0), 0.0, lot, StubPathEngine())
    assert status == "waiting" and spot is None


def test_severe_deviation_switches_fallback():
    """bucket0 实际 3 辆 → 学习 level=3；bucket1 只来 1 辆 → E=2/3>0.5 → 兜底。"""
    s = RhoRollingStrategy(roll_step=10, window_min=60)
    lot = build_lot()
    pe = StubPathEngine()
    for t in (0.0, 60.0, 120.0):           # bucket0 到 3 辆
        s.assign(veh(f"B0-{t}", arrival=t), t, lot, pe)
    assert s._mode == "plan"
    s.assign(veh("B1-1", arrival=650.0), 650.0, lot, pe)   # bucket1 只 1 辆
    assert s._mode == "plan"  # bucket0 无预测，只学习不判定
    spot, status = s.assign(veh("B2-1", arrival=1250.0), 1250.0, lot, pe)
    assert s._mode == "fallback"
    assert status == "assigned" and spot is not None


def test_mild_deviation_stays_plan():
    """bucket0 实际 3 辆 → 学习 level=3；bucket1 实际 3 辆 → E=0 → 保持基准。"""
    s = RhoRollingStrategy(roll_step=10, window_min=60)
    lot = build_lot()
    pe = StubPathEngine()
    for t in (0.0, 60.0, 120.0):
        s.assign(veh(f"B0-{t}", arrival=t), t, lot, pe)
    for i, t in enumerate((600.0, 660.0, 720.0)):           # bucket1 来 3 辆
        s.assign(veh(f"B1-{i}", arrival=t), t, lot, pe)
    s.assign(veh("B2-1", arrival=1250.0), 1250.0, lot, pe)  # 触发 bucket1 判定
    assert s._mode == "plan"


def test_moderate_deviation_switches_adjust():
    """bucket0 实际 4 辆 → 学习 level=4；bucket1 来 3 辆 → E=0.25 → 中度，偏低→nearest。"""
    s = RhoRollingStrategy(roll_step=10, window_min=60)
    lot = build_lot()
    pe = StubPathEngine({"G1-1": 1.0, "A1": 10.0, "A2": 11.0, "G1-2": 2.0})
    for t in (0.0, 30.0, 60.0, 90.0):                       # bucket0 到 4 辆
        s.assign(veh(f"B0-{t}", arrival=t), t, lot, pe)
    for i, t in enumerate((600.0, 630.0, 660.0)):           # bucket1 到 3 辆
        s.assign(veh(f"B1-{i}", arrival=t), t, lot, pe)
    spot, status = s.assign(veh("B2-1", arrival=1200.0), 1200.0, lot, pe)
    assert s._mode == "adjust"
    assert s._last_diff < 0          # 实际低于预测 → 用低负载算法
    assert status == "assigned"
    assert spot is not None


def test_event_burst_triggers_fallback():
    """5 分钟进场超过阈值立即切兜底（无需等待滚动窗口）。"""
    s = RhoRollingStrategy(burst_threshold=3)
    lot = build_lot()
    pe = StubPathEngine()
    for i, t in enumerate((0.0, 60.0, 120.0)):
        s.assign(veh(f"V{i}", arrival=t), t, lot, pe)
    assert s._mode == "plan"
    s.assign(veh("V3", arrival=180.0), 180.0, lot, pe)   # 第 4 辆触发
    assert s._mode == "fallback"


def test_fallback_uses_nearest_by_default():
    """兜底后由 nearest 就近分配（距离最近的车位被选中）。"""
    s = RhoRollingStrategy(roll_step=10, window_min=60)
    lot = build_lot()
    pe = StubPathEngine({"G1-1": 1.0, "A1": 10.0, "A2": 11.0, "G1-2": 2.0})
    for t in (0.0, 60.0, 120.0):
        s.assign(veh(f"B0-{t}", arrival=t), t, lot, pe)
    s.assign(veh("B1-1", arrival=650.0), 650.0, lot, pe)
    spot, status = s.assign(veh("B2-1", arrival=1250.0), 1250.0, lot, pe)
    assert s._mode == "fallback"
    assert spot is not None and spot.spot_id == "G1-1"
    assert status == "assigned"


def test_assign_never_reads_real_duration():
    """在线策略信息边界：真实停车时长不同，分配结果不受影响（只依赖预估）。"""
    s = RhoRollingStrategy()
    lot = build_lot()
    pe = StubPathEngine({"G1-1": 1.0, "A1": 10.0, "A2": 11.0, "G1-2": 2.0})
    v_short = veh("VS", arrival=0.0, real=600.0, est=600.0)
    v_long = veh("VL", arrival=0.0, real=60000.0, est=600.0)
    spot_s, _ = s.assign(v_short, 0.0, lot, pe)
    lot2 = build_lot()
    spot_l, _ = RhoRollingStrategy().assign(v_long, 0.0, lot2, pe)
    assert spot_s.spot_id == spot_l.spot_id
