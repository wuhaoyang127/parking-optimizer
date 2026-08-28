from __future__ import annotations
"""路网路径引擎：NetworkX 封装

支持多个入口（entry）与多个出口（exit）：
- ``entry_ids`` / ``exit_ids``：布局中全部入口/出口节点ID（按遍历顺序）；
- ``entry_id``：默认入口（优先 "ENTRY"，否则第一个入口），向后兼容旧调用；
- ``default_exit_id``：默认出口（优先 "EXIT"，否则第一个出口）；无出口时返回 None，
  调用方应回退到默认入口（旧布局兼容）。
"""

import networkx as nx
from ..domain.spot import RoadNetwork, RoadNode, NodeType


class PathEngine:
    """计算停车场路网最短路径"""

    def __init__(self, road_network: RoadNetwork):
        self.network = road_network
        self.graph = nx.DiGraph()
        self._entry_ids: list[str] = []
        self._exit_ids: list[str] = []
        self._build_graph()

    def _build_graph(self):
        """从 RoadNetwork 构建 NetworkX 有向图"""
        for node_id, node in self.network.nodes.items():
            self.graph.add_node(node_id)
            if node.node_type == NodeType.ENTRY:
                self._entry_ids.append(node_id)
            elif node.node_type == NodeType.EXIT:
                self._exit_ids.append(node_id)

        for edge in self.network.edges:
            self.graph.add_edge(edge.from_node, edge.to_node, weight=edge.length)

    # ========== 入口 / 出口 ==========

    @property
    def entry_ids(self) -> list[str]:
        """布局中全部入口节点ID（按遍历顺序）。"""
        return list(self._entry_ids)

    @property
    def exit_ids(self) -> list[str]:
        """布局中全部出口节点ID（按遍历顺序）。"""
        return list(self._exit_ids)

    @property
    def entry_id(self) -> str:
        """默认入口：优先 "ENTRY"，否则第一个入口（向后兼容）。"""
        if not self._entry_ids:
            raise ValueError("路网中没有入口节点")
        if "ENTRY" in self._entry_ids:
            return "ENTRY"
        return self._entry_ids[0]

    @property
    def default_exit_id(self) -> str | None:
        """默认出口：优先 "EXIT"，否则第一个出口；无出口返回 None。"""
        if not self._exit_ids:
            return None
        if "EXIT" in self._exit_ids:
            return "EXIT"
        return self._exit_ids[0]

    def resolve_entry(self, entry_id: str | None) -> str:
        """把车辆入口解析为有效入口节点ID：None 或非法值回退默认入口。"""
        if entry_id and entry_id in self._entry_ids:
            return entry_id
        return self.entry_id

    def resolve_exit(self, exit_id: str | None) -> str:
        """把车辆出口解析为有效出口节点ID：None 或非法值回退默认出口；
        布局没有出口节点时回退默认入口（旧布局兼容，离场回入口）。"""
        if exit_id and exit_id in self._exit_ids:
            return exit_id
        default = self.default_exit_id
        if default is not None:
            return default
        return self.entry_id

    # ========== 最短路径 ==========

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

    def distance_to_spot(self, spot_node_id: str, entry_id: str | None = None) -> float:
        """从入口到某车位的距离。

        ``entry_id`` 为 None 时用默认入口（向后兼容旧调用）；多入口场景下
        调用方应传入车辆入口（``vehicle.entry_id`` 解析后的值）。
        """
        origin = self.resolve_entry(entry_id)
        return self.shortest_distance(origin, spot_node_id)

    def distance_matrix(self) -> dict[str, dict[str, float]]:
        """所有节点对最短距离矩阵"""
        return dict(nx.all_pairs_dijkstra_path_length(self.graph, weight='weight'))
