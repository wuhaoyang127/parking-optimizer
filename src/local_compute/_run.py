"""local_compute 包：单次仿真运行 + 指标平均 + 车辆序列化。"""
import time

from parking_opt.routing.path_engine import PathEngine
from parking_opt.simulation.parking_lot import ParkingLot
from parking_opt.simulation.engine import SimulationEngine
from parking_opt.evaluation.metrics import compute_metrics


def run_single(net, spots, vehicles, strategy, seed, wait_policy="fifo",
               car_speed=1.39, max_wait_time=1800):
    # 重置车位状态，避免多次运行时复用污染（compare_all 循环会复用 spots）
    for s in spots:
        s.is_occupied = False
        s.occupied_by = None
    pe = PathEngine(net); lot = ParkingLot(spots)
    engine = SimulationEngine(lot, pe, vehicles, strategy, seed=seed, wait_policy=wait_policy,
                              car_speed=car_speed, max_wait_time=max_wait_time)
    t0 = time.time(); events = engine.run()
    m = compute_metrics(events, len(spots)); m["runtime_s"] = round(time.time() - t0, 3)
    m["strategy"] = strategy.name; return m, events, lot


# 计数类指标（次数）：多种子取平均后四舍五入为整数，避免显示成小数
COUNT_FIELDS = {"shift_count", "rejected_count", "buffer_failed_count"}


def _avg_metrics(metrics_list):
    """对多个 metrics dict 取平均：数值字段求均值，非数值字段保留第一个（用于多 seed 统计）。
    计数类字段（移位/拒绝/缓冲失败次数）取平均后四舍五入为整数。"""
    if not metrics_list:
        return None
    first = metrics_list[0]
    avg = dict(first)
    for k, v in first.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            vals = [m[k] for m in metrics_list if isinstance(m.get(k), (int, float))]
            if vals:
                mean = sum(vals) / len(vals)
                avg[k] = int(mean + 0.5) if k in COUNT_FIELDS else round(mean, 4)
    return avg


def _vehicle_to_dict(v) -> dict:
    """Vehicle → 可 JSON 序列化的 dict（本地计算任务回传用）。"""
    return {
        "vehicle_id": v.vehicle_id,
        "arrival_time": float(getattr(v, "arrival_time", 0.0) or 0.0),
        "parking_duration": float(getattr(v, "parking_duration", 0.0) or 0.0),
        "estimated_duration": float(getattr(v, "estimated_duration", 0.0) or 0.0),
        "assigned_spot": getattr(v, "assigned_spot", None),
        "rejected": bool(getattr(v, "rejected", False)),
        "wait_start": getattr(v, "wait_start", None),
        "wait_end": getattr(v, "wait_end", None),
        "entry_id": getattr(v, "entry_id", None),
        "exit_id": getattr(v, "exit_id", None),
    }
