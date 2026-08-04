from __future__ import annotations
"""指标计算：从事件日志提取统计"""

from ..domain.spot import Event, EventType


def compute_metrics(events: list[Event], total_spots: int,
                    sim_duration: float | None = None) -> dict:
    """从事件日志计算所有指标"""

    # 基础计数
    arrivals = [e for e in events if e.event_type == EventType.VEHICLE_ARRIVAL]
    assigned = [e for e in events if e.event_type == EventType.PARKING_ASSIGNED]
    rejected = [e for e in events if e.event_type == EventType.REJECTED]
    shift_starts = [e for e in events if e.event_type == EventType.SHIFT_START]
    degradations = [e for e in events if e.event_type == EventType.DEGRADATION]

    total_vehicles = len(arrivals)
    n_assigned = len(assigned)
    n_rejected = len(rejected)

    # 满足率
    satisfaction_rate = n_assigned / total_vehicles if total_vehicles > 0 else 0.0

    # 仿真时长
    if sim_duration is None:
        all_times = [e.time for e in events if e.time > 0]
        sim_duration = max(all_times) if all_times else 86400

    # 利用率 (简化: 用 spot_entry 和 departure 事件计算)
    spot_entries = [e for e in events if e.event_type == EventType.SPOT_ENTRY]
    departures = [e for e in events if e.event_type == EventType.DEPARTURE]

    # 按车辆聚合占用时间
    occupied_time = 0.0
    for entry in spot_entries:
        vid = entry.vehicle_id
        dep = next((d for d in departures if d.vehicle_id == vid), None)
        if dep:
            occupied_time += dep.time - entry.time

    spatial_util = occupied_time / (total_spots * sim_duration) if sim_duration > 0 else 0.0

    # 移位统计
    shift_count = len(shift_starts)
    shift_dist = sum(e.metadata.get('distance', 0) for e in shift_starts)

    # 行驶距离
    total_drive = sum(e.metadata.get('drive_distance', 0) for e in spot_entries)

    # 等待时间
    wait_starts = {e.vehicle_id: e.time for e in events if e.event_type == EventType.WAIT_START}
    wait_ends = {e.vehicle_id: e.time for e in events if e.event_type == EventType.WAIT_END}
    wait_times = []
    for vid, start in wait_starts.items():
        end = wait_ends.get(vid, start)
        wait_times.append(end - start)
    avg_wait = sum(wait_times) / len(wait_times) if wait_times else 0.0

    return {
        "satisfaction_rate": round(satisfaction_rate, 4),
        "spatial_utilization": round(spatial_util, 4),
        "shift_count": shift_count,
        "shift_distance_m": round(shift_dist, 2),
        "total_drive_distance_m": round(total_drive, 2),
        "avg_wait_time_s": round(avg_wait, 2),
        "rejected_count": n_rejected,
        "degradation_count": len(degradations),
        "total_vehicles": total_vehicles,
        "assigned_vehicles": n_assigned,
        "sim_duration_s": round(sim_duration, 2),
    }
