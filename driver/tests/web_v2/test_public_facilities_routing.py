from __future__ import annotations

from collections import deque
from pathlib import Path

import pytest

from parking_opt.api.facility_scenarios import build_public_facility_scenarios
from parking_opt.api.models import ParkingFacilityLayout, ParkingFacilityStateSnapshot, ScenarioBundle
from parking_opt.api.routing import RouteCostService, RouteNotFoundError

REPO_ROOT = Path(__file__).resolve().parents[2]


def _reachable(layout, start: str) -> set[str]:  # type: ignore[no-untyped-def]
    adjacent: dict[str, list[str]] = {item.node_id: [] for item in layout.nodes}
    for edge in layout.edges:
        adjacent[edge.from_node_id].append(edge.to_node_id)
        if not edge.directed:
            adjacent[edge.to_node_id].append(edge.from_node_id)
    found, queue = {start}, deque([start])
    while queue:
        for target in adjacent[queue.popleft()]:
            if target not in found:
                found.add(target)
                queue.append(target)
    return found


def test_exported_public_resources_round_trip_to_authoritative_models() -> None:
    output = REPO_ROOT / "data" / "synthetic" / "web-v2-public"
    for scenario in build_public_facility_scenarios().values():
        stem = scenario.base_state.scenario_id
        assert (
            ParkingFacilityLayout.model_validate_json(
                (output / f"{stem}.facility-layout.json").read_text(encoding="utf-8")
            )
            == scenario.layout
        )
        assert (
            ParkingFacilityStateSnapshot.model_validate_json(
                (output / f"{stem}.facility-state.json").read_text(encoding="utf-8")
            )
            == scenario.base_state
        )
        assert (
            ScenarioBundle.model_validate_json(
                (output / f"{stem}.scenario.json").read_text(encoding="utf-8")
            )
            == scenario.bundle
        )


def test_every_entrance_reaches_every_space_buffer_and_an_exit() -> None:
    for scenario in build_public_facility_scenarios().values():
        targets = {item.access_node_id for item in scenario.layout.spaces} | {
            item.access_node_id for item in scenario.layout.buffers
        }
        exit_nodes = {item.node_id for item in scenario.layout.exits}
        for entrance in scenario.layout.entrances:
            reached = _reachable(scenario.layout, entrance.node_id)
            assert targets <= reached
            assert reached & exit_nodes
        for target in targets:
            assert _reachable(scenario.layout, target) & exit_nodes


def test_directed_entry_and_exit_edges_cannot_be_traversed_backwards() -> None:
    scenario = build_public_facility_scenarios()["lot-commercial"]
    with pytest.raises(RouteNotFoundError):
        RouteCostService().route(
            scenario.bundle.layout,
            scenario.bundle.cost_snapshot,
            from_node_id="junction-nw",
            to_node_id="entrance-west",
        )
    with pytest.raises(RouteNotFoundError):
        RouteCostService().route(
            scenario.bundle.layout,
            scenario.bundle.cost_snapshot,
            from_node_id="exit-west",
            to_node_id="junction-sw",
        )
