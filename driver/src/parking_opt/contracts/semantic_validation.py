"""Cross-record semantic guards that JSON Schema cannot express."""

from collections.abc import Mapping, Sequence
from typing import Any

from parking_opt.contracts.canonical import canonical_sha256, snapshot_content_sha256
from parking_opt.contracts.errors import ContractValidationError, ValidationIssue

FORBIDDEN_FIELD_NAMES = frozenset(
    {
        "actual_arrival_time_s",
        "actual_departure_time_s",
        "event_queue",
        "future_events",
        "license_plate",
        "oracle_result",
        "plate_number",
        "simpy_env",
        "truth_events",
        "truth_store",
    }
)


def _issue(
    constraint_id: str,
    pointer: str,
    message: str,
    observed_value: object | None = None,
) -> ContractValidationError:
    return ContractValidationError(
        (
            ValidationIssue(
                error_code="SEMANTIC_VALIDATION_FAILED",
                json_pointer=pointer,
                constraint_id=constraint_id,
                message=message,
                observed_value=observed_value,
            ),
        )
    )


def _unique_ids(records: Sequence[Mapping[str, Any]], field: str, pointer: str) -> set[str]:
    values = [record[field] for record in records]
    if len(values) != len(set(values)):
        raise _issue("C1_ID_UNIQUENESS", pointer, f"{field} values must be unique", values)
    return set(values)


def assert_no_forbidden_fields(value: object, pointer: str = "") -> None:
    """Reject truth, simulator, oracle, and direct-identifier fields recursively."""

    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            child_pointer = f"{pointer}/{key_text}"
            if key_text.casefold() in FORBIDDEN_FIELD_NAMES:
                raise _issue(
                    "C1_FORBIDDEN_INFORMATION_FIELD",
                    child_pointer,
                    "field is forbidden at the policy contract boundary",
                    key_text,
                )
            assert_no_forbidden_fields(child, child_pointer)
    elif isinstance(value, list | tuple):
        for index, child in enumerate(value):
            assert_no_forbidden_fields(child, f"{pointer}/{index}")


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


def validate_scenario_semantics(
    scenario: Mapping[str, Any],
    layout: Mapping[str, Any],
) -> None:
    """Validate frozen scenario references, timing, buffers, and synthetic lineage."""

    if scenario["layout_id"] != layout["layout_id"]:
        raise _issue(
            "C2_SCENARIO_LAYOUT",
            "/layout_id",
            "scenario layout_id must match the supplied layout",
        )
    if scenario["drain_deadline_s"] < scenario["arrival_window_end_s"]:
        raise _issue(
            "C2_SCENARIO_HORIZON",
            "/drain_deadline_s",
            "drain deadline cannot precede the arrival-window end",
        )
    config = scenario["config"]
    if config["buffer_count"] != len(config["active_buffer_position_ids"]):
        raise _issue(
            "C2_SCENARIO_BUFFERS",
            "/config/buffer_count",
            "buffer_count must equal the active buffer ID count",
        )
    layout_buffers = {item["position_id"] for item in layout["buffer_slots"]}
    if not set(config["active_buffer_position_ids"]) <= layout_buffers:
        raise _issue(
            "C2_SCENARIO_BUFFERS",
            "/config/active_buffer_position_ids",
            "active buffers must be a subset of layout buffers",
        )
    if scenario["data_source"] == "synthetic" and scenario["random_seed"] is None:
        raise _issue(
            "C2_SYNTHETIC_SEED",
            "/random_seed",
            "synthetic scenarios require a random seed",
        )
    requests = scenario["vehicle_requests"]
    request_ids = _unique_ids(requests, "request_id", "/vehicle_requests")
    vehicle_ids = _unique_ids(
        requests,
        "anonymous_vehicle_id",
        "/vehicle_requests",
    )
    if len(request_ids) != len(vehicle_ids):
        raise _issue(
            "C2_SCENARIO_VEHICLE_REQUEST",
            "/vehicle_requests",
            "each synthetic vehicle must have exactly one arrival request",
        )
    for index, request in enumerate(requests):
        if request["arrival_time_s"] >= scenario["arrival_window_end_s"]:
            raise _issue(
                "C2_SCENARIO_HORIZON",
                f"/vehicle_requests/{index}/arrival_time_s",
                "arrival must occur inside [0, arrival_window_end_s)",
            )
    _unique_ids(scenario["truth_events"], "truth_event_id", "/truth_events")
    for index, event in enumerate(scenario["truth_events"]):
        if event["anonymous_vehicle_id"] not in vehicle_ids:
            raise _issue(
                "C2_SCENARIO_REFERENCE",
                f"/truth_events/{index}/anonymous_vehicle_id",
                "truth event vehicle has no arrival request",
            )


def _validate_departure_information(
    information: Mapping[str, Any],
    decision_time_s: int,
    pointer: str,
) -> None:
    if information["known_at_time_s"] > decision_time_s:
        raise _issue(
            "C1_INFORMATION_VISIBILITY",
            f"{pointer}/known_at_time_s",
            "departure information is not yet visible",
            information["known_at_time_s"],
        )
    if information["source"] == "model_prediction":
        lineage = (
            information["training_data_cutoff_s"],
            information["feature_window_end_s"],
            information["generated_at_time_s"],
            information["known_at_time_s"],
        )
        if any(value is None for value in lineage) or tuple(lineage) != tuple(sorted(lineage)):
            raise _issue(
                "C1_PREDICTION_LINEAGE",
                pointer,
                "prediction lineage times must be non-null and monotonic",
                lineage,
            )


def validate_snapshot_semantics(snapshot: Mapping[str, Any]) -> None:
    """Validate cross-object IDs, visibility, ordering, and canonical content hash."""

    assert_no_forbidden_fields(snapshot)
    decision_time_s = snapshot["decision_time_s"]
    vehicle_ids = _unique_ids(snapshot["vehicles"], "anonymous_vehicle_id", "/vehicles")
    position_ids = _unique_ids(snapshot["positions"], "position_id", "/positions")
    reservation_ids = _unique_ids(snapshot["reservations"], "reservation_id", "/reservations")
    lock_ids = _unique_ids(snapshot["locks"], "lock_id", "/locks")
    action_ids = _unique_ids(snapshot["actions"], "action_id", "/actions")
    transaction_ids = _unique_ids(snapshot["transactions"], "transaction_id", "/transactions")
    if len(reservation_ids | lock_ids | action_ids | transaction_ids) != (
        len(reservation_ids) + len(lock_ids) + len(action_ids) + len(transaction_ids)
    ):
        raise _issue(
            "C1_CROSS_TYPE_RUNTIME_ID_UNIQUENESS",
            "/",
            "reservation, lock, action, and transaction IDs must not collide",
        )

    for index, vehicle in enumerate(snapshot["vehicles"]):
        _validate_departure_information(
            vehicle["departure_information"],
            decision_time_s,
            f"/vehicles/{index}/departure_information",
        )
        location = vehicle["location_state"]
        if location["kind"] == "AT_POSITION" and location["position_id"] not in position_ids:
            raise _issue(
                "C1_SNAPSHOT_REFERENCE",
                f"/vehicles/{index}/location_state/position_id",
                "vehicle position does not exist",
            )

    for index, position in enumerate(snapshot["positions"]):
        occupant = position["occupant_vehicle_id"]
        if occupant is not None and occupant not in vehicle_ids:
            raise _issue(
                "C1_SNAPSHOT_REFERENCE",
                f"/positions/{index}/occupant_vehicle_id",
                "position occupant does not exist",
            )
        if position["position_kind"] == "buffer" and position["assignable"]:
            raise _issue(
                "C1_BUFFER_NOT_ASSIGNABLE",
                f"/positions/{index}/assignable",
                "a dedicated buffer cannot accept a normal arrival",
            )

    occupancy_by_vehicle = {
        position["occupant_vehicle_id"]: position["position_id"]
        for position in snapshot["positions"]
        if position["occupant_vehicle_id"] is not None
    }
    if len(occupancy_by_vehicle) != sum(
        position["occupant_vehicle_id"] is not None for position in snapshot["positions"]
    ):
        raise _issue(
            "C2_VEHICLE_SINGLE_POSITION",
            "/positions",
            "a vehicle cannot physically occupy multiple positions",
        )
    for index, vehicle in enumerate(snapshot["vehicles"]):
        location = vehicle["location_state"]
        if location["kind"] == "AT_POSITION":
            if occupancy_by_vehicle.get(vehicle["anonymous_vehicle_id"]) != location["position_id"]:
                raise _issue(
                    "C2_OCCUPANCY_RECONCILIATION",
                    f"/vehicles/{index}/location_state",
                    "vehicle and position occupancy records disagree",
                )

    claim_owners: dict[str, set[str]] = {
        position["position_id"]: (
            {position["occupant_vehicle_id"]}
            if position["occupant_vehicle_id"] is not None
            else set()
        )
        for position in snapshot["positions"]
    }
    for index, reservation in enumerate(snapshot["reservations"]):
        if (
            reservation["position_id"] not in position_ids
            or reservation["owner_vehicle_id"] not in vehicle_ids
        ):
            raise _issue(
                "C2_RESERVATION_REFERENCE",
                f"/reservations/{index}",
                "reservation position or owner does not exist",
            )
        claim_owners[reservation["position_id"]].add(reservation["owner_vehicle_id"])
    if any(len(owners) > 1 for owners in claim_owners.values()):
        raise _issue(
            "C2_POSITION_CLAIM_CAPACITY",
            "/reservations",
            "a capacity-one position has conflicting claim owners",
        )

    expected_hash = snapshot_content_sha256(snapshot)
    if snapshot["snapshot_content_sha256"] != expected_hash:
        raise _issue(
            "C1_SNAPSHOT_HASH",
            "/snapshot_content_sha256",
            "snapshot content hash does not match canonical content",
            snapshot["snapshot_content_sha256"],
        )

    pending_order = [
        (request["event_sequence_no"], request["request_id"])
        for request in snapshot["pending_requests"]
    ]
    if pending_order != sorted(pending_order):
        raise _issue(
            "C1_PENDING_CANONICAL_ORDER",
            "/pending_requests",
            "pending requests must use canonical event-sequence and request-ID order",
            pending_order,
        )


def validate_decision_request_semantics(request: Mapping[str, Any]) -> None:
    """Validate hashes, trigger closure, and the policy information boundary."""

    assert_no_forbidden_fields(request)
    validate_layout_semantics(request["layout"])
    validate_snapshot_semantics(request["observed_snapshot"])
    if request["layout"]["layout_id"] != request["observed_snapshot"]["layout_id"]:
        raise _issue(
            "C1_DECISION_LAYOUT_MATCH",
            "/observed_snapshot/layout_id",
            "snapshot layout_id must match embedded layout",
        )
    expected_hashes = {
        "config_sha256": canonical_sha256(request["approved_config"]),
        "layout_sha256": canonical_sha256(request["layout"]),
        "visible_snapshot_sha256": snapshot_content_sha256(request["observed_snapshot"]),
    }
    for field, expected in expected_hashes.items():
        if request[field] != expected:
            raise _issue(
                "C1_DECISION_HASH",
                f"/{field}",
                f"{field} does not match canonical request content",
                request[field],
            )
    if (
        request["visible_snapshot_sha256"]
        != request["observed_snapshot"]["snapshot_content_sha256"]
    ):
        raise _issue(
            "C1_DECISION_HASH",
            "/visible_snapshot_sha256",
            "request and snapshot hashes must be identical",
        )
    config = request["approved_config"]
    if config["buffer_count"] != len(config["active_buffer_position_ids"]):
        raise _issue(
            "C1_BUFFER_CONFIGURATION",
            "/approved_config/buffer_count",
            "buffer_count must equal the active buffer ID count",
        )
    layout_buffers = {item["position_id"] for item in request["layout"]["buffer_slots"]}
    if not set(config["active_buffer_position_ids"]) <= layout_buffers:
        raise _issue(
            "C1_BUFFER_CONFIGURATION",
            "/approved_config/active_buffer_position_ids",
            "active buffers must be a subset of layout buffer positions",
        )

    if request["trigger_event_type"] in {"ARRIVAL_REQUESTED", "DEPARTURE_REQUESTED"}:
        target = [
            item
            for item in request["observed_snapshot"]["pending_requests"]
            if item["request_id"] == request["trigger_request_id"]
        ]
        if (
            len(target) != 1
            or target[0]["anonymous_vehicle_id"] != request["trigger_anonymous_vehicle_id"]
        ):
            raise _issue(
                "C1_TRIGGER_TARGET_MATCH",
                "/trigger_request_id",
                "trigger request and vehicle must identify one visible pending request",
            )
