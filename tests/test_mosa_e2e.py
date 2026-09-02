"""MOSA：端到端仿真与场景自动绑定。"""

from src.parking_opt.domain.spot import Vehicle
from src.parking_opt.strategies.mosa import MosaStrategy, estimate_scene
from src.parking_opt.strategies.baselines import FCFS

from tests._mosa_helpers import run_sim


class TestMosaEndToEnd:
    def test_runs_without_crash(self):
        m = run_sim(MosaStrategy(pop_size=8, generations=6), n_spots=15, n_vehicles=60)
        assert 0.0 <= m["satisfaction_rate"] <= 1.0
        assert m["total_vehicles"] > 0

    def test_offline_plan_not_worse_than_fcfs(self):
        """离线全信息预分配在同一需求下，满足率应不低于 FCFS（对照基准）。"""
        mosa_m = run_sim(MosaStrategy(pop_size=10, generations=8),
                         n_spots=15, n_vehicles=60)
        fcfs_m = run_sim(FCFS(), n_spots=15, n_vehicles=60)
        assert mosa_m["satisfaction_rate"] >= fcfs_m["satisfaction_rate"] - 0.05


class TestSceneAutoBinding:
    """场景权重与车位数/车辆数/时间自动绑定（共 3 种情况）。"""

    def test_estimate_binds_spots_vehicles_time(self):
        # 车少 → 平峰（重距离）
        assert estimate_scene(20, 30, 21600, 3900) == "normal"
        # 车多 → 饱和（重利用率）
        assert estimate_scene(20, 120, 21600, 3900) == "saturated"
        # 中等压力 → 高峰（重时间）
        assert estimate_scene(20, 90, 21600, 3900) == "peak"
        # 短停车时长下同样车辆数压力更低 → 平峰
        assert estimate_scene(20, 90, 21600, 600) == "normal"

    def test_scene_param_locked_in_ui(self):
        """scene 参数应标记为 locked（网页渲染为灰色不可调）。"""
        scene_spec = next(p for p in MosaStrategy.PARAMS if p["key"] == "scene")
        assert scene_spec.get("locked") is True
        assert scene_spec["default"] == "auto"

    def test_estimate_invalid_inputs_fallback_normal(self):
        assert estimate_scene(0, 10, 21600, 3900) == "normal"
        assert estimate_scene(20, 0, 21600, 3900) == "normal"
        assert estimate_scene(20, 10, 0, 3900) == "normal"

    def test_resolve_scene_uses_real_spots_and_vehicles(self):
        """运行时/真实布局场景判定：按真实车位与真实车辆精确计算（与 UI 提示共用）。"""
        from src.parking_opt.strategies.mosa import resolve_scene
        # 20 辆车，每辆停 3600s，到达间隔 300s，最后离场-首次到达 = 19*300 + 3600 = 9300s
        vehs = [Vehicle(f"V{i:02d}", i * 300, 3600, 3600) for i in range(20)]
        # 20 车位：72000 / (20*9300) = 0.387 → 平峰
        assert resolve_scene(20, vehs) == "normal"
        # 10 车位：72000 / (10*9300) = 0.774 → 高峰
        assert resolve_scene(10, vehs) == "peak"
        # 8 车位：72000 / (8*9300) = 0.968 → 饱和
        assert resolve_scene(8, vehs) == "saturated"

    def test_resolve_scene_invalid_inputs_fallback(self):
        from src.parking_opt.strategies.mosa import resolve_scene
        assert resolve_scene(0, [Vehicle("V", 0, 100, 100)]) == "normal"
        assert resolve_scene(10, []) == "normal"
