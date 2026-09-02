"""MOSA 测试共享辅助（pytest 不收集本文件，仅被 test_mosa_* 导入）。"""

from src.parking_opt.domain.spot import RoadNetwork, RoadNode, NodeType, Spot, SpotType
from src.parking_opt.routing.path_engine import PathEngine
from src.parking_opt.simulation.parking_lot import ParkingLot
from src.parking_opt.simulation.engine import SimulationEngine
from src.parking_opt.simulation.arrival import generate_demand
from src.parking_opt.evaluation.metrics import compute_metrics


def build_net_spots(n_spots=15, tandem_ratio=0.5):
    """构建小规模测试路网（矩形），返回 (RoadNetwork, list[Spot])。"""

    def _an(net, nid, nt, x, y, st=None, sg=None, dp=None):
        net.add_node(RoadNode(nid, nt, x, y, st, sg, dp))

    net = RoadNetwork()
    _an(net, "ENTRY", NodeType.ENTRY, 0, 0)
    _an(net, "M", NodeType.ROAD_NODE, 8, 0)
    _an(net, "U", NodeType.ROAD_NODE, 8, 6)
    _an(net, "D", NodeType.ROAD_NODE, 8, -6)
    for a, b, d in [("ENTRY", "M", 8), ("M", "U", 6), ("M", "D", 6),
                    ("U", "M", 6), ("D", "M", 6)]:
        net.add_edge(a, b, d)
    spots = []
    half = n_spots // 2
    nt = int(half * tandem_ratio / 2)
    ns = half - nt * 2
    for row, rd, ys in [("U", "U", 1), ("D", "D", -1)]:
        for i in range(ns):
            sid = f"{row}{i + 1:02d}"
            _an(net, sid, NodeType.PARKING_SPOT, 12 + i * 4.5, ys * 9,
                SpotType.STANDALONE, sid, 1)
            net.add_edge(rd, sid, 3)
            net.add_edge(sid, rd, 3)
            spots.append(Spot(sid, SpotType.STANDALONE, sid, sid, 1))
        for g in range(nt):
            gid = f"{row}G{g + 1}"
            prev = rd
            bx = 12 + ns * 4.5 + g * 7
            by = ys * 9
            for d in range(1, 3):
                sid = f"{gid}-{d}"
                _an(net, sid, NodeType.PARKING_SPOT, bx + d * 3.5, by,
                    SpotType.TANDEM, gid, d)
                net.add_edge(prev, sid, 3.5)
                net.add_edge(sid, prev, 3.5)
                prev = sid
                spots.append(Spot(sid, SpotType.TANDEM, sid, gid, d))
    return net, spots


def run_sim(strategy, n_spots=15, n_vehicles=60, seed=42):
    """跑一次完整仿真，返回 metrics dict。"""
    net, spots = build_net_spots(n_spots)
    pe = PathEngine(net)
    lot = ParkingLot(spots)
    vehicles = generate_demand(total_vehicles=n_vehicles, seed=seed)
    events = SimulationEngine(lot, pe, vehicles, strategy, seed=seed).run()
    return compute_metrics(events, len(spots))


class _PrepareProbe:
    """验证引擎调用 prepare 钩子的探针策略。"""

    name = "prepare_probe"

    def __init__(self):
        self.prepare_calls = 0
        self.seen_vehicles = 0

    def prepare(self, vehicles, parking_lot, path_engine):
        self.prepare_calls += 1
        self.seen_vehicles = len(vehicles)

    def assign(self, vehicle, time, parking_lot, path_engine):
        available = parking_lot.get_available_spots()
        if not available:
            return (None, "waiting")
        return (available[0], "assigned")
