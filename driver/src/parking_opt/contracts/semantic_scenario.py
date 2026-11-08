"""Scenario and decision-request semantic guards."""

from collections.abc import Mapping
from typing import Any

from parking_opt.contracts.canonical import canonical_sha256, snapshot_content_sha256
from parking_opt.contracts.semantic_layout import validate_layout_semantics
from parking_opt.contracts.semantic_snapshot import validate_snapshot_semantics
from parking_opt.contracts.semantic_validation import (
    _issue,
    _unique_ids,
    assert_no_forbidden_fields,
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
