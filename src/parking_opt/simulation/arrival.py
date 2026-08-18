"""车辆需求生成器：仿真数据"""

import random
from ..domain.spot import Vehicle
from .defaults import (SIM_DURATION, DURATION_MIN, DURATION_MAX,
                       PEAK_RATIO, ERROR_RATIO)


def generate_demand(total_vehicles: int = 150,
                    sim_duration: float = SIM_DURATION,
                    duration_min: float = DURATION_MIN,
                    duration_max: float = DURATION_MAX,
                    peak_ratio: float = PEAK_RATIO,
                    error_ratio: float = ERROR_RATIO,
                    seed: int = 42) -> list[Vehicle]:
    """
    生成仿真车辆需求（双峰到达分布）

    参数:
        total_vehicles: 车辆总数
        sim_duration: 仿真时长(s), 默认21600=6h（让车位更紧张，策略差异明显）
        duration_min/max: 停车时长范围(s), 默认10min~2h
        peak_ratio: 高峰时段车辆占比
        error_ratio: 预估时长相对真实时长的误差上限（±比例）
        seed: 随机种子
    """
    random.seed(seed)

    vehicles = []
    # 高峰时间用仿真时长的比例（早高峰 35%，晚高峰 73%）
    peak1 = sim_duration * 0.35
    peak2 = sim_duration * 0.73
    for i in range(total_vehicles):
        vid = f"V{i+1:04d}"

        # 到达时间：双峰分布（高峰集中到达，制造短时拥堵）
        if random.random() < peak_ratio:
            # 高峰时段集中到达，标准差 600s(10分钟)，形成排队等待
            if random.random() < 0.5:
                arrival = random.gauss(peak1, 600)  # 早高峰集中
            else:
                arrival = random.gauss(peak2, 600)  # 晚高峰集中
        else:
            # 平峰均匀分布
            arrival = random.uniform(0, sim_duration)

        arrival = max(0, min(arrival, sim_duration - 600))  # 裁剪

        # 停车时长
        parking_duration = random.uniform(duration_min, duration_max)

        # 预估时长 = 真实时长 × (1 ± error_ratio)，模拟系统对停车时长的预估
        # （在线策略可利用 estimated_duration 做时长感知分配，但无法读到真实 parking_duration）
        error = random.uniform(-error_ratio, error_ratio)
        estimated_duration = parking_duration * (1 + error)

        vehicles.append(Vehicle(
            vehicle_id=vid,
            arrival_time=arrival,
            parking_duration=parking_duration,
            estimated_duration=estimated_duration,
        ))

    return sorted(vehicles, key=lambda v: v.arrival_time)
