from __future__ import annotations
"""路网路径引擎：NetworkX 封装"""

import networkx as nx
from ..domain.spot import RoadNetwork, RoadNode, NodeType


class PathEngine:
    """计算停车场路网最短路径"""

    def __init__(self, road_network: RoadNetwork):
        self.network = road_network
        self.graph = nx.DiGraph()
        self._entry_id: str | None = None
        self._build_graph()

    def _build_graph(self):
        """从 RoadNetwork 构建 NetworkX 有向图"""
        for node_id, node in self.network.nodes.items():
            self.graph.add_node(node_id)
            if node.node_type == NodeType.ENTRY:
                self._entry_id = node_id

        for edge in self.network.edges:
            self.graph.add_edge(edge.from_node, edge.to_node, weight=edge.length)

    @property
    def entry_id(self) -> str:
        if self._entry_id is None:
            raise ValueError("路网中没有入口节点")
        return self._entry_id

    def shortest_distance(self, from_node: str, to_node: str) -> float:
        """两点间最短距离(米)"""
        try:
            return nx.shortest_path_length(
                self.graph, from_node, to_node, weight='weight'
            )
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return float('inf')

    def shortest_path(self, from_node: str, to_node: str) -> list[str]:
        """两点间最短路径节点序列"""
        try:
            return nx.shortest_path(
                self.graph, from_node, to_node, weight='weight'
            )
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []

    def get_path_edges(self, path_nodes: list[str]) -> list[tuple[str, str, float]]:
        """把节点序列转成有向边序列 [(from, to, length)]；找不到边则返回空列表。"""
        if not path_nodes or len(path_nodes) < 2:
            return []
        edges = []
        for a, b in zip(path_nodes, path_nodes[1:]):
            data = self.graph.get_edge_data(a, b)
            if data is None:
                return []
            edges.append((a, b, float(data.get("weight", 0.0))))
        return edges

    def distance_to_spot(self, spot_node_id: str) -> float:
        """从入口到某车位的距离"""
        return self.shortest_distance(self.entry_id, spot_node_id)

    def distance_matrix(self) -> dict[str, dict[str, float]]:
        """所有节点对最短距离矩阵"""
        return dict(nx.all_pairs_dijkstra_path_length(self.graph, weight='weight'))
