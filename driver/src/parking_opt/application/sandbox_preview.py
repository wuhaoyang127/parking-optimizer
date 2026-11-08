"""Sandbox decision-request building and candidate projection."""

from __future__ import annotations

from parking_opt.application.sandbox_layout import _sandbox_config
from parking_opt.application.sandbox_types import (
    _ALGORITHM_ID,
    _ALGORITHM_VERSION,
    CandidateExplanation,
)
from parking_opt.contracts.canonical import canonical_sha256
from parking_opt.contracts.snapshot_projection import project_observed_snapshot
from parking_opt.domain.records import DecisionRequest, PendingRequest
from parking_opt.domain.state import AuthoritativeState
from parking_opt.layout.model import Layout, layout_to_mapping
from parking_opt.strategies.online_rule import ArrivalCandidateAssessment


def _decision_request(
    state: AuthoritativeState,
    layout: Layout,
    *,
    trigger_event_type: str,
    target: PendingRequest,
) -> DecisionRequest:
    snapshot = project_observed_snapshot(
        state,
        snapshot_id=f"snapshot-{state.sequence_no}-{target.request_id}",
        decision_time_s=state.sim_time_s,
    )
    layout_mapping = layout_to_mapping(layout)
    config = _sandbox_config(layout)
    return DecisionRequest(
        request_id=f"decision-{target.request_id}",
        algorithm_id=_ALGORITHM_ID,
        algorithm_version=_ALGORITHM_VERSION,
        trigger_event_id=f"sandbox-event-{state.sequence_no}",
        trigger_event_type=trigger_event_type,
        trigger_request_id=target.request_id,
        trigger_anonymous_vehicle_id=target.anonymous_vehicle_id,
        decision_time_s=state.sim_time_s,
        layout=layout_mapping,
        approved_config=config,
        observed_snapshot=snapshot,
        config_sha256=canonical_sha256(config),
        layout_sha256=canonical_sha256(layout_mapping),
        visible_snapshot_sha256=snapshot.snapshot_content_sha256,
        decision_target_s=1.0,
        decision_deadline_s=3.0,
    )


def _candidate_projection(
    assessments: tuple[ArrivalCandidateAssessment, ...],
) -> tuple[CandidateExplanation, ...]:
    feasible = sorted((item for item in assessments if item.feasible), key=lambda item: item.score or ())
    rank_by_id = {item.position_id: rank for rank, item in enumerate(feasible, start=1)}
    return tuple(
        CandidateExplanation(
            rank=rank_by_id.get(item.position_id),
            position_id=item.position_id,
            stack_group_id=item.stack_group_id,
            depth=item.depth,
            feasible=item.feasible,
            reason_codes=item.reason_codes,
            distance_m=item.distance_m,
            incremental_unrecoverable_exposure=item.incremental_unrecoverable_exposure,
            incremental_blocked_vehicle_count=item.incremental_blocked_vehicle_count,
            remaining_one_step_assignable_capacity=item.remaining_one_step_assignable_capacity,
            departure_order_mismatch_count=item.departure_order_mismatch_count,
            score=item.score,
        )
        for item in sorted(
            assessments,
            key=lambda item: (0 if item.feasible else 1, item.score or (), item.position_id),
        )
    )
