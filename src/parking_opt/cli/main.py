"""命令行入口：运行仿真实验"""

import argparse
import json
from pathlib import Path

from ..domain.spot import Spot, SpotType, RoadNetwork, RoadNode, NodeType
from ..io.road_io import load_road_network, save_events, save_metrics, load_config
from ..routing.path_engine import PathEngine
from ..simulation.parking_lot import ParkingLot
from ..simulation.engine import SimulationEngine
from ..simulation.arrival import generate_demand
from ..strategies import StrategyRegistry
from ..evaluation.metrics import compute_metrics


def build_test_network(n_spots: int = 20, tandem_ratio: float = 0.3) -> RoadNetwork:
    """构建测试用路网（简化矩形停车场）"""
    network = RoadNetwork()
    network.add_node(RoadNode("ENTRY", NodeType.ENTRY, 0, 0))
    network.add_node(RoadNode("EXIT", NodeType.EXIT, 50, 0))
    network.add_node(RoadNode("N0", NodeType.ROAD_NODE, 5, 0))

    network.add_edge("ENTRY", "N0", 5.0)
    network.add_edge("N0", "EXIT", 45.0)

    spot_id = 0
    n_tandem_groups = int(n_spots * tandem_ratio / 2)  # 每组2深度
    n_standalone = n_spots - n_tandem_groups * 2

    x = 10.0
    y_offset = 3.0

    # 独立车位
    for i in range(n_standalone):
        sid = f"A{spot_id+1:02d}"
        network.add_node(RoadNode(sid, NodeType.PARKING_SPOT, x, y_offset,
                                   SpotType.STANDALONE, sid, 1))
        network.add_edge("N0", sid, abs(x - 5))
        network.add_edge(sid, "N0", abs(x - 5))
        x += 5.0
        spot_id += 1

    # 纵深车位（每组2深度）
    for g in range(n_tandem_groups):
        gid = f"G{g+1}"
        for d in range(1, 3):
            sid = f"{gid}-{d}"
            network.add_node(RoadNode(sid, NodeType.PARKING_SPOT, x, y_offset,
                                       SpotType.TANDEM, gid, d))
            if d == 1:
                network.add_edge("N0", sid, abs(x - 5))
            network.add_edge(sid, "N0", abs(x - 5))
            x += 5.0
            spot_id += 1

    return network


def spots_from_network(network: RoadNetwork) -> list[Spot]:
    """从路网提取Spot列表"""
    spots = []
    for node in network.nodes.values():
        if node.node_type == NodeType.PARKING_SPOT:
            spots.append(Spot(
                spot_id=node.node_id,
                spot_type=node.spot_type or SpotType.STANDALONE,
                node_id=node.node_id,
                stack_group_id=node.stack_group_id or node.node_id,
                depth=node.depth or 1,
                x=node.x, y=node.y,
            ))
    return spots


def main():
    parser = argparse.ArgumentParser(description="智能停车场仿真")
    parser.add_argument("--network", type=str, help="路网JSON文件路径")
    parser.add_argument("--strategy", type=str, default="greedy",
                        choices=list(StrategyRegistry.all().keys()))
    parser.add_argument("--vehicles", type=int, default=150)
    parser.add_argument("--spots", type=int, default=20, help="测试路网车位数")
    parser.add_argument("--tandem-ratio", type=float, default=0.3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=str, default="outputs")
    args = parser.parse_args()

    # 路网
    if args.network:
        network = load_road_network(args.network)
    else:
        network = build_test_network(args.spots, args.tandem_ratio)

    spots = spots_from_network(network)
    path_engine = PathEngine(network)
    parking_lot = ParkingLot(spots)

    # 需求
    vehicles = generate_demand(total_vehicles=args.vehicles, seed=args.seed)

    # 策略
    strategy = StrategyRegistry.create(args.strategy)

    # 仿真
    engine = SimulationEngine(parking_lot, path_engine, vehicles, strategy, args.seed)
    events = engine.run()

    # 指标
    metrics = compute_metrics(events, len(spots))
    metrics["strategy"] = args.strategy
    metrics["seed"] = args.seed

    # 输出
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    save_events(events, out_dir / "events.jsonl")
    save_metrics(metrics, out_dir / "metrics.json")

    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
