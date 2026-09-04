from __future__ import annotations
"""RHO 滚动时域动态修正策略（算法三接入）。

来源：新算法接入/算法三《SARIMA+RHO 滚动时域 实时动态修正完整解决方案》。
预测前置规划 + 滚动窗口动态纠偏 + 实时事件兜底：SARIMA-lite 免依赖预测器
（Holt 水平/趋势 + AR(1) 误差修正，生产环境可换 statsmodels SARIMA）；
RHO 每 roll_step 分钟按 E_t=|A_t-F_t|/F_t 分三级修正，5 分钟进场突发立即切
兜底，连续 2 个滚动步长回归后自动恢复。

信息边界：在线算法——只统计已到达车辆，不读未来需求，不读真实停车时长
（parking_duration），不实现 prepare()。
"""

from ..domain.spot import Spot, Vehicle
from ..simulation.parking_lot import ParkingLot
from .baselines import BaseStrategy
from .registry import StrategyRegistry
from ._rho_forecast import SarimaLite


class RhoRollingStrategy(BaseStrategy):
    """RHO 滚动时域动态修正（在线，算法三）。"""

    name = "rho_rolling"
    label = "RHO 滚动时域动态修正"
    DESCRIPTION = (
        "**RHO 滚动时域动态修正（算法三）**\\n\\n"
        "预测前置规划 + 滚动窗口动态纠偏 + 实时事件兜底。SARIMA-lite 车流预判，"
        "RHO 每 10 分钟按窗口累计偏差 E=|A−F|/F 分三级修正：\\n\\n"
        "- **轻微（≤20%）**：保持基准方案，仅增量更新预测；\\n"
        "- **中度（20%~50%）**：实际偏高用高负载算法、偏低用低负载算法；\\n"
        "- **重度（>50% 或 5 分钟突发）**：降级纯实时兜底，连续 2 步长回归后恢复。\\n\\n"
        "> 在线策略：只统计已到达车辆，不读未来需求与真实停车时长。"
    )

    PARAMS = [
        {"key": "roll_step", "label": "滚动校验步长(分钟)", "type": "int",
         "min": 1, "max": 30, "step": 1, "default": 10,
         "help": "RHO 每隔多少分钟校验一次预测偏差并修正方案"},
        {"key": "window_min", "label": "车流预测窗口(分钟)", "type": "int",
         "min": 10, "max": 120, "step": 10, "default": 60,
         "help": "每次滚动向前预测多少分钟的车流（需为步长的整数倍更佳）"},
        {"key": "mild_threshold", "label": "轻微偏差阈值", "type": "float",
         "min": 0.05, "max": 0.4, "step": 0.05, "default": 0.2,
         "help": "E≤该值判为一级轻微偏差，保持基准方案"},
        {"key": "severe_threshold", "label": "重度偏差阈值", "type": "float",
         "min": 0.3, "max": 1.0, "step": 0.05, "default": 0.5,
         "help": "E>该值判为三级重度偏差，降级纯实时兜底"},
        {"key": "burst_threshold", "label": "5分钟突发进场阈值(台)", "type": "int",
         "min": 3, "max": 30, "step": 1, "default": 10,
         "help": "5 分钟内进场超过该值立即触发事件修正（切兜底）"},
        {"key": "plan_strategy", "label": "基准方案算法", "type": "strategy",
         "default": "duration_greedy", "help": "轻微偏差时使用的基准分配算法"},
        {"key": "high_load_strategy", "label": "中度偏高算法", "type": "strategy",
         "default": "greedy", "help": "中度偏差且实际车流高于预测时使用（重吞吐）"},
        {"key": "low_load_strategy", "label": "中度偏低算法", "type": "strategy",
         "default": "nearest", "help": "中度偏差且实际车流低于预测时使用（重距离）"},
        {"key": "fallback_strategy", "label": "重度兜底算法", "type": "strategy",
         "default": "nearest", "help": "重度偏差/突发时降级使用的纯实时算法（兜底A=就近分配）"},
    ]

    BURST_WINDOW_S = 300.0   # 事件触发观察窗：5 分钟
    RECOVERY_ROLLS = 2       # 连续 N 个滚动步长回归后自动恢复

    def __init__(self, roll_step: int = 10, window_min: int = 60,
                 mild_threshold: float = 0.2, severe_threshold: float = 0.5,
                 burst_threshold: int = 10, plan_strategy: str = "duration_greedy",
                 high_load_strategy: str = "greedy", low_load_strategy: str = "nearest",
                 fallback_strategy: str = "nearest"):
        self.roll_step = int(roll_step)
        self.window_min = int(window_min)
        self.mild_threshold = float(mild_threshold)
        self.severe_threshold = float(severe_threshold)
        self.burst_threshold = int(burst_threshold)
        self.step_s = max(60.0, self.roll_step * 60.0)
        self.window_buckets = max(1, int(round(self.window_min / self.roll_step)))

        self._plan = self._sub(plan_strategy)
        self._high = self._sub(high_load_strategy)
        self._low = self._sub(low_load_strategy)
        self._fallback = self._sub(fallback_strategy)

        # 滚动预测状态
        self._forecaster = SarimaLite()
        self._bucket_counts: dict[int, int] = {}
        self._bucket_forecasts: dict[int, float] = {}
        self._seen: set[str] = set()
        self._arrival_times: list[float] = []
        self._last_roll_bucket: int | None = None
        self._mode = "plan"          # plan / adjust / fallback
        self._last_diff = 0.0        # 最近一次 A_t - F_t（决定中度偏差方向）
        self._consecutive_normal = 0

    def _sub(self, name: str):
        """实例化子算法；防止自引用导致递归。"""
        if name == self.name:
            name = "nearest"
        return StrategyRegistry.create(name)

    def _observe_arrival(self, vehicle: Vehicle, time: float) -> None:
        """按真实到达时间统计进场车流（每辆车只计一次，等待重试不重复计）。"""
        if vehicle.vehicle_id in self._seen:
            return
        self._seen.add(vehicle.vehicle_id)
        bucket = int(vehicle.arrival_time // self.step_s)
        self._bucket_counts[bucket] = self._bucket_counts.get(bucket, 0) + 1
        self._arrival_times.append(vehicle.arrival_time)

    def _roll_check(self, time: float) -> None:
        """推进滚动窗口：学习已完成时段、按窗口累计偏差分级、刷新预测。"""
        bucket = int(time // self.step_s)
        if self._last_roll_bucket is None:
            self._last_roll_bucket = bucket - 1  # 已完成到上一个时段（可能为 -1）
            return
        if bucket - 1 <= self._last_roll_bucket:
            return
        for b in range(self._last_roll_bucket + 1, bucket):
            self._process_bucket(b)
            self._last_roll_bucket = b
        self._classify_window(bucket)
        self._forecast_next(bucket)

    def _process_bucket(self, bucket: int) -> None:
        """用刚完成时段的真实车流在线更新预测器（增量学习）。"""
        self._forecaster.update(float(self._bucket_counts.get(bucket, 0)))

    def _classify_window(self, cur_bucket: int) -> None:
        """按整个预测窗口的累计偏差分级（比单时段更抗小样本噪声）。"""
        a_sum = 0.0
        f_sum = 0.0
        start = max(0, cur_bucket - self.window_buckets)
        for b in range(start, cur_bucket):
            forecast = self._bucket_forecasts.get(b)
            if forecast is None:
                continue
            a_sum += float(self._bucket_counts.get(b, 0))
            f_sum += forecast
        if f_sum <= 0.0 and a_sum <= 0.0:
            return  # 无预测且无实际：只学习，不判定
        self._apply_level(self._classify(self._deviation(a_sum, f_sum)),
                          a_sum, f_sum)

    def _forecast_next(self, start_bucket: int) -> None:
        """预测下一窗口各时段到场数，供后续偏差校验。"""
        preds = self._forecaster.predict(self.window_buckets)
        for k, p in enumerate(preds):
            self._bucket_forecasts[start_bucket + k] = p

    @staticmethod
    def _deviation(actual: float, forecast: float) -> float:
        """E_t = |A_t - F_t| / F_t（F_t=0 时用绝对偏差）。"""
        if forecast > 0:
            return abs(actual - forecast) / forecast
        return actual

    def _classify(self, dev: float) -> int:
        if dev <= self.mild_threshold:
            return 1
        if dev <= self.severe_threshold:
            return 2
        return 3

    def _apply_level(self, level: int, actual: float, forecast: float) -> None:
        if level == 1:
            if self._mode == "fallback":  # 兜底恢复需连续 2 个步长回归
                self._consecutive_normal += 1
                if self._consecutive_normal >= self.RECOVERY_ROLLS:
                    self._mode = "plan"
                    self._consecutive_normal = 0
            else:
                self._mode = "plan"
            return
        if level == 2:
            self._mode = "adjust"
            self._last_diff = actual - forecast
            self._consecutive_normal = 0
            return
        self._mode = "fallback"
        self._consecutive_normal = 0

    def _event_check(self, time: float) -> None:
        """事件触发：5 分钟进场超阈值立即切兜底（无需等待定时窗口）。"""
        horizon = time - self.BURST_WINDOW_S
        self._arrival_times = [t for t in self._arrival_times if t > horizon]
        if len(self._arrival_times) > self.burst_threshold and self._mode != "fallback":
            self._mode = "fallback"
            self._consecutive_normal = 0

    def assign(self, vehicle: Vehicle, time: float, parking_lot: ParkingLot,
               path_engine) -> tuple[Spot | None, str]:
        self._observe_arrival(vehicle, time)
        self._roll_check(time)
        self._event_check(time)

        if self._mode == "fallback":
            return self._fallback.assign(vehicle, time, parking_lot, path_engine)
        if self._mode == "adjust":
            sub = self._high if self._last_diff > 0 else self._low
            return sub.assign(vehicle, time, parking_lot, path_engine)
        return self._plan.assign(vehicle, time, parking_lot, path_engine)
