"""多入口/多出口测试共享辅助（pytest 不收集本文件）。"""

from src.parking_opt.domain.spot import RoadNetwork, RoadNode, NodeType, Spot, SpotType, Vehicle


def build_two_entry_net(with_exits: bool = True) -> RoadNetwork:
    """两个入口 E1/E2，两个出口 X1/X2，两个独立车位 A/B。

    拓扑：E1-A(10m)，E2-B(10m)；A/B 均可到 X1/X2（交叉出口，验证进出可不同）。
    E1 离 A 近，E2 离 B 近。
    """
    net = RoadNetwork()
    net.add_node(RoadNode("E1", NodeType.ENTRY, 0, 0))
    net.add_node(RoadNode("E2", NodeType.ENTRY, 100, 0))
    if with_exits:
        net.add_node(RoadNode("X1", NodeType.EXIT, 0, 50))
        net.add_node(RoadNode("X2", NodeType.EXIT, 100, 50))
    net.add_node(RoadNode("A", NodeType.PARKING_SPOT, 10, 0, SpotType.STANDALONE, "A", 1))
    net.add_node(RoadNode("B", NodeType.PARKING_SPOT, 90, 0, SpotType.STANDALONE, "B", 1))
    edges = [("E1", "A", 10), ("A", "E1", 10), ("E2", "B", 10), ("B", "E2", 10)]
    if with_exits:
        # A/B 都能到 X1/X2（交叉出口，验证进出可不同）
        edges += [("A", "X1", 5), ("X1", "A", 5), ("A", "X2", 15), ("X2", "A", 15),
                  ("B", "X1", 15), ("X1", "B", 15), ("B", "X2", 5), ("X2", "B", 5)]
    for a, b, d in edges:
        net.add_edge(a, b, d)
    return net


def spots_from_net(net: RoadNetwork) -> list[Spot]:
    return [Spot(n.node_id, n.spot_type, n.node_id, n.stack_group_id or n.node_id, n.depth or 1)
            for n in net.nodes.values() if n.node_type == NodeType.PARKING_SPOT]


def make_veh(vid, entry=None, exit_=None, arrival=0.0, park=100.0):
    return Vehicle(vehicle_id=vid, arrival_time=arrival, parking_duration=park,
                   estimated_duration=park, entry_id=entry, exit_id=exit_)


def _ev(time, type_, vid, spot_id="", metadata=None):
    return {"time": time, "type": type_, "vehicle_id": vid,
            "spot_id": spot_id, "metadata": metadata or {}}
