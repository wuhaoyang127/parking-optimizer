from __future__ import annotations
from itertools import pairwise
from typing import Literal
from pydantic import AwareDatetime, model_validator
from parking_opt.api.models import ContractModel, Identifier, SpaceStatus
from parking_opt.api.models_facility_layout import ParkingFacilityLayout
from parking_opt.api.models_state import ParkingFacilityStateSnapshot, Route, RoutePreviewRequest
class RoutePreview(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    parking_lot_id: Identifier
    layout_version: Identifier
    scenario_version: Identifier
    state_version: Identifier
    observed_at: AwareDatetime
    entrance_id: Identifier
    target_space_id: Identifier
    route: Route
    @model_validator(mode="after")
    def verify_route_identity(self) -> RoutePreview:
        if self.route.parking_lot_id != self.parking_lot_id:
            raise ValueError("route preview belongs to another parking lot")
        if self.route.layout_version != self.layout_version:
            raise ValueError("route preview layout version mismatch")
        return self
    def require_context(
        self,
        *,
        request: RoutePreviewRequest,
        layout: ParkingFacilityLayout,
        state: ParkingFacilityStateSnapshot,
    ) -> RoutePreview:
        state.require_layout(layout)
        if self.parking_lot_id != layout.parking_lot_id or self.layout_version != layout.layout_version:
            raise ValueError("route preview layout identity mismatch")
        if (self.layout_version != request.layout_version or self.scenario_version != request.scenario_version or self.state_version != request.state_version or self.entrance_id != request.entrance_id or self.target_space_id != request.target_space_id):
            raise ValueError("route preview request identity mismatch")
        if (state.scenario_version != self.scenario_version or state.state_version != self.state_version or state.observed_at != self.observed_at):
            raise ValueError("route preview state version mismatch")
        entrance_by_id = {item.entrance_id: item for item in layout.entrances}
        target_by_id = {item.space_id: item for item in layout.spaces}
        if self.entrance_id not in entrance_by_id or self.target_space_id not in target_by_id:
            raise ValueError("route preview references an unknown entrance or target")
        if self.route.from_node_id != entrance_by_id[self.entrance_id].node_id:
            raise ValueError("route preview starts at another entrance")
        if self.route.to_node_id != target_by_id[self.target_space_id].access_node_id:
            raise ValueError("route preview ends at another target access node")
        if self.route.node_ids[0] != self.route.from_node_id or self.route.node_ids[-1] != self.route.to_node_id:
            raise ValueError("route preview node sequence endpoints do not match route identity")
        nodes_by_id = {item.node_id: item for item in layout.nodes}
        edges_by_id = {item.edge_id: item for item in layout.edges}
        if not set(self.route.node_ids) <= set(nodes_by_id):
            raise ValueError("route preview references an unknown node")
        if not set(self.route.edge_ids) <= set(edges_by_id):
            raise ValueError("route preview references an unknown edge")
        if len(self.route.node_ids) != len(self.route.edge_ids) + 1:
            raise ValueError("route preview node and edge sequence lengths differ")
        for (from_node_id, to_node_id), edge_id in zip(pairwise(self.route.node_ids), self.route.edge_ids, strict=True):
            edge = edges_by_id[edge_id]
            follows_forward = edge.from_node_id == from_node_id and edge.to_node_id == to_node_id
            follows_reverse = not edge.directed and edge.to_node_id == from_node_id and edge.from_node_id == to_node_id
            if not follows_forward and not follows_reverse:
                raise ValueError("route preview edge sequence is not traversable")
        if tuple(item.edge_id for item in self.route.instructions) != self.route.edge_ids:
            raise ValueError("route preview instructions must cover route edges in order")
        if tuple(item.sequence for item in self.route.instructions) != tuple(range(1, len(self.route.instructions) + 1)):
            raise ValueError("route preview instruction sequence must be contiguous")
        target_state = next(item for item in state.spaces if item.space_id == self.target_space_id)
        if not target_state.assignable or target_state.effective_status is not SpaceStatus.AVAILABLE:
            raise ValueError("route preview target is no longer assignable")
        return self
