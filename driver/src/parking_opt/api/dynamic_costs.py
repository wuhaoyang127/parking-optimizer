"""Deterministic complete cost snapshots derived from currently observed channel load."""

from __future__ import annotations

import hashlib
import json

from parking_opt.api.models import ChannelLoadSnapshot, CostSnapshot, Layout


class DynamicCostService:
    """Convert visible channel occupancy into one complete, versioned edge-cost view."""

    def build(self, layout: Layout, load: ChannelLoadSnapshot) -> CostSnapshot:
        if load.parking_lot_id != layout.parking_lot_id:
            raise ValueError("channel load and layout parking_lot_id mismatch")
        if load.layout_version != layout.layout_version:
            raise ValueError("channel load and layout_version mismatch")
        capacities = {item.channel_zone_id: item.capacity for item in layout.channel_zones}
        if set(load.active_units_by_zone) != set(capacities):
            missing = sorted(set(capacities) - set(load.active_units_by_zone))
            unknown = sorted(set(load.active_units_by_zone) - set(capacities))
            raise ValueError(
                f"channel load domain mismatch; missing={missing}, unknown={unknown}"
            )
        edge_costs: dict[str, float] = {}
        unavailable: list[str] = []
        for edge in layout.edges:
            ratios = [
                load.active_units_by_zone[zone_id] / capacities[zone_id]
                for zone_id in edge.channel_zone_ids
            ]
            peak_ratio = max(ratios, default=0.0)
            edge_costs[edge.edge_id] = edge.base_travel_time_s * (1.0 + peak_ratio)
            if any(
                load.active_units_by_zone[zone_id] >= capacities[zone_id]
                for zone_id in edge.channel_zone_ids
            ):
                unavailable.append(edge.edge_id)
        canonical = {
            "parking_lot_id": load.parking_lot_id,
            "layout_version": load.layout_version,
            "observed_at": load.observed_at.isoformat(),
            "active_units_by_zone": dict(sorted(load.active_units_by_zone.items())),
        }
        digest = hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:16]
        return CostSnapshot(
            parking_lot_id=layout.parking_lot_id,
            layout_version=layout.layout_version,
            cost_version=f"cost-dynamic-{digest}",
            observed_at=load.observed_at,
            edge_travel_time_s=edge_costs,
            unavailable_edge_ids=tuple(sorted(unavailable)),
        )
