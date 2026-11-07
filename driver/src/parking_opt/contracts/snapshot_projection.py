"""White-list projection from authoritative state to immutable ObservedSnapshot."""

from __future__ import annotations

from typing import Any

from parking_opt.contracts.canonical import snapshot_content_sha256
from parking_opt.domain.conversion import (
    action_to_mapping,
    channel_resource_to_mapping,
    executor_resource_to_mapping,
    lock_to_mapping,
    pending_request_to_mapping,
    position_to_mapping,
    reservation_to_mapping,
    transaction_to_mapping,
    vehicle_to_mapping,
)
from parking_opt.domain.records import ObservedSnapshot
from parking_opt.domain.state import AuthoritativeState


def observed_snapshot_to_mapping(snapshot: ObservedSnapshot) -> dict[str, Any]:
    """Serialize exactly the fields permitted by snapshot.schema.json."""

    return {
        "schema_version": snapshot.schema_version,
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_content_sha256": snapshot.snapshot_content_sha256,
        "run_id": snapshot.run_id,
        "scenario_id": snapshot.scenario_id,
        "layout_id": snapshot.layout_id,
        "decision_time_s": snapshot.decision_time_s,
        "vehicles": [vehicle_to_mapping(item) for item in snapshot.vehicles],
        "positions": [position_to_mapping(item) for item in snapshot.positions],
        "reservations": [reservation_to_mapping(item) for item in snapshot.reservations],
        "locks": [lock_to_mapping(item) for item in snapshot.locks],
        "actions": [action_to_mapping(item) for item in snapshot.actions],
        "transactions": [transaction_to_mapping(item) for item in snapshot.transactions],
        "executor_resource": executor_resource_to_mapping(snapshot.executor_resource),
        "channel_zone_resources": [
            channel_resource_to_mapping(item) for item in snapshot.channel_zone_resources
        ],
        "pending_requests": [
            pending_request_to_mapping(item) for item in snapshot.pending_requests
        ],
    }


def project_observed_snapshot(
    state: AuthoritativeState,
    *,
    snapshot_id: str,
    decision_time_s: int | None = None,
) -> ObservedSnapshot:
    """Project only approved visible fields; reject truth/simulator objects by type."""

    if type(state) is not AuthoritativeState:
        raise TypeError("snapshot projection accepts only an AuthoritativeState value")
    effective_time = state.sim_time_s if decision_time_s is None else decision_time_s
    if effective_time < state.sim_time_s:
        raise ValueError("decision_time_s cannot precede the reduced authoritative state")
    provisional = ObservedSnapshot(
        schema_version="1.0.0",
        snapshot_id=snapshot_id,
        snapshot_content_sha256="0" * 64,
        run_id=state.run_id,
        scenario_id=state.scenario_id,
        layout_id=state.layout_id,
        decision_time_s=effective_time,
        vehicles=state.vehicles,
        positions=state.positions,
        reservations=state.reservations,
        locks=state.locks,
        actions=state.actions,
        transactions=state.transactions,
        executor_resource=state.executor_resource,
        channel_zone_resources=state.channel_zone_resources,
        pending_requests=state.pending_requests,
    )
    content_hash = snapshot_content_sha256(observed_snapshot_to_mapping(provisional))
    return ObservedSnapshot(
        schema_version=provisional.schema_version,
        snapshot_id=provisional.snapshot_id,
        snapshot_content_sha256=content_hash,
        run_id=provisional.run_id,
        scenario_id=provisional.scenario_id,
        layout_id=provisional.layout_id,
        decision_time_s=provisional.decision_time_s,
        vehicles=provisional.vehicles,
        positions=provisional.positions,
        reservations=provisional.reservations,
        locks=provisional.locks,
        actions=provisional.actions,
        transactions=provisional.transactions,
        executor_resource=provisional.executor_resource,
        channel_zone_resources=provisional.channel_zone_resources,
        pending_requests=provisional.pending_requests,
    )
