"""Facility spaces/buffers/groups verification mixin."""

from __future__ import annotations

from math import cos, radians, sin

from parking_opt.api.models_discovery import Coordinate
from parking_opt.api.models_facility import FacilityBounds, FacilityRectangle


class _FacilitySpacesVerificationMixin:
    def _verify_spaces_buffers_groups(self) -> None:
        def unique(values: tuple[str, ...], label: str) -> set[str]:
            result = set(values)
            if len(result) != len(values):
                raise ValueError(f"{label} ids must be unique")
            return result

        def rectangle_fits(rectangle: FacilityRectangle, bounds: FacilityBounds) -> bool:
            angle = radians(rectangle.heading_deg)
            cosine = cos(angle)
            sine = sin(angle)
            half_width = rectangle.width_m / 2
            half_length = rectangle.length_m / 2
            return all(
                bounds.contains(Coordinate(x_m=rectangle.center.x_m + dx * cosine - dy * sine, y_m=rectangle.center.y_m + dx * sine + dy * cosine))
                for dx in (-half_width, half_width)
                for dy in (-half_length, half_length)
            )

        floor_ids = {item.floor_id for item in self.floors}
        floors_by_id = {item.floor_id: item for item in self.floors}
        zones_by_id = {item.zone_id: item for item in self.zones}
        nodes_by_id = {item.node_id: item for item in self.nodes}
        edges_by_id = {item.edge_id: item for item in self.edges}
        channel_zone_ids = {item.channel_zone_id for item in self.channel_zones}
        spaces_by_id = {item.space_id: item for item in self.spaces}
        if len(spaces_by_id) != len(self.spaces):
            raise ValueError("facility space ids must be unique")
        for space in self.spaces:
            if space.parking_lot_id != self.parking_lot_id:
                raise ValueError(f"space {space.space_id} belongs to another parking lot")
            if space.floor_id not in floor_ids or space.zone_id not in zones_by_id:
                raise ValueError(f"space {space.space_id} references an unknown floor or zone")
            if zones_by_id[space.zone_id].floor_id != space.floor_id:
                raise ValueError(f"space {space.space_id} zone belongs to another floor")
            if space.access_node_id not in nodes_by_id:
                raise ValueError(f"space {space.space_id} references an unknown access node")
            if nodes_by_id[space.access_node_id].kind != "space_access":
                raise ValueError(f"space {space.space_id} must reference a space access node")
            if nodes_by_id[space.access_node_id].floor_id != space.floor_id:
                raise ValueError(f"space {space.space_id} access node belongs to another floor")
            if not rectangle_fits(space.geometry, floors_by_id[space.floor_id].bounds):
                raise ValueError(f"space {space.space_id} exceeds its floor bounds")
        buffers_by_id = {item.buffer_id: item for item in self.buffers}
        if len(buffers_by_id) != len(self.buffers):
            raise ValueError("facility buffer ids must be unique")
        if set(buffers_by_id) & set(spaces_by_id):
            raise ValueError("facility space and buffer ids must not overlap")
        for buffer in self.buffers:
            if buffer.parking_lot_id != self.parking_lot_id:
                raise ValueError(f"buffer {buffer.buffer_id} belongs to another parking lot")
            if len(set(buffer.stack_group_ids)) != len(buffer.stack_group_ids):
                raise ValueError(f"buffer {buffer.buffer_id} repeats a stack group")
            if buffer.floor_id not in floor_ids or buffer.zone_id not in zones_by_id:
                raise ValueError(f"buffer {buffer.buffer_id} references an unknown floor or zone")
            if zones_by_id[buffer.zone_id].floor_id != buffer.floor_id:
                raise ValueError(f"buffer {buffer.buffer_id} zone belongs to another floor")
            buffer_node = nodes_by_id.get(buffer.access_node_id)
            if buffer_node is None or buffer_node.kind != "buffer_access" or buffer_node.floor_id != buffer.floor_id:
                raise ValueError(f"buffer {buffer.buffer_id} has an invalid access node")
            if not rectangle_fits(buffer.geometry, floors_by_id[buffer.floor_id].bounds):
                raise ValueError(f"buffer {buffer.buffer_id} exceeds its floor bounds")
        groups_by_id = {item.stack_group_id: item for item in self.tandem_groups}
        if len(groups_by_id) != len(self.tandem_groups):
            raise ValueError("facility tandem group ids must be unique")
        grouped_space_ids: set[str] = set()
        for group in self.tandem_groups:
            if len(set(group.space_ids_near_to_deep)) != len(group.space_ids_near_to_deep):
                raise ValueError(f"tandem group {group.stack_group_id} repeats a space")
            if len(set(group.buffer_ids)) != len(group.buffer_ids):
                raise ValueError(f"tandem group {group.stack_group_id} repeats a buffer")
            if not set(group.space_ids_near_to_deep) <= set(spaces_by_id):
                raise ValueError(f"tandem group {group.stack_group_id} references an unknown space")
            if not set(group.buffer_ids) <= set(buffers_by_id):
                raise ValueError(f"tandem group {group.stack_group_id} references an unknown buffer")
            members = [spaces_by_id[item_id] for item_id in group.space_ids_near_to_deep]
            if any(item.stack_group_id != group.stack_group_id for item in members):
                raise ValueError(f"tandem group {group.stack_group_id} membership is inconsistent")
            if [item.depth for item in members] != list(range(1, len(members) + 1)):
                raise ValueError(f"tandem group {group.stack_group_id} depths must be contiguous")
            if grouped_space_ids & set(group.space_ids_near_to_deep):
                raise ValueError("a facility space cannot belong to multiple tandem groups")
            grouped_space_ids.update(group.space_ids_near_to_deep)
            for buffer_id in group.buffer_ids:
                if group.stack_group_id not in buffers_by_id[buffer_id].stack_group_ids:
                    raise ValueError(f"buffer {buffer_id} does not declare tandem group")
        declared_grouped = {item.space_id for item in self.spaces if item.stack_group_id is not None}
        if grouped_space_ids != declared_grouped:
            raise ValueError("facility tandem declarations do not cover grouped spaces exactly")
        for buffer in self.buffers:
            if not set(buffer.stack_group_ids) <= set(groups_by_id):
                raise ValueError(f"buffer {buffer.buffer_id} references an unknown tandem group")
            if any(buffer.buffer_id not in groups_by_id[group_id].buffer_ids for group_id in buffer.stack_group_ids):
                raise ValueError(f"buffer {buffer.buffer_id} tandem declarations are not reciprocal")
        connection_ids = unique(tuple(item.connection_id for item in self.inter_floor_connections), "inter-floor connection")
        if len(connection_ids) != len(self.inter_floor_connections):
            raise ValueError("inter-floor connection ids must be unique")
        inter_floor_edge_ids: set[str] = set()
        for connection in self.inter_floor_connections:
            if connection.from_floor_id not in floor_ids or connection.to_floor_id not in floor_ids:
                raise ValueError(f"connection {connection.connection_id} references an unknown floor")
            if connection.from_floor_id == connection.to_floor_id:
                raise ValueError(f"connection {connection.connection_id} must join different floors")
            if not set(connection.edge_ids) <= set(edges_by_id):
                raise ValueError(f"connection {connection.connection_id} references an unknown edge")
            for edge_id in connection.edge_ids:
                edge = edges_by_id[edge_id]
                if edge.traversal_kind != connection.kind:
                    raise ValueError(f"connection {connection.connection_id} traversal kind mismatch")
                edge_floor_pair = (nodes_by_id[edge.from_node_id].floor_id, nodes_by_id[edge.to_node_id].floor_id)
                declared_pair = (connection.from_floor_id, connection.to_floor_id)
                if edge.directed and edge_floor_pair != declared_pair:
                    raise ValueError(f"connection {connection.connection_id} direction mismatch")
                if not edge.directed and set(edge_floor_pair) != set(declared_pair):
                    raise ValueError(f"connection {connection.connection_id} floor mismatch")
            if inter_floor_edge_ids & set(connection.edge_ids):
                raise ValueError("an edge cannot belong to multiple inter-floor connections")
            inter_floor_edge_ids.update(connection.edge_ids)
        actual_inter_floor_edges = {edge.edge_id for edge in self.edges if nodes_by_id[edge.from_node_id].floor_id != nodes_by_id[edge.to_node_id].floor_id}
        if inter_floor_edge_ids != actual_inter_floor_edges:
            raise ValueError("inter-floor edge declarations must be complete and exact")
