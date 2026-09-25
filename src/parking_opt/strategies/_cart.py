"""CART 回归树（纯 numpy 实现，供机器学习策略使用，不新增第三方依赖）。

只做回归（叶节点输出均值），分裂准则为方差减少（MSE gain）。
本项目样本量小（数百辆车 × 个位数特征），朴素 O(n²d) 实现足够快。
"""

from __future__ import annotations

import numpy as np


class _TreeNode:
    """回归树节点：叶节点只有 value；内部节点另有 feature/threshold 与左右子树。"""

    __slots__ = ("feature", "threshold", "left", "right", "value")

    def __init__(self):
        self.feature = None      # int | None
        self.threshold = None    # float | None
        self.left = None         # _TreeNode | None
        self.right = None        # _TreeNode | None
        self.value = 0.0         # 预测值（内部节点也存，便于回退/裁剪）

    def predict_one(self, x) -> float:
        node = self
        while node.feature is not None:
            node = node.left if x[node.feature] <= node.threshold else node.right
        return node.value


class CartRegressor:
    """CART 回归树。

    fit(X, y)：训练；predict(X)：批量预测；predict_one(x)：单样本预测。
    """

    def __init__(self, max_depth: int = 4, min_samples_leaf: int = 5):
        self.max_depth = int(max_depth)
        self.min_samples_leaf = int(min_samples_leaf)
        self.root = _TreeNode()

    def fit(self, X, y) -> "CartRegressor":
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float)
        if len(y) == 0:
            self.root.value = 0.0
            return self
        self.root = self._grow(X, y, depth=0)
        return self

    def predict(self, X) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        return np.asarray([self.root.predict_one(row) for row in X], dtype=float)

    def predict_one(self, x) -> float:
        return float(self.root.predict_one(np.asarray(x, dtype=float)))

    def _grow(self, X, y, depth) -> _TreeNode:
        node = _TreeNode()
        node.value = float(np.mean(y))
        if (depth >= self.max_depth or len(y) < 2 * self.min_samples_leaf
                or float(np.ptp(y)) <= 1e-9):
            return node

        n, d = X.shape
        best_gain = 1e-12
        best_feature = None
        best_threshold = None

        for f in range(d):
            vals = X[:, f]
            order = np.argsort(vals)
            svals = vals[order]
            sy = y[order]
            for i in range(1, n):
                if svals[i] == svals[i - 1]:
                    continue
                if i < self.min_samples_leaf or n - i < self.min_samples_leaf:
                    continue
                thr = (float(svals[i - 1]) + float(svals[i])) / 2.0
                yl, yr = sy[:i], sy[i:]
                gain = (float(np.var(sy))
                        - (len(yl) / n) * float(np.var(yl))
                        - (len(yr) / n) * float(np.var(yr)))
                if gain > best_gain:
                    best_gain = gain
                    best_feature = f
                    best_threshold = thr

        if best_feature is None:
            return node

        node.feature = best_feature
        node.threshold = best_threshold
        left_mask = X[:, best_feature] <= best_threshold
        node.left = self._grow(X[left_mask], y[left_mask], depth + 1)
        node.right = self._grow(X[~left_mask], y[~left_mask], depth + 1)
        return node
