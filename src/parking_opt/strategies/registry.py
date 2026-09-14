"""统一策略注册表：单点登记算法，网页与 CLI 均从这里取。"""

from __future__ import annotations

# 策略分类：经典/规则算法 与 机器学习算法。
# 机器学习类算法的判定口径：从数据中学习规律/预测（如时序预测、监督学习、强化学习）。
# 仅用规则/启发式/运筹优化（如贪心、NSGA-II 进化搜索、多准则评分）的算法归 classic。
CATEGORY_CLASSIC = "classic"
CATEGORY_ML = "ml"


class StrategyRegistry:
    """策略注册表（类级单例）。

    用法：
        StrategyRegistry.register(MyStrategy)            # 登记（也可作装饰器）
        StrategyRegistry.create("my_strategy", **params) # 按参数实例化
        StrategyRegistry.all()                           # {name: class}
        StrategyRegistry.specs("my_strategy")            # 参数声明 PARAMS
        StrategyRegistry.default_params("my_strategy")   # {key: default}
    """

    _strategies: dict = {}

    @classmethod
    def register(cls, strategy_cls) -> type:
        """登记策略类，返回该类（可作装饰器使用）。"""
        if not hasattr(strategy_cls, "name") or not strategy_cls.name:
            raise ValueError(f"策略类 {strategy_cls!r} 缺少 name 属性")
        cls._strategies[strategy_cls.name] = strategy_cls
        return strategy_cls

    @classmethod
    def create(cls, name: str, **params):
        """按参数实例化策略；未知参数名会触发 TypeError（提示参数写错）。"""
        strategy_cls = cls._strategies[name]
        return strategy_cls(**params)

    @classmethod
    def get(cls, name: str):
        """获取策略类（未登记返回 None）。"""
        return cls._strategies.get(name)

    @classmethod
    def all(cls) -> dict:
        """返回全部策略 {name: class} 的副本。"""
        return dict(cls._strategies)

    @classmethod
    def specs(cls, name: str) -> list:
        """返回某策略的参数声明 PARAMS（未登记返回空列表）。"""
        strategy_cls = cls._strategies.get(name)
        return strategy_cls.PARAMS if strategy_cls else []

    @classmethod
    def default_params(cls, name: str) -> dict:
        """返回某策略的默认参数 {key: default}（供网页初始化控件）。"""
        return {p["key"]: p["default"] for p in cls.specs(name) if "default" in p}

    @classmethod
    def names_in_category(cls, category: str) -> list:
        """返回指定分类下的策略 name 列表（保持登记顺序）。

        未标 category 的策略默认视为 CATEGORY_CLASSIC（向后兼容）。
        """
        return [n for n, c in cls._strategies.items()
                if getattr(c, "category", CATEGORY_CLASSIC) == category]

    @classmethod
    def items_in_category(cls, category: str) -> list:
        """返回指定分类下的 [(name, class), ...] 列表（保持登记顺序）。

        供「全部对比」按当前分类过滤使用；云/本机计算共用，避免两处口径不一致。
        """
        return [(n, c) for n, c in cls._strategies.items()
                if getattr(c, "category", CATEGORY_CLASSIC) == category]
