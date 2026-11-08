"""Layout cross-record semantic guards that JSON Schema cannot express."""

from collections.abc import Mapping
from typing import Any

from parking_opt.contracts.semantic_validation import _issue, _unique_ids


def validate_layout_semantics(layout: Mapping[str, Any]) -> None:
    """Validate v1 references, set separation, and tandem depth continuity."""

    nodes = _unique_ids(layout["road_nodes"], "road_node_id", "/road_nodes")
    edges = _unique_ids(layout["road_edges"], "road_edge_id", "/road_edges")
    zones = _unique_ids(layout["channel_zones"], "channel_zone_id", "/channel_zones")
    slots = layout["slots"]
    buffers = layout["buffer_slots"]
    normal_ids = _unique_ids(slots, "position_id", "/slots")
    buffer_ids = _unique_ids(buffers, "position_id", "/buffer_slots")
    if normal_ids & buffer_ids:
        raise _issue(
            "C1_POSITION_SET_DISJOINT",
            "/buffer_slots",
            "normal and buffer position IDs must be disjoint",
            sorted(normal_ids & buffer_ids),
        )

    for collection_name, records in (("slots", slots), ("buffer_slots", buffers)):
        for index, record in enumerate(records):
            if record["access_node_id"] not in nodes:
                raise _issue(
                    "C1_LAYOUT_REFERENCE",
                    f"/{collection_name}/{index}/access_node_id",
                    "position access node does not exist",
                    record["access_node_id"],
                )
            unknown_zones = set(record["channel_zone_ids"]) - zones
            if unknown_zones:
                raise _issue(
                    "C1_LAYOUT_REFERENCE",
                    f"/{collection_name}/{index}/channel_zone_ids",
                    "position references unknown channel zones",
                    sorted(unknown_zones),
                )

    depths_by_group: dict[str, list[int]] = {}
    for slot in slots:
        depths_by_group.setdefault(slot["stack_group_id"], []).append(slot["depth"])
    for group_id, depths in depths_by_group.items():
        expected = list(range(1, len(depths) + 1))
        if sorted(depths) != expected:
            raise _issue(
                "C1_CONTIGUOUS_DEPTH",
                "/slots",
                f"stack group {group_id} must have contiguous depths from 1",
                depths,
            )

    edges_by_id = {edge["road_edge_id"]: edge for edge in layout["road_edges"]}
    for index, edge in enumerate(layout["road_edges"]):
        if edge["from_node_id"] not in nodes or edge["to_node_id"] not in nodes:
            raise _issue(
                "C1_LAYOUT_REFERENCE",
                f"/road_edges/{index}",
                "road edge endpoint does not exist",
            )
        if set(edge["channel_zone_ids"]) - zones:
            raise _issue(
                "C1_LAYOUT_REFERENCE",
                f"/road_edges/{index}/channel_zone_ids",
                "road edge references unknown channel zones",
            )

    _unique_ids(layout["path_costs"], "path_cost_id", "/path_costs")
    path_pairs = [(item["from_node_id"], item["to_node_id"]) for item in layout["path_costs"]]
    if len(path_pairs) != len(set(path_pairs)):
        raise _issue(
            "C2_PATH_PAIR_UNIQUENESS",
            "/path_costs",
            "each directed node pair may have at most one materialized path cost",
        )
    for index, path_cost in enumerate(layout["path_costs"]):
        if path_cost["from_node_id"] not in nodes or path_cost["to_node_id"] not in nodes:
            raise _issue(
                "C1_LAYOUT_REFERENCE",
                f"/path_costs/{index}",
                "path endpoint does not exist",
            )
        unknown_edges = set(path_cost["road_edge_ids"]) - edges
        if unknown_edges:
            raise _issue(
                "C1_LAYOUT_REFERENCE",
                f"/path_costs/{index}/road_edge_ids",
                "path references unknown road edges",
                sorted(unknown_edges),
            )
        if set(path_cost["channel_zone_ids"]) - zones:
            raise _issue(
                "C1_LAYOUT_REFERENCE",
                f"/path_costs/{index}/channel_zone_ids",
                "path references unknown channel zones",
            )
        current_node_id = path_cost["from_node_id"]
        for edge_offset, edge_id in enumerate(path_cost["road_edge_ids"]):
            edge = edges_by_id[edge_id]
            if edge["from_node_id"] == current_node_id:
                current_node_id = edge["to_node_id"]
            elif not edge["directed"] and edge["to_node_id"] == current_node_id:
                current_node_id = edge["from_node_id"]
            else:
                raise _issue(
                    "C1_PATH_CONTINUITY",
                    f"/path_costs/{index}/road_edge_ids/{edge_offset}",
                    "path edge is not traversable from the preceding node",
                    edge_id,
                )
        if current_node_id != path_cost["to_node_id"]:
            raise _issue(
                "C1_PATH_CONTINUITY",
                f"/path_costs/{index}/to_node_id",
                "path does not end at the declared node",
                current_node_id,
            )
        selected_edges = [edges_by_id[item] for item in path_cost["road_edge_ids"]]
        distance_m = sum(float(item["distance_m"]) for item in selected_edges)
        travel_time_s = sum(item["travel_time_s"] for item in selected_edges)
        if abs(float(path_cost["distance_m"]) - distance_m) > 1e-9:
            raise _issue(
                "C2_PATH_AGGREGATE",
                f"/path_costs/{index}/distance_m",
                "path distance does not equal its edge sum",
            )
        if path_cost["travel_time_s"] != travel_time_s:
            raise _issue(
                "C2_PATH_AGGREGATE",
                f"/path_costs/{index}/travel_time_s",
                "path travel time does not equal its edge sum",
            )
        expected_zones: list[str] = []
        for edge in selected_edges:
            for zone_id in edge["channel_zone_ids"]:
                if zone_id not in expected_zones:
                    expected_zones.append(zone_id)
        if path_cost["channel_zone_ids"] != expected_zones:
            raise _issue(
                "C2_PATH_AGGREGATE",
                f"/path_costs/{index}/channel_zone_ids",
                "path channel zones do not equal the stable edge union",
            )
