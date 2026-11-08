"""Decision audit and metric summary views for the presentation facade."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from statistics import fmean
from typing import Any, cast

from parking_opt.application.presentation.models import (
    DecisionActionView,
    DecisionAuditView,
    MetricSummaryView,
    MetricValueView,
    RequestMetricSummaryView,
    ValidatedDemoBundle,
)


def decision_audit(bundle: ValidatedDemoBundle, decision_id: str) -> DecisionAuditView:
    try:
        decision = next(item for item in bundle._decisions if item["decision_id"] == decision_id)
    except StopIteration as exc:
        raise KeyError(f"unknown decision_id: {decision_id}") from exc
    fallback = cast(Mapping[str, Any] | None, decision["fallback_record"])
    generation = cast(Mapping[str, Any] | None, decision["candidate_generation"])
    timing = cast(Mapping[str, Any], decision["timing"])
    target_request_id = cast(str, decision["target_request_id"])
    trigger = next(
        (
            event
            for event in bundle._events
            if cast(Mapping[str, Any], event.get("payload") or {}).get("pending_request", {}).get("request_id") == target_request_id
        ),
        None,
    )
    solver_status = cast(str, decision["solver_status"])
    if solver_status == "TIME_LIMIT_FEASIBLE":
        incumbent_status = "SAVED_VALIDATED_INCUMBENT"
    elif solver_status == "OPTIMAL":
        incumbent_status = "NOT_APPLICABLE_OPTIMAL"
    elif solver_status == "TIME_LIMIT_NO_FEASIBLE":
        incumbent_status = "NO_FEASIBLE_INCUMBENT"
    else:
        incumbent_status = "NOT_REPORTED_BY_SAVED_RESULT"
    generation_counts = (
        ()
        if generation is None
        else tuple(
            (key, int(generation[key]))
            for key in (
                "requests_seen",
                "requests_kept",
                "positions_seen",
                "positions_kept",
                "buffer_matchings_seen",
                "buffer_matchings_kept",
                "action_plans_kept",
            )
        )
    )
    return DecisionAuditView(
        decision_id=cast(str, decision["decision_id"]),
        request_id=cast(str, decision["request_id"]),
        algorithm_id=cast(str, decision["algorithm_id"]),
        algorithm_version=cast(str, decision["algorithm_version"]),
        target_request_id=target_request_id,
        target_anonymous_vehicle_id=cast(str, decision["target_anonymous_vehicle_id"]),
        primary_decision=cast(str, decision["primary_decision"]),
        solver_status=solver_status,
        validation_status=cast(str, decision["validation_status"]),
        config_sha256=cast(str, decision["config_sha256"]),
        layout_sha256=cast(str, decision["layout_sha256"]),
        visible_snapshot_sha256=cast(str, decision["visible_snapshot_sha256"]),
        input_model_sha256=cast(str | None, decision["input_model_sha256"]),
        trigger_event_id=None if trigger is None else cast(str, trigger["event_id"]),
        trigger_event_type=None if trigger is None else cast(str, trigger["event_type"]),
        trigger_sim_time_s=None if trigger is None else int(trigger["sim_time_s"]),
        snapshot_content_status="HASH_ONLY_NOT_PERSISTED",
        explanation_codes=tuple(cast(Sequence[str], decision["explanation_codes"])),
        actions=tuple(
            DecisionActionView(
                action_id=item["action_id"],
                action_type=item["action_type"],
                anonymous_vehicle_id=item["anonymous_vehicle_id"],
                origin_position_id=item["origin_position_id"],
                destination_position_id=item["destination_position_id"],
                destination_exit_id=item["destination_exit_id"],
                distance_m=float(item["distance_m"]),
                modeled_duration_s=item["modeled_duration_s"],
            )
            for item in cast(Sequence[Mapping[str, Any]], decision["recommended_actions"])
        ),
        used_fallback=fallback is not None,
        fallback_original_method=None if fallback is None else cast(str, fallback["original_method"]),
        fallback_original_solver_status=None if fallback is None else cast(str, fallback["original_solver_status"]),
        fallback_reason=None if fallback is None else cast(str, fallback["reason"]),
        fallback_strategy=None if fallback is None else cast(str, fallback["used_strategy"]),
        fallback_elapsed_s=None if fallback is None else float(fallback["elapsed_s"]),
        fallback_validation_status=None if fallback is None else cast(str, fallback["result_validation_status"]),
        incumbent_status=incumbent_status,
        end_to_end_s=float(timing["end_to_end_s"]),
        validation_and_modeling_s=float(timing["validation_and_modeling_s"]),
        solver_s=float(timing["solver_s"]),
        postsolve_validation_s=float(timing["postsolve_validation_s"]),
        minimum_logging_s=float(timing["minimum_logging_s"]),
        solver_time_limit_s=float(timing["solver_time_limit_s"]),
        candidate_generation=generation_counts,
        candidate_truncation_reasons=(
            () if generation is None else tuple(cast(Sequence[str], generation["truncation_reasons"]))
        ),
    )


def metric_summary(bundle: ValidatedDemoBundle, run_id: str) -> MetricSummaryView:
    if run_id != bundle.run_id:
        raise KeyError(f"unknown run_id: {run_id}")
    aggregates: list[MetricValueView] = []
    request_records: list[Mapping[str, Any]] = []
    request_groups: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    not_applicable = 0
    for metric in bundle._metrics:
        if metric["value"] is None:
            not_applicable += 1
        if metric["record_level"] in {"instantaneous", "run_aggregate"}:
            dimensions = cast(Mapping[str, str | int], metric["dimensions"])
            aggregates.append(
                MetricValueView(
                    metric_name=cast(str, metric["metric_name"]),
                    value=cast(float | None, metric["value"]),
                    unit=cast(str, metric["unit"]),
                    numerator=cast(float | None, metric["numerator"]),
                    denominator=cast(float | None, metric["denominator"]),
                    not_applicable_reason=cast(str | None, metric["not_applicable_reason"]),
                    dimensions=tuple(sorted(dimensions.items())),
                    record_level=cast(str, metric["record_level"]),
                    window_start_s=int(metric["window_start_s"]),
                    window_end_s=int(metric["window_end_s"]),
                    measured_at_s=cast(int | None, metric["measured_at_s"]),
                )
            )
        elif metric["record_level"] == "request_observation":
            request_records.append(metric)
            request_groups[cast(str, metric["metric_name"])].append(metric)
    aggregates.sort(key=lambda item: item.metric_name)
    request_summaries: list[RequestMetricSummaryView] = []
    for metric_name, records in sorted(request_groups.items()):
        completed_values = [
            float(item["value"]) for item in records if item["event_observed"] is True and item["value"] is not None
        ]
        request_summaries.append(
            RequestMetricSummaryView(
                metric_name=metric_name,
                unit=cast(str, records[0]["unit"]),
                observation_count=len(records),
                completed_count=len(completed_values),
                censored_count=sum(item["event_observed"] is False for item in records),
                pending_count=sum(item["pending_at_horizon"] is True for item in records),
                completed_only_mean=None if not completed_values else float(fmean(completed_values)),
                observed_lower_bound_count=sum(item["observed_wait_lower_bound_s"] is not None for item in records),
            )
        )
    window_start_s = int(bundle._metrics[0]["window_start_s"]) if bundle._metrics else 0
    window_end_s = int(bundle._metrics[0]["window_end_s"]) if bundle._metrics else 0
    return MetricSummaryView(
        run_id=bundle.run_id,
        scenario_id=bundle.scenario_id,
        algorithm_id=bundle.algorithm_id,
        algorithm_version=bundle.algorithm_version,
        window_start_s=window_start_s,
        window_end_s=window_end_s,
        aggregates=tuple(aggregates),
        request_summaries=tuple(request_summaries),
        request_observation_count=len(request_records),
        censored_request_count=sum(item["pending_at_horizon"] is True for item in request_records),
        pending_at_horizon_count=sum(item["pending_at_horizon"] is True for item in request_records),
        unobserved_request_count=sum(item["event_observed"] is False for item in request_records),
        not_applicable_metric_count=not_applicable,
    )
