"""领域模型：数据类定义"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SpotType(Enum):
    STANDALONE = "STANDALONE"
    TANDEM = "TANDEM"


class NodeType(Enum):
    ENTRY = "entry"
    EXIT = "exit"
    ROAD_NODE = "road_node"
    PARKING_SPOT = "parking_spot"


@dataclass
class Spot:
    """车位"""
    spot_id: str
    spot_type: SpotType
    node_id: str              # 路网节点ID
    stack_group_id: str       # 纵深组ID（独立车位=唯一ID）
    depth: int                # 1=靠通道
    x: float = 0.0
    y: float = 0.0
    is_occupied: bool = False
    occupied_by: Optional[str] = None  # vehicle_id

    def is_standalone(self) -> bool:
        return self.spot_type == SpotType.STANDALONE

    def is_deepest(self, group_spots: list["Spot"]) -> bool:
        """是否是该纵深组中最深的车位"""
        return self.depth == max(s.depth for s in group_spots)


@dataclass
class Vehicle:
    """车辆需求"""
    vehicle_id: str
    arrival_time: float           # 到达时间(s)
    parking_duration: float       # 真实停车时长(s), 在线策略不可读
    estimated_duration: float     # 估计时长(s), 在线策略可用
    assigned_spot: Optional[str] = None  # spot_id
    rejected: bool = False
    wait_start: Optional[float] = None
    wait_end: Optional[float] = None
    entry_id: Optional[str] = None  # 指定入口节点ID（None=默认入口）
    exit_id: Optional[str] = None   # 指定出口节点ID（None=默认出口/回退入口）

    @property
    def departure_time(self) -> float:
        return self.arrival_time + self.parking_duration

    @property
    def estimated_departure(self) -> float:
        return self.arrival_time + self.estimated_duration


@dataclass
class RoadNode:
    """路网节点"""
    node_id: str
    node_type: NodeType
    x: float = 0.0
    y: float = 0.0
    # parking_spot 专属字段
    spot_type: Optional[SpotType] = None
    stack_group_id: Optional[str] = None
    depth: Optional[int] = None


@dataclass
class RoadEdge:
    """路网有向边"""
    from_node: str
    to_node: str
    length: float  # 米


@dataclass
class RoadNetwork:
    """停车场路网"""
    nodes: dict[str, RoadNode] = field(default_factory=dict)
    edges: list[RoadEdge] = field(default_factory=list)

    def add_node(self, node: RoadNode):
        self.nodes[node.node_id] = node

    def add_edge(self, from_id: str, to_id: str, length: float):
        self.edges.append(RoadEdge(from_id, to_id, length))


class EventType(Enum):
    VEHICLE_ARRIVAL = "vehicle_arrival"
    PARKING_ASSIGNED = "parking_assigned"
    SPOT_ENTRY = "spot_entry"
    DEPARTURE = "departure"
    SHIFT_START = "shift_start"
    SHIFT_END = "shift_end"
    REJECTED = "rejected"
    DEGRADATION = "degradation"
    WAIT_START = "wait_start"
    WAIT_END = "wait_end"
    BUFFER_FAILED = "buffer_failed"


@dataclass
class Event:
    """仿真事件"""
    time: float
    event_type: EventType
    vehicle_id: Optional[str] = None
    spot_id: Optional[str] = None
    strategy: Optional[str] = None
    metadata: dict = field(default_factory=dict)
