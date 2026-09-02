from __future__ import annotations
"""MOSA 场景判定（高峰/平峰/饱和）。"""


def estimate_scene(n_spots: int, n_vehicles: int, sim_duration: float,
                   avg_duration: float) -> str:
    """按车位数/车辆数/时间预估场景权重模式（与 _resolve_scene 同一判定规则）。

    三种情况：高峰（重时间）/ 平峰（重距离）/ 饱和（重利用率）。
    UI 在运行前用本函数做预估展示；运行时 MosaStrategy 按真实生成车辆精确判定。
    """
    if n_spots <= 0 or n_vehicles <= 0 or sim_duration <= 0:
        return "normal"
    total_demand_time = n_vehicles * max(avg_duration, 1.0)
    span = sim_duration + max(avg_duration, 1.0)  # 近似时间跨度（最后到达 + 平均停车）
    demand_ratio = total_demand_time / (n_spots * span)
    if demand_ratio >= 0.85:
        return "saturated"
    if demand_ratio >= 0.6:
        return "peak"
    return "normal"


def resolve_scene(n_spots: int, vehicles) -> str:
    """按真实车位与真实车辆需求精确判定场景（运行时与 UI 预判共用同一规则）。

    与 MosaStrategy._resolve_scene 逻辑一致：总停车时长 / (车位数 × 需求时间跨度)。
    """
    if n_spots <= 0 or not vehicles:
        return "normal"
    total_demand_time = sum(v.parking_duration for v in vehicles)
    span = (max(v.departure_time for v in vehicles)
            - min(v.arrival_time for v in vehicles))
    if span <= 0:
        return "peak"
    demand_ratio = total_demand_time / (n_spots * span)
    if demand_ratio >= 0.85:
        return "saturated"
    if demand_ratio >= 0.6:
        return "peak"
    return "normal"
