"""Build metrics, manifest, and the run artifact index."""

from __future__ import annotations

from typing import Any

from parking_opt.contracts import canonical_sha256
from parking_opt.evaluation.metrics import MetricContext, compute_metrics, write_metric_jsonl
from parking_opt.experiments.runner import ALGORITHM_VERSION, _write_jsonl, _write_object, sha256_file
from parking_opt.experiments.runner_diagnostics import _decision_diagnostics, _failure_records
from parking_opt.logging.run_metadata import build_run_manifest, write_run_manifest


def build_index(ctx: dict[str, Any], result) -> dict[str, Any]:
    """Compute metrics and assemble the validated completed-run index."""

    artifact_root = ctx["artifact_root"]
    scenario = ctx["scenario"]
    unit = ctx["unit"]
    algorithm_id = ctx["algorithm_id"]
    decisions = result.decisions
    _write_jsonl(artifact_root / "decisions.jsonl", decisions)
    context = MetricContext(
        run_id=ctx["run_id"],
        scenario_id=scenario["scenario_id"],
        algorithm_id=algorithm_id,
        algorithm_version=ALGORITHM_VERSION,
        window_start_s=0,
        window_end_s=int(scenario["arrival_window_end_s"]),
        drain_deadline_s=int(scenario["drain_deadline_s"]),
        load_level=unit.load_level,
        layout_class=unit.layout_class,
        buffer_count=unit.buffer_count,
        relocation_executor_capacity=unit.relocation_executor_capacity,
        recoverability_policy=unit.recoverability_policy,
        facility_comparison_mode=unit.facility_comparison_mode,
        max_departure_wait_s=int(scenario["config"]["max_departure_wait_s"]),
    )
    metrics = compute_metrics(
        initial_state=result.initial_state,
        events=result.events,
        layout=ctx["layout"],
        context=context,
    )
    write_metric_jsonl(artifact_root / "metrics.jsonl", metrics, schema_catalog=ctx["catalog"])
    requests = tuple(item for item in metrics if item["record_level"] == "request_observation")
    _write_jsonl(artifact_root / "requests.jsonl", requests)
    failures = _failure_records(decisions, result.events)
    _write_jsonl(artifact_root / "failures.jsonl", failures)

    manifest = build_run_manifest(
        repo_root=ctx["repo_root"],
        run_id=ctx["run_id"],
        scenario_id=scenario["scenario_id"],
        algorithm_id=algorithm_id,
        algorithm_version=ALGORITHM_VERSION,
        config_sha256=ctx["config_sha256"],
        input_data_sha256=ctx["scenario_content_sha256"],
        random_seed=unit.seed,
        started_at=ctx["started_at"],
        ended_at=ctx["ended_at"],
        command=ctx["command"],
        run_status="COMPLETED",
    )
    write_run_manifest(artifact_root / "run-manifest.json", manifest, schema_catalog=ctx["catalog"])
    diagnostics = _decision_diagnostics(
        decisions,
        result.events,
        deadline_s=ctx["decision_deadline_s"],
    )
    artifact_names = (
        "layout.json",
        "scenario.json",
        "events.jsonl",
        "decisions.jsonl",
        "metrics.jsonl",
        "requests.jsonl",
        "failures.jsonl",
        "run-manifest.json",
    )
    index = {
        "schema_version": "1.0.0",
        "record_type": "c6_run_artifact_index",
        "run_status": "COMPLETED",
        "run_id": ctx["run_id"],
        "unit_id": unit.unit_id,
        "seed_partition": unit.partition.value,
        "experiment_slice": unit.experiment_slice,
        "departure_information_source": unit.departure_information_source,
        "facility_comparison_mode": unit.facility_comparison_mode,
        "user_cancellation_probability": unit.user_cancellation_probability,
        "soft_information_truncation_count": (
            ctx["generated"].soft_information_truncation_count
        ),
        "experiment_budget_s": unit.experiment_budget_s,
        "budget_role": (
            ctx["protocol"]["time"]["ten_second_role"]
            if unit.experiment_budget_s == 10.0
            else "online_sensitivity"
            if unit.experiment_budget_s is not None
            else None
        ),
        "algorithm_id": algorithm_id,
        "algorithm_version": ALGORITHM_VERSION,
        "random_seed": unit.seed,
        "protocol_sha256": ctx["protocol_hash"],
        "layout_sha256": canonical_sha256(ctx["layout_mapping"]),
        "scenario_sha256": ctx["generated"].scenario_content_sha256,
        "event_truth_sha256": ctx["generated"].event_truth_sha256,
        "arrival_count": ctx["generated"].arrival_count,
        "realized_offered_load_ratio": ctx["generated"].realized_offered_load_ratio,
        "event_count": len(result.events),
        "metric_record_count": len(metrics),
        "request_record_count": len(requests),
        "failure_record_count": len(failures),
        "pending_request_count_at_horizon": len(result.final_state.pending_requests),
        "state_invariant_violation_count": 0,
        "wall_clock_s": ctx["wall_clock_s"],
        "decision_diagnostics": diagnostics,
        "artifact_sha256": {name: sha256_file(artifact_root / name) for name in artifact_names},
        "resume_status": "EXECUTED",
    }
    if diagnostics["fallback_log_mismatch_count"] != 0:
        raise RuntimeError("fallback decisions and FALLBACK_USED events are not one-to-one")
    _write_object(artifact_root / "artifact-index.json", index)
    artifact_root.replace(ctx["run_root"])
    return index
