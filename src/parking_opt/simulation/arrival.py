"""车辆需求生成器：仿真数据"""

import random
from ..domain.spot import Vehicle


def generate_demand(total_vehicles: int = 150,
                    sim_duration: float = 86400.0,
                    duration_min: float = 2400.0,
                    duration_max: float = 21600.0,
                    peak_ratio: float = 0.7,
                    seed: int = 42) -> list[Vehicle]:
    """
    生成仿真车辆需求（双峰到达分布）

    参数:
        total_vehicles: 车辆总数
        sim_duration: 仿真时长(s), 默认86400=24h
        duration_min/max: 停车时长范围(s), 默认40min~6h
        peak_ratio: 高峰时段车辆占比
        seed: 随机种子
    """
    random.seed(seed)

    vehicles = []
    for i in range(total_vehicles):
        vid = f"V{i+1:04d}"

        # 到达时间：双峰分布
        if random.random() < peak_ratio:
            # 高峰时段 (8:00-9:00 或 17:00-18:00 附近)
            if random.random() < 0.5:
                arrival = random.gauss(8 * 3600 + 1800, 1800)  # 早高峰
            else:
                arrival = random.gauss(17 * 3600 + 1800, 1800)  # 晚高峰
        else:
            # 平峰均匀分布
            arrival = random.uniform(0, sim_duration)

        arrival = max(0, min(arrival, sim_duration - 600))  # 裁剪

        # 停车时长
        parking_duration = random.uniform(duration_min, duration_max)

        # 预估时长 = 真实时长 × (1 ± 30% 误差)，模拟系统对停车时长的预估
        # （在线策略可利用 estimated_duration 做时长感知分配，但无法读到真实 parking_duration）
        error = random.uniform(-0.3, 0.3)
        estimated_duration = parking_duration * (1 + error)

        vehicles.append(Vehicle(
            vehicle_id=vid,
            arrival_time=arrival,
            parking_duration=parking_duration,
            estimated_duration=estimated_duration,
        ))

    return sorted(vehicles, key=lambda v: v.arrival_time)
