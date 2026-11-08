"""Snapshot cross-record semantic guards that JSON Schema cannot express."""

from collections.abc import Mapping
from typing import Any

from parking_opt.contracts.canonical import snapshot_content_sha256
from parking_opt.contracts.semantic_validation import (
    _issue,
    _unique_ids,
    _validate_departure_information,
    assert_no_forbidden_fields,
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
