"""Regenerate paired statistics, static figures, and Markdown from saved artifacts."""
from __future__ import annotations
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from parking_opt.contracts.canonical import canonical_sha256
from parking_opt.experiments.reporting import BASELINE_ID, CANDIDATE_ID, _run_values, _sensitivity_group, _write_json, _write_jsonl
from parking_opt.experiments.reporting_collect import build_pairs, collect_completed_runs
from parking_opt.experiments.reporting_csv import _write_failures_csv, _write_metrics_csv
from parking_opt.experiments.reporting_render import _generate_figures, _render_report
from parking_opt.experiments.runner import sha256_file
from parking_opt.experiments.statistics import descriptive_summary, paired_bootstrap_summary
def generate_report(
    *,
    experiment_root: Path,
    protocol: dict[str, Any],
) -> dict[str, Any]:
    """Verify completed runs and regenerate every report artifact from disk."""
    report_root = experiment_root / "report"
    report_root.mkdir(parents=True, exist_ok=True)
    collected = collect_completed_runs(experiment_root)
    indexes = collected["indexes"]
    metrics_by_run = collected["metrics_by_run"]
    all_metrics = collected["all_metrics"]
    all_failures = collected["all_failures"]
    pairs = build_pairs(indexes, protocol)
    complete_pairs = pairs["complete_pairs"]
    rolling_only_units = pairs["rolling_only_units"]
    incomplete_units = pairs["incomplete_units"]
    observed_formal_ids = pairs["observed_formal_ids"]
    observed_extension_ids = pairs["observed_extension_ids"]
    if not complete_pairs and not rolling_only_units:
        raise ValueError("report requires a complete pair or rolling-only budget unit")
    metric_pairs: dict[str, tuple[list[float], list[float]]] = {}
    co_primary_pairs = (
        [pair for pair in complete_pairs if all(index["seed_partition"] == "formal_core" for index in pair)]
        if observed_extension_ids
        else complete_pairs
    )
    for baseline, candidate in co_primary_pairs:
        baseline_run_values = _run_values(metrics_by_run[str(baseline["run_id"])])
        candidate_run_values = _run_values(metrics_by_run[str(candidate["run_id"])])
        for metric_name in sorted(set(baseline_run_values) & set(candidate_run_values)):
            baseline_list, candidate_list = metric_pairs.setdefault(metric_name, ([], []))
            baseline_list.append(baseline_run_values[metric_name])
            candidate_list.append(candidate_run_values[metric_name])
    statistics_config = protocol["statistics"]
    paired_statistics: dict[str, Any] = {}
    for metric_name, (paired_baseline, paired_candidate) in metric_pairs.items():
        paired = paired_bootstrap_summary(
            paired_baseline,
            paired_candidate,
            resamples=int(statistics_config["bootstrap_resamples"]),
            confidence_level=float(statistics_config["confidence_level"]),
            seed=int(protocol["seed_sets"]["statistics"]),
        )
        paired_statistics[metric_name] = {
            "baseline_values": paired_baseline,
            "candidate_values": paired_candidate,
            "paired": paired.to_mapping(),
        }
    sensitivity_values: dict[
        str,
        dict[str, dict[str, list[float]]],
    ] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    if observed_extension_ids:
        for algorithms in indexes.values():
            for algorithm_id, index in algorithms.items():
                if index["seed_partition"] != "formal_extension":
                    continue
                group = _sensitivity_group(index)
                values = _run_values(metrics_by_run[str(index["run_id"])])
                for metric_name, value in values.items():
                    sensitivity_values[group][algorithm_id][metric_name].append(value)
    sensitivity_statistics: dict[str, Any] = {}
    for group, algorithm_values in sorted(sensitivity_values.items()):
        algorithm_summaries: dict[str, Any] = {}
        for algorithm_id, metric_values in sorted(algorithm_values.items()):
            algorithm_summaries[algorithm_id] = {
                metric_name: descriptive_summary(values).to_mapping()
                for metric_name, values in sorted(metric_values.items())
            }
        group_record: dict[str, Any] = {"algorithms": algorithm_summaries}
        if BASELINE_ID in algorithm_values and CANDIDATE_ID in algorithm_values:
            paired_metrics: dict[str, Any] = {}
            common_metrics = set(algorithm_values[BASELINE_ID]) & set(algorithm_values[CANDIDATE_ID])
            for metric_name in sorted(common_metrics):
                baseline_values = algorithm_values[BASELINE_ID][metric_name]
                candidate_values = algorithm_values[CANDIDATE_ID][metric_name]
                if len(baseline_values) != len(candidate_values):
                    raise ValueError(f"sensitivity group {group} is not paired for {metric_name}")
                paired_metrics[metric_name] = paired_bootstrap_summary(
                    baseline_values,
                    candidate_values,
                    resamples=int(statistics_config["bootstrap_resamples"]),
                    confidence_level=float(statistics_config["confidence_level"]),
                    seed=int(protocol["seed_sets"]["statistics"]),
                ).to_mapping()
            group_record["paired"] = paired_metrics
        sensitivity_statistics[group] = group_record
    invariant_violations = sum(
        int(index["state_invariant_violation_count"]) for pair in complete_pairs for index in pair
    )
    deadline_violations = sum(
        int(index["decision_diagnostics"]["hard_deadline_violation_count"])
        for pair in complete_pairs
        for index in pair
    )
    formal_pairs = [
        pair for pair in complete_pairs if all(index["seed_partition"] == "formal_core" for index in pair)
    ]
    formal_seed_count = len({int(index["random_seed"]) for pair in formal_pairs for index in pair})
    required_seed_count = len(protocol["seed_sets"]["formal_core"])
    required_formal_pair_count = len(protocol["seed_sets"]["formal_core"])
    research_gate = {
        "status": (
            "NOT_APPLICABLE_EXPLORATORY_SENSITIVITY"
            if observed_extension_ids and not observed_formal_ids
            else "NOT_ASSESSED_INCOMPLETE_CORE_MATRIX"
            if len(formal_pairs) < required_formal_pair_count
            else "READY_FOR_THRESHOLD_ASSESSMENT"
        ),
        "formal_pair_count": len(formal_pairs),
        "required_formal_pair_count": required_formal_pair_count,
        "formal_seed_count": formal_seed_count,
        "required_formal_seed_count": required_seed_count,
        "state_invariant_violation_count": invariant_violations,
        "hard_deadline_violation_count": deadline_violations,
        "thresholds_sha256": canonical_sha256(protocol["rolling_research_gate"]),
    }
    _write_jsonl(report_root / "metrics-long.jsonl", all_metrics)
    _write_metrics_csv(report_root / "metrics-long.csv", all_metrics)
    _write_failures_csv(report_root / "failures.csv", all_failures)
    _write_json(
        report_root / "paired-statistics.json",
        {
            "schema_version": "1.0.0",
            "record_type": "c6_paired_statistics",
            "pair_count": len(complete_pairs),
            "incomplete_units": incomplete_units,
            "statistics_config": statistics_config,
            "metrics": paired_statistics,
            "research_gate": research_gate,
        },
    )
    if observed_extension_ids:
        _write_json(
            report_root / "sensitivity-statistics.json",
            {
                "schema_version": "1.0.0",
                "record_type": "c7_exploratory_sensitivity_statistics",
                "exploratory_not_co_primary_gate": True,
                "ten_second_budget_role": protocol["time"]["ten_second_role"],
                "group_count": len(sensitivity_statistics),
                "groups": sensitivity_statistics,
            },
        )
    figures = _generate_figures(
        report_root,
        paired_statistics=paired_statistics,
        metrics=all_metrics,
    )
    with (report_root / "report.md").open("w", encoding="utf-8", newline="\n") as handle:
        _render_report(
            handle,
            pair_count=len(complete_pairs),
            statistics=paired_statistics,
            failures=all_failures,
            figures=figures,
            research_gate=research_gate,
        )
    artifact_names = [
        "metrics-long.jsonl",
        "metrics-long.csv",
        "failures.csv",
        "paired-statistics.json",
        "report.md",
        *(["sensitivity-statistics.json"] if observed_extension_ids else []),
        *figures,
    ]
    report_index = {
        "schema_version": "1.0.0",
        "record_type": "c6_report_index",
        "protocol_sha256": canonical_sha256(protocol),
        "complete_pair_count": len(complete_pairs),
        "rolling_only_budget_unit_count": len(rolling_only_units),
        "report_scope": (
            "formal_extension_exploratory"
            if observed_extension_ids and not observed_formal_ids
            else "formal_core"
        ),
        "exploratory_not_co_primary_gate": bool(observed_extension_ids),
        "incomplete_units": incomplete_units,
        "research_gate": research_gate,
        "artifact_sha256": {name: sha256_file(report_root / name) for name in artifact_names},
    }
    _write_json(report_root / "report-index.json", report_index)
    return report_index
