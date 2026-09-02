"""risk_scoring 注册表与构造函数契约测试。"""

from src.parking_opt.strategies.registry import StrategyRegistry
from src.parking_opt.strategies.risk_scoring import RiskScoringStrategy

# 确保策略已登记（导入包触发注册）
import src.parking_opt.strategies  # noqa: F401


def test_registry_create():
    s = StrategyRegistry.create("risk_scoring")
    assert isinstance(s, RiskScoringStrategy)
    assert s.name == "risk_scoring"


def test_registry_create_with_params():
    s = StrategyRegistry.create("risk_scoring", w_distance=2.0, w_risk=0.5, w_depth=0.0)
    assert (s.w_distance, s.w_risk, s.w_depth) == (2.0, 0.5, 0.0)


def test_default_construction():
    s = RiskScoringStrategy()
    assert s.w_distance == 1.0 and s.w_risk == 1.5 and s.w_depth == 0.5


def test_params_match_constructor():
    """PARAMS 里每个 key 必须是构造函数关键字参数（网页控件契约）。"""
    keys = {p["key"] for p in RiskScoringStrategy.PARAMS}
    assert keys == {"w_distance", "w_risk", "w_depth"}
    # 用默认值实例化不报错
    defaults = {p["key"]: p["default"] for p in RiskScoringStrategy.PARAMS}
    RiskScoringStrategy(**defaults)


def test_registered_in_registry():
    assert StrategyRegistry.get("risk_scoring") is RiskScoringStrategy
