"""risk_scoring 测试共享辅助（pytest 不收集本文件）。"""

from src.parking_opt.domain.spot import Spot, SpotType, Vehicle
from src.parking_opt.simulation.parking_lot import ParkingLot


class StubPathEngine:
    """按 node_id 返回可配置距离的路径引擎替身。"""

    def __init__(self, distances=None):
        self.distances = distances or {}

    def distance_to_spot(self, node_id, entry_id=None):
        return self.distances.get(node_id, 1.0)

    def shortest_distance(self, a, b):
        return 1.0


def build_lot():
    """2 独立位 + 1 个 2 深纵深组（G1-1 外层, G1-2 里层）。"""
    spots = [
        Spot("A1", SpotType.STANDALONE, "A1", "A1", 1),
        Spot("A2", SpotType.STANDALONE, "A2", "A2", 1),
        Spot("G1-1", SpotType.TANDEM, "G1-1", "G1", 1),
        Spot("G1-2", SpotType.TANDEM, "G1-2", "G1", 2),
    ]
    return ParkingLot(spots)


def veh(vid, arrival=0.0, real=1800.0, est=1800.0):
    """构造车辆；real=真实停车时长(策略不可读)，est=预估时长(策略可用)。"""
    return Vehicle(vid, arrival_time=arrival, parking_duration=real,
                   estimated_duration=est)
