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


def test_rho_is_classic_statistical_forecast():
    """RHO 的 SARIMA-lite 属统计时序预测，严格口径归经典，不硬凑机器学习。"""
    assert StrategyRegistry.get("rho_rolling").category == CATEGORY_CLASSIC


def test_classic_contains_rule_and_optimization_algorithms():
    """规则/启发式/进化搜索/多准则评分/统计时序预测算法归经典分类。"""
    classic = StrategyRegistry.names_in_category(CATEGORY_CLASSIC)
    for name in ("fcfs", "nearest", "random", "greedy", "departure_greedy",
                 "duration_greedy", "peak_offpeak_fusion", "mosa", "risk_scoring",
                 "rho_rolling"):
        assert name in classic, name


def test_ml_category_contains_duration_tree():
    """接入 CART 回归树后，ml 分类自动出现该算法（框架按分类出下拉）。"""
    assert StrategyRegistry.names_in_category(CATEGORY_ML) == ["ml_duration_tree"]


def test_names_in_category_preserves_registration_order():
    """分类查询保持登记顺序（下拉框顺序稳定）。"""
    classic = StrategyRegistry.names_in_category(CATEGORY_CLASSIC)
    assert classic == [n for n, _ in StrategyRegistry.items_in_category(CATEGORY_CLASSIC)]
    assert classic.index("fcfs") < classic.index("rho_rolling")


def test_classic_plus_ml_equals_all():
    """两个分类的并集 = 全部已登记策略（没有漏分类）。"""
    classic = set(StrategyRegistry.names_in_category(CATEGORY_CLASSIC))
    ml = set(StrategyRegistry.names_in_category(CATEGORY_ML))
    assert classic | ml == set(StrategyRegistry.all())
    assert classic.isdisjoint(ml)


def test_items_filtered_by_names_mixes_categories():
    """勾选列表可跨分类混合取算法（ML 与贪心同场对比）。"""
    items = StrategyRegistry.items_filtered(["greedy", "ml_duration_tree"])
    names = [n for n, _ in items]
    assert names == ["greedy", "ml_duration_tree"]


def test_items_filtered_names_priority_and_fallback():
    """names 优先于 category；names 中未登记的跳过；都给 None 返回全部。"""
    items = StrategyRegistry.items_filtered(["greedy", "no_such"], CATEGORY_ML)
    assert [n for n, _ in items] == ["greedy"]
    assert StrategyRegistry.items_filtered(None, CATEGORY_ML) == \
        StrategyRegistry.items_in_category(CATEGORY_ML)
    assert StrategyRegistry.items_filtered(None, None) == \
        list(StrategyRegistry.all().items())
