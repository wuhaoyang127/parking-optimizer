from __future__ import annotations
from typing import Annotated, Literal
from pydantic import Field, model_validator
from parking_opt.api.models import SCHEMA_VERSION, ContractModel, Identifier
from parking_opt.api.models_discovery import BufferSpace, ChannelZone, ParkingSpace, RoadEdge, RoadNode, TandemGroup

class Layout(ContractModel):
    schema_version: Literal["2.0.0"] = SCHEMA_VERSION
    parking_lot_id: Identifier
    layout_version: Identifier
    coordinate_system: Literal["local_meters"] = "local_meters"
    coordinate_origin_note: str = Field(min_length=1, max_length=200)
    entrance_node_ids: tuple[Identifier, ...] = Field(min_length=1)
    exit_node_ids: tuple[Identifier, ...] = Field(min_length=1)
    nodes: tuple[RoadNode, ...] = Field(min_length=2)
    edges: tuple[RoadEdge, ...] = Field(min_length=1)
    channel_zones: tuple[ChannelZone, ...]
    spaces: tuple[ParkingSpace, ...] = Field(min_length=1)
    tandem_groups: tuple[TandemGroup, ...] = ()
    buffers: tuple[BufferSpace, ...] = ()
    @model_validator(mode="after")
    def verify_layout_references(self) -> Layout:
        nodes_by_id = {item.node_id: item for item in self.nodes}
        node_ids = set(nodes_by_id)
        if len(node_ids) != len(self.nodes):
            raise ValueError("node ids must be unique")
        if len(set(self.entrance_node_ids)) != len(self.entrance_node_ids):
            raise ValueError("entrance node ids must be unique")
        if len(set(self.exit_node_ids)) != len(self.exit_node_ids):
            raise ValueError("exit node ids must be unique")
        edge_ids = {item.edge_id for item in self.edges}
        if len(edge_ids) != len(self.edges):
            raise ValueError("edge ids must be unique")
        if not set(self.entrance_node_ids + self.exit_node_ids) <= node_ids:
            raise ValueError("entrance and exit nodes must exist")
        if any(nodes_by_id[item_id].kind != "entrance" for item_id in self.entrance_node_ids):
            raise ValueError("entrance_node_ids must reference entrance nodes")
        if any(nodes_by_id[item_id].kind != "exit" for item_id in self.exit_node_ids):
            raise ValueError("exit_node_ids must reference exit nodes")
        if set(self.entrance_node_ids) != {item.node_id for item in self.nodes if item.kind == "entrance"}:
            raise ValueError("all entrance nodes must be declared in entrance_node_ids")
        if set(self.exit_node_ids) != {item.node_id for item in self.nodes if item.kind == "exit"}:
            raise ValueError("all exit nodes must be declared in exit_node_ids")
        channel_zone_ids = {item.channel_zone_id for item in self.channel_zones}
        if len(channel_zone_ids) != len(self.channel_zones):
            raise ValueError("channel zone ids must be unique")
        for edge in self.edges:
            if edge.from_node_id not in node_ids or edge.to_node_id not in node_ids:
                raise ValueError(f"edge {edge.edge_id} references an unknown node")
            if len(set(edge.channel_zone_ids)) != len(edge.channel_zone_ids):
                raise ValueError(f"edge {edge.edge_id} repeats a channel zone")
            if not set(edge.channel_zone_ids) <= channel_zone_ids:
                raise ValueError(f"edge {edge.edge_id} references an unknown channel zone")
        space_ids = {item.space_id for item in self.spaces}
        if len(space_ids) != len(self.spaces):
            raise ValueError("space ids must be unique")
        if any(item.parking_lot_id != self.parking_lot_id for item in self.spaces):
            raise ValueError("space belongs to another parking lot")
        for space in self.spaces:
            if space.access_node_id not in node_ids:
                raise ValueError(f"space {space.space_id} references an unknown access node")
        buffer_ids = {item.buffer_id for item in self.buffers}
        if len(buffer_ids) != len(self.buffers):
            raise ValueError("buffer ids must be unique")
        if buffer_ids & space_ids:
            raise ValueError("buffer ids and space ids must not overlap")
        for buffer in self.buffers:
            if buffer.parking_lot_id != self.parking_lot_id:
                raise ValueError(f"buffer {buffer.buffer_id} belongs to another parking lot")
            if buffer.access_node_id not in node_ids:
                raise ValueError(f"buffer {buffer.buffer_id} references an unknown access node")
            if len(set(buffer.channel_zone_ids)) != len(buffer.channel_zone_ids):
                raise ValueError(f"buffer {buffer.buffer_id} repeats a channel zone")
            if not set(buffer.channel_zone_ids) <= channel_zone_ids:
                raise ValueError(f"buffer {buffer.buffer_id} references an unknown channel zone")
        tandem_ids = {item.stack_group_id for item in self.tandem_groups}
        if len(tandem_ids) != len(self.tandem_groups):
            raise ValueError("tandem group ids must be unique")
        grouped: set[str] = set()
        by_id = {item.space_id: item for item in self.spaces}
        spaces_by_group: dict[str, list[ParkingSpace]] = {}
        for space in self.spaces:
            spaces_by_group.setdefault(space.stack_group_id, []).append(space)
        for group in self.tandem_groups:
            if len(set(group.space_ids_near_to_deep)) != len(group.space_ids_near_to_deep):
                raise ValueError(f"tandem group {group.stack_group_id} repeats a space")
            unknown_ids = set(group.space_ids_near_to_deep) - space_ids
            if unknown_ids:
                raise ValueError(f"tandem group {group.stack_group_id} references unknown spaces: {', '.join(sorted(unknown_ids))}")
            if grouped & set(group.space_ids_near_to_deep):
                raise ValueError("a space cannot belong to more than one tandem group")
            declared_group = spaces_by_group.get(group.stack_group_id, [])
            if set(group.space_ids_near_to_deep) != {item.space_id for item in declared_group}:
                raise ValueError(f"tandem group {group.stack_group_id} membership is incomplete")
            depths = sorted(item.depth for item in declared_group)
            if depths != list(range(1, len(declared_group) + 1)):
                raise ValueError(f"tandem group {group.stack_group_id} depths must be contiguous")
            expected = tuple(item.space_id for item in sorted((by_id[item_id] for item_id in group.space_ids_near_to_deep), key=lambda item: item.depth))
            if expected != group.space_ids_near_to_deep:
                raise ValueError(f"tandem group {group.stack_group_id} is not ordered by depth")
            if any(by_id[item_id].stack_group_id != group.stack_group_id for item_id in expected):
                raise ValueError("tandem group membership is inconsistent")
            grouped.update(expected)
        for group_id, members in spaces_by_group.items():
            if len(members) == 1 and members[0].depth != 1:
                raise ValueError(f"independent space group {group_id} must have depth 1")
            if len(members) > 1 and group_id not in tandem_ids:
                raise ValueError(f"stack group {group_id} lacks a tandem group declaration")
        return self
