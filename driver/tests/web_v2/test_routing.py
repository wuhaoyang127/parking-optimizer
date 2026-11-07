from __future__ import annotations

from math import cos, radians, sin

import pytest

from parking_opt.api.models import CostSnapshot, Layout
from parking_opt.api.routing import RouteCostService, RouteInputError
from parking_opt.api.scenarios import built_in_scenarios


def test_route_uses_current_visible_cost_snapshot() -> None:
    bundle = built_in_scenarios()["school-demo"]
    route = RouteCostService().route(
        bundle.layout,
        bundle.cost_snapshot,
        from_node_id="entry",
        to_node_id="access-b",
    )
    assert route.edge_ids == ("edge-entry-junction", "edge-junction-b")
    assert route.distance_m == 38
    assert route.dynamic_eta_s == 39
    assert route.cost_version == bundle.cost_snapshot.cost_version


def test_route_fails_closed_on_incomplete_cost_domain() -> None:
    bundle = built_in_scenarios()["school-demo"]
    values = dict(bundle.cost_snapshot.edge_travel_time_s)
    values.pop("edge-junction-b")
    incomplete = CostSnapshot(
        parking_lot_id=bundle.parking_lot.parking_lot_id,
        layout_version=bundle.layout.layout_version,
        cost_version="missing-edge",
        observed_at=bundle.cost_snapshot.observed_at,
        edge_travel_time_s=values,
    )
    with pytest.raises(RouteInputError, match="cost edge domain mismatch"):
        RouteCostService().route(
            bundle.layout,
            incomplete,
            from_node_id="entry",
            to_node_id="access-b",
        )


def _guidance_route(points: tuple[tuple[float, float], ...]) -> tuple[Layout, CostSnapshot]:
    bundle = built_in_scenarios()["school-demo"]
    payload = bundle.layout.model_dump(mode="json")
    ids = [f"node-{index}" for index in range(len(points))]
    payload.update(
        entrance_node_ids=[ids[0]],
        exit_node_ids=["exit"],
        nodes=[
            {
                "node_id": node_id,
                "coordinate": {"x_m": point[0], "y_m": point[1]},
                "kind": "entrance" if index == 0 else "space_access",
                "label": f"位置{index + 1}",
            }
            for index, (node_id, point) in enumerate(zip(ids, points, strict=True))
        ] + [{"node_id": "exit", "coordinate": {"x_m": 50, "y_m": 50},
              "kind": "exit", "label": "出口"}],
        edges=[
            {"edge_id": f"internal-edge-{index}", "from_node_id": ids[index],
             "to_node_id": ids[index + 1], "distance_m": 10, "base_travel_time_s": 2,
             "directed": False, "channel_zone_ids": []}
            for index in range(len(ids) - 1)
        ],
        channel_zones=[],
        spaces=[{
            "parking_lot_id": bundle.layout.parking_lot_id, "space_id": "TEST-01",
            "coordinate": {"x_m": points[-1][0], "y_m": points[-1][1]},
            "access_node_id": ids[-1], "status": "available", "charging": False,
            "stack_group_id": "independent-test", "depth": 1,
            "assignable": True, "assignability_reasons": [],
        }],
        tandem_groups=[], buffers=[],
    )
    layout = Layout.model_validate(payload)
    costs = bundle.cost_snapshot.model_copy(update={
        "edge_travel_time_s": {edge.edge_id: 2 for edge in layout.edges},
        "unavailable_edge_ids": (),
    })
    return layout, costs


@pytest.mark.parametrize(
    ("angle", "action"),
    [(0, "直行"), (30, "直行"), (30.01, "右转"), (90, "右转"),
     (-90, "左转"), (-30, "直行"), (-30.01, "左转"),
     (149.99, "右转"), (150, "按高亮路线调整方向"), (180, "按高亮路线调整方向")],
)
def test_guidance_uses_frozen_canvas_turn_boundaries(angle: float, action: str) -> None:
    layout, costs = _guidance_route((
        (0, 0), (10, 0), (10 + 10 * cos(radians(angle)), 10 * sin(radians(angle)))
    ))
    service = RouteCostService()
    service.register_entrance_headings(layout.parking_lot_id, layout.layout_version, {"node-0": 0})
    route = service.route(layout, costs, from_node_id="node-0", to_node_id="node-2")
    assert route.instructions[0].text.startswith("直行")
    assert route.instructions[1].text.startswith(action)
    assert "到达目标区域" in route.instructions[-1].text
    assert all("internal-edge" not in item.text and "node-" not in item.text
               for item in route.instructions)


def test_guidance_headings_change_only_text_and_are_version_scoped() -> None:
    layout, costs = _guidance_route(((0, 0), (10, 0), (10, 10)))
    service = RouteCostService()
    before = service.route(layout, costs, from_node_id="node-0", to_node_id="node-2")
    assert before.instructions[0].text.startswith("沿高亮通道前行")
    service.register_entrance_headings(layout.parking_lot_id, "foreign-version", {"node-0": 90})
    assert service.route(layout, costs, from_node_id="node-0", to_node_id="node-2") == before
    service.register_entrance_headings(layout.parking_lot_id, layout.layout_version, {"node-0": 90})
    after = service.route(layout, costs, from_node_id="node-0", to_node_id="node-2")
    assert after.instructions[0].text.startswith("左转")
    assert before.model_dump(exclude={"instructions"}) == after.model_dump(exclude={"instructions"})
    assert [item.model_dump(exclude={"text"}) for item in before.instructions] == [
        item.model_dump(exclude={"text"}) for item in after.instructions
    ]


def test_zero_vector_and_zero_edge_routes_do_not_invent_turns_or_steps() -> None:
    layout, costs = _guidance_route(((0, 0), (0, 0), (10, 0)))
    service = RouteCostService()
    service.register_entrance_headings(layout.parking_lot_id, layout.layout_version, {"node-0": 90})
    route = service.route(layout, costs, from_node_id="node-0", to_node_id="node-2")
    assert all(item.text.startswith("沿高亮通道前行") for item in route.instructions)
    stationary = service.route(layout, costs, from_node_id="node-0", to_node_id="node-0")
    assert stationary.instructions == ()
    assert stationary.edge_ids == ()
    assert stationary.distance_m == stationary.dynamic_eta_s == 0
