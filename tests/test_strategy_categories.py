"""策略两段式选择：category 分类契约 + 注册表分类查询。"""

import src.parking_opt.strategies  # noqa: F401  触发注册
from src.parking_opt.strategies import StrategyRegistry
from src.parking_opt.strategies.registry import CATEGORY_CLASSIC, CATEGORY_ML


def test_category_constants_are_valid():
    """分类常量只能是 classic / ml。"""
    assert CATEGORY_CLASSIC == "classic"
    assert CATEGORY_ML == "ml"


def test_every_registered_strategy_has_known_category():
    """所有已登记策略的 category 必须来自 {classic, ml}。"""
    for name, cls in StrategyRegistry.all().items():
        assert getattr(cls, "category", CATEGORY_CLASSIC) in (CATEGORY_CLASSIC, CATEGORY_ML), name


def test_rho_is_ml():
    """RHO 用了 SARIMA-lite 时序预测，属于机器学习分类。"""
    assert StrategyRegistry.get("rho_rolling").category == CATEGORY_ML


def test_classic_contains_rule_and_optimization_algorithms():
    """规则/启发式/进化搜索/多准则评分算法归经典分类，不得误标机器学习。"""
    classic = StrategyRegistry.names_in_category(CATEGORY_CLASSIC)
    for name in ("fcfs", "nearest", "random", "greedy", "departure_greedy",
                 "duration_greedy", "peak_offpeak_fusion", "mosa", "risk_scoring"):
        assert name in classic, name


def test_ml_contains_only_learning_algorithms():
    """当前机器学习分类只有 RHO。"""
    assert StrategyRegistry.names_in_category(CATEGORY_ML) == ["rho_rolling"]


def test_names_in_category_preserves_registration_order():
    """分类查询保持登记顺序（下拉框顺序稳定）。"""
    ml = StrategyRegistry.names_in_category(CATEGORY_ML)
    assert ml == [n for n, _ in StrategyRegistry.items_in_category(CATEGORY_ML)]
    assert ml == ["rho_rolling"]


def test_classic_plus_ml_equals_all():
    """两个分类的并集 = 全部已登记策略（没有漏分类）。"""
    classic = set(StrategyRegistry.names_in_category(CATEGORY_CLASSIC))
    ml = set(StrategyRegistry.names_in_category(CATEGORY_ML))
    assert classic | ml == set(StrategyRegistry.all())
    assert classic.isdisjoint(ml)
