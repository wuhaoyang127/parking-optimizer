from __future__ import annotations

from parking_opt.api.dynamic_costs import DynamicCostService
from parking_opt.api.models import ChannelLoadSnapshot
from parking_opt.api.routing import RouteCostService, RouteNotFoundError
from parking_opt.api.scenarios import built_in_scenarios


def _load(*, active: int) -> ChannelLoadSnapshot:
    bundle = built_in_scenarios()["school-demo"]
    return ChannelLoadSnapshot(
        parking_lot_id=bundle.layout.parking_lot_id,
        layout_version=bundle.layout.layout_version,
        observed_at=bundle.cost_snapshot.observed_at,
        active_units_by_zone={
            zone.channel_zone_id: active for zone in bundle.layout.channel_zones
        },
    )


def test_dynamic_cost_snapshot_is_complete_deterministic_and_hand_checkable() -> None:
    bundle = built_in_scenarios()["school-demo"]
    service = DynamicCostService()
    zero = service.build(bundle.layout, _load(active=0))
    repeated = service.build(bundle.layout, _load(active=0))
    assert repeated == zero
    assert set(zero.edge_travel_time_s) == {edge.edge_id for edge in bundle.layout.edges}
    assert zero.unavailable_edge_ids == ()
    for edge in bundle.layout.edges:
        assert zero.edge_travel_time_s[edge.edge_id] == edge.base_travel_time_s


def test_full_channel_capacity_marks_affected_edges_unavailable() -> None:
    bundle = built_in_scenarios()["school-demo"]
    load = ChannelLoadSnapshot(
        parking_lot_id=bundle.layout.parking_lot_id,
        layout_version=bundle.layout.layout_version,
        observed_at=bundle.cost_snapshot.observed_at,
        active_units_by_zone={
            zone.channel_zone_id: zone.capacity for zone in bundle.layout.channel_zones
        },
    )
    costs = DynamicCostService().build(bundle.layout, load)
    expected_closed = {
        edge.edge_id for edge in bundle.layout.edges if edge.channel_zone_ids
    }
    assert set(costs.unavailable_edge_ids) == expected_closed
    target = bundle.layout.spaces[0].access_node_id
    try:
        RouteCostService().route(
            bundle.layout,
            costs,
            from_node_id=bundle.layout.entrance_node_ids[0],
            to_node_id=target,
        )
    except RouteNotFoundError:
        pass
    else:
        assert not expected_closed, "fully loaded school channels should cut the test route"


def test_channel_load_must_cover_every_zone_exactly() -> None:
    bundle = built_in_scenarios()["school-demo"]
    incomplete = _load(active=0).model_copy(update={"active_units_by_zone": {}})
    try:
        DynamicCostService().build(bundle.layout, incomplete)
    except ValueError as exc:
        assert "domain mismatch" in str(exc)
    else:
        raise AssertionError("incomplete channel load must fail closed")
