from __future__ import annotations
"""算法三预测器：免依赖 SARIMA-lite（供 rho 策略使用）。

对进场车流计数序列做一阶差分（隐含在趋势项中），水平与趋势用指数平滑在线
更新，残差按 AR(1) 衰减回灌——相当于 ARIMA(1,1,1) 的轻量近似。生产环境可
替换为 statsmodels SARIMA。
"""


class SarimaLite:
    """Holt 水平/趋势 + AR(1) 误差修正的在线预测器。"""

    def __init__(self, alpha: float = 0.5, beta: float = 0.15, phi: float = 0.5):
        self.alpha = alpha
        self.beta = beta
        self.phi = phi
        self.level: float | None = None
        self.trend = 0.0
        self.last_err = 0.0

    def update(self, actual: float) -> None:
        """用刚完成时段的真实车流更新在线参数。"""
        if self.level is None:
            self.level = float(actual)
            self.trend = 0.0
            self.last_err = 0.0
            return
        one_step = self.level + self.trend + self.phi * self.last_err
        self.last_err = float(actual) - one_step
        prev_level = self.level
        self.level = self.alpha * float(actual) + (1.0 - self.alpha) * (self.level + self.trend)
        self.trend = self.beta * (self.level - prev_level) + (1.0 - self.beta) * self.trend

    def predict(self, steps: int) -> list[float]:
        """预测未来 steps 个时段的到场车辆数（非负）。"""
        if self.level is None:
            return [0.0] * max(0, steps)
        out = []
        for k in range(1, steps + 1):
            f = self.level + k * self.trend + (self.phi ** k) * self.last_err
            out.append(max(0.0, f))
        return out
