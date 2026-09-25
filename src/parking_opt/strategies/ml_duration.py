from __future__ import annotations
"""机器学习策略：CART 回归树预测停车时长 + 时长感知贪心分配。

信息边界（与 MOSA 同为「离线训练/优化 + 在线执行」口径）：
- prepare（离线，可读全量需求）：用当前需求序列训练回归树，标签为真实停车
  时长 parking_duration，但特征只用在线可观测的「到达时刻 / 入口」；
- assign（在线）：只读当前车辆可观测特征做预测，用预测时长替代
  estimated_duration 做内外层分流，不读未来需求与真实停车时长。

对比口径：duration_greedy 在线使用带误差的 estimated_duration（噪声 oracle），
本策略在线使用模型预测 ŷ；两者评分标准完全一致（同一套加权/字典序排名）。
"""

import numpy as np

from ..domain.spot import Spot, SpotType, Vehicle
from ..simulation.parking_lot import ParkingLot
from ._cart import CartRegressor
from .baselines import BaseStrategy
from .registry import CATEGORY_ML


class MlDurationTreeStrategy(BaseStrategy):
    """ML 时长预测树：学习「到达时段/入口 → 停车时长」规律后在线选位。"""

    name = "ml_duration_tree"
    label = "ML 时长预测树"
    category = CATEGORY_ML
    DESCRIPTION = (
        "**ML 时长预测树**\n\n"
        "机器学习策略：离线用 CART 回归树学习「到达时段/入口 → 停车时长」的映射，"
        "在线对来车预测停车时长，再按时长感知贪心分流（短停放外层、长停放里层，减少移位）。\n\n"
        "- 训练（prepare，离线全信息）：标签为历史真实停车时长，特征只用在线可观测的到达时刻与入口；\n"
        "- 预测（assign，在线合法）：不读未来需求与真实停车时长；\n"
        "- 预测无区分度时自动退化为「外层优先」贪心（与朴素贪心一致）；\n"
        "- 与 MOSA 同属「离线训练/优化 + 在线执行」口径，网页按 ml 分类单独对比。"
    )

    PARAMS = [
        {"key": "max_depth", "label": "树最大深度", "type": "int",
         "min": 2, "max": 8, "step": 1, "default": 4,
         "help": "回归树最大深度，越大越能拟合复杂时段规律，也越容易过拟合"},
        {"key": "min_samples_leaf", "label": "叶最小样本数", "type": "int",
         "min": 1, "max": 20, "step": 1, "default": 5,
         "help": "叶节点最少样本数，越大预测越平滑"},
        {"key": "use_entry", "label": "使用入口特征", "type": "bool",
         "default": True,
         "help": "把车辆入口作为特征（多入口布局下更有效）"},
    ]

    def __init__(self, max_depth: int = 4, min_samples_leaf: int = 5,
                 use_entry: bool = True):
        self.max_depth = int(max_depth)
        self.min_samples_leaf = int(min_samples_leaf)
        self.use_entry = bool(use_entry)
        self._tree = None
        self._threshold = 3600.0
        self._fallback = 3600.0
        self._degenerate = True
        self._entries = []

    # ── 离线训练 ──
    def prepare(self, vehicles, parking_lot, path_engine):
        X, y = self._build_dataset(vehicles)
        self._tree = None
        self._threshold = 3600.0
        self._fallback = 3600.0
        self._degenerate = True
        if X is None or len(y) < max(2, 2 * self.min_samples_leaf):
            return
        tree = CartRegressor(self.max_depth, self.min_samples_leaf).fit(X, y)
        preds = tree.predict(X)
        self._tree = tree
        self._threshold = float(np.median(y))
        self._fallback = float(np.mean(y))
        # 预测值变化范围小于真实时长均值 5% 视为「无区分度」，
        # 退化为外层优先贪心（避免噪声分裂误导分流）。
        self._degenerate = bool(np.ptp(preds) <= 0.05 * float(np.mean(y)))

    # ── 在线分配 ──
    def assign(self, vehicle, time, parking_lot, path_engine):
        available = parking_lot.get_available_spots()
        if not available:
            return (None, "waiting")

        entry = getattr(vehicle, "entry_id", None)
        standalone = [s for s in available if s.spot_type == SpotType.STANDALONE]
        depth1 = [s for s in available if s.spot_type == SpotType.TANDEM and s.depth == 1]
        depth_n = [s for s in available if s.spot_type == SpotType.TANDEM and s.depth > 1]

        # 1. 独立车位优先（无阻挡问题），选最近
        if standalone:
            best = min(standalone, key=lambda s: path_engine.distance_to_spot(s.node_id, entry))
            return (best, "assigned")

        # 2. 预测无区分度：退化为外层优先贪心（与朴素贪心一致）
        if self._degenerate:
            if depth1:
                best = min(depth1, key=lambda s: path_engine.distance_to_spot(s.node_id, entry))
                return (best, "assigned")
            if depth_n:
                best = min(depth_n, key=lambda s: self._inner_estimated_departure(s, parking_lot))
                return (best, "assigned")
            return (None, "waiting")

        # 3. 预测时长分流：短停→外层、长停→里层（与 duration_greedy 同构）
        est = self._predict_duration(vehicle)
        if depth1 and depth_n:
            if est < self._threshold:
                best = min(depth1, key=lambda s: path_engine.distance_to_spot(s.node_id, entry))
                return (best, "assigned")
            best = min(depth_n, key=lambda s: self._inner_estimated_departure(s, parking_lot))
            return (best, "assigned")

        if depth1:
            best = min(depth1, key=lambda s: path_engine.distance_to_spot(s.node_id, entry))
            return (best, "assigned")
        if depth_n:
            best = min(depth_n, key=lambda s: self._inner_estimated_departure(s, parking_lot))
            return (best, "assigned")
        return (None, "waiting")

    # ── 内部工具 ──
    def _build_dataset(self, vehicles):
        vehicles = list(vehicles or [])
        if not vehicles:
            return None, None
        if self.use_entry:
            self._entries = sorted({getattr(v, "entry_id", None) for v in vehicles
                                    if getattr(v, "entry_id", None) is not None})
        X = np.asarray([self._features(v) for v in vehicles], dtype=float)
        y = np.asarray([float(getattr(v, "parking_duration", 0.0) or 0.0)
                        for v in vehicles], dtype=float)
        return X, y

    def _features(self, vehicle):
        feats = [float(getattr(vehicle, "arrival_time", 0.0) or 0.0)]
        if self.use_entry and self._entries:
            e = getattr(vehicle, "entry_id", None)
            feats += [1.0 if e == k else 0.0 for k in self._entries]
        return feats

    def _predict_duration(self, vehicle) -> float:
        if self._tree is None:
            return self._fallback
        pred = self._tree.predict_one(self._features(vehicle))
        return float(max(pred, 1.0))

    def _inner_estimated_departure(self, spot, parking_lot) -> float:
        """返回该里层车位外侧阻挡车的预计离场时间（越早越好）。

        ML 全程使用模型预测时长（不读 estimated_duration，信息源一致）。
        """
        max_dep = 0.0
        for outer in parking_lot.get_outer_spots(spot):
            if outer.is_occupied and outer.occupied_by:
                v = parking_lot.vehicles.get(outer.occupied_by)
                if v:
                    est_dep = v.arrival_time + self._predict_duration(v)
                    if est_dep > max_dep:
                        max_dep = est_dep
        return max_dep
