"""Regenerate paired statistics, static figures, and Markdown from saved artifacts."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from statistics import fmean
from typing import Any, TextIO, cast

from parking_opt.contracts.canonical import canonical_json_bytes, canonical_sha256
from parking_opt.experiments.protocol import (
    core_experiment_units,
    sensitivity_experiment_units,
)
from parking_opt.experiments.runner import sha256_file, validate_completed_run
from parking_opt.experiments.statistics import descriptive_summary, paired_bootstrap_summary

BASELINE_ID = "online-rule-v1"
CANDIDATE_ID = "rolling-candidate-v1"
CO_PRIMARY_METRICS = (
    "normal_space_time_utilization",
    "demand_satisfaction_rate",
    "relocation_distance_m",
)
REQUEST_METRICS = ("arrival_wait_s", "departure_wait_s", "departure_delay_s")


def _read_jsonl(path: Path) -> tuple[dict[str, Any], ...]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise TypeError(f"{path}:{line_number} is not a JSON object")
            records.append(cast(dict[str, Any], value))
    return tuple(records)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def _write_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> None:
    payload = bytearray()
    for record in records:
        payload.extend(canonical_json_bytes(record))
        payload.extend(b"\n")
    path.write_bytes(bytes(payload))


def _completed_run_roots(experiment_root: Path) -> tuple[Path, ...]:
    roots = sorted(
        item.parent for item in (experiment_root / "runs").glob("*/*/artifact-index.json")
    )
    if not roots:
        raise ValueError(f"no completed C6 run artifacts found under {experiment_root}")
    return tuple(roots)


def _failed_attempt_rows(experiment_root: Path) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    attempts_root = experiment_root / "attempts"
    if not attempts_root.exists():
        return ()
    for failure_path in sorted(attempts_root.rglob("run-failure.json")):
        failure = json.loads(failure_path.read_text(encoding="utf-8"))
        if not isinstance(failure, dict):
            raise TypeError(f"{failure_path} is not a JSON object")
        relative = failure_path.relative_to(experiment_root).as_posix()
        algorithm_id = (
            failure_path.parent.parent.name
            if failure_path.parent.parent != failure_path.parent
            else "unknown"
        )
        rows.append(
            {
                "run_id": str(failure.get("run_id", "unknown-failed-run")),
                "algorithm_id": algorithm_id,
                "record": {
                    "record_type": "runtime_failure",
                    "attempt_path": relative,
                    **failure,
                },
            }
        )
    return tuple(rows)


def _run_values(
    metric_records: Sequence[Mapping[str, Any]],
) -> dict[str, float]:
    values: dict[str, float] = {}
    request_values: dict[str, list[float]] = defaultdict(list)
    request_counts: dict[str, int] = defaultdict(int)
    censored_counts: dict[str, int] = defaultdict(int)
    for record in metric_records:
        metric_name = str(record["metric_name"])
        value = record["value"]
        if value is None:
            continue
        if record["record_level"] == "request_observation":
            request_counts[metric_name] += 1
            if record["event_observed"] is True:
                request_values[metric_name].append(float(value))
            else:
                censored_counts[metric_name] += 1
        else:
            values[metric_name] = float(value)
    for metric_name in REQUEST_METRICS:
        observed = request_values.get(metric_name, [])
        if observed:
            values[f"{metric_name}_completed_only_mean"] = fmean(observed)
        total = request_counts.get(metric_name, 0)
        if total:
            values[f"{metric_name}_censoring_rate"] = censored_counts[metric_name] / total
    return values


def _validate_pair(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> None:
    equal_fields = (
        "unit_id",
        "random_seed",
        "protocol_sha256",
        "layout_sha256",
        "scenario_sha256",
        "event_truth_sha256",
        "arrival_count",
    )
    mismatched = [field for field in equal_fields if baseline[field] != candidate[field]]
    if mismatched:
        raise ValueError(f"paired run input mismatch: {mismatched}")
    if baseline["algorithm_id"] != BASELINE_ID:
        raise ValueError("paired baseline has the wrong algorithm ID")
    if candidate["algorithm_id"] != CANDIDATE_ID:
        raise ValueError("paired candidate has the wrong algorithm ID")


def _sensitivity_group(index: Mapping[str, Any]) -> str:
    fields = (
        "experiment_slice",
        "layout_class",
        "load_level",
        "buffer_count",
        "relocation_executor_capacity",
        "recoverability_policy",
        "departure_information_source",
        "facility_comparison_mode",
        "user_cancellation_probability",
        "experiment_budget_s",
    )
    return "|".join(f"{field}={index.get(field)}" for field in fields)


def _write_metrics_csv(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    fieldnames = (
        "run_id",
        "scenario_id",
        "algorithm_id",
        "record_level",
        "subject_vehicle_id",
        "subject_request_id",
        "metric_name",
        "value",
        "unit",
        "event_observed",
        "pending_at_horizon",
        "observed_wait_lower_bound_s",
        "dimensions_json",
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    **{name: record.get(name) for name in fieldnames[:-1]},
                    "dimensions_json": json.dumps(
                        record["dimensions"],
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                }
            )


def _write_failures_csv(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = ("run_id", "algorithm_id", "record_json")
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "run_id": row["run_id"],
                    "algorithm_id": row["algorithm_id"],
                    "record_json": json.dumps(
                        row["record"],
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                }
            )


def _generate_figures(
    report_root: Path,
    *,
    paired_statistics: Mapping[str, Any],
    metrics: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    import matplotlib

    matplotlib.use("Agg")
    matplotlib.rcParams["svg.hashsalt"] = "parking-opt-c6-v1"
    from matplotlib import pyplot as plt

    figure_root = report_root / "figures"
    figure_root.mkdir(parents=True, exist_ok=True)
    generated: list[str] = []

    available = [metric for metric in CO_PRIMARY_METRICS if metric in paired_statistics]
    if available:
        differences = [
            float(paired_statistics[metric]["paired"]["descriptive"]["mean"])
            for metric in available
        ]
        fig, axis = plt.subplots(figsize=(8, 4.5))
        axis.bar(available, differences, color="#35618f")
        axis.axhline(0, color="black", linewidth=0.8)
        axis.set_ylabel("candidate - baseline")
        axis.set_title("Paired co-primary differences from saved MetricRecord rows")
        axis.tick_params(axis="x", rotation=20)
        fig.tight_layout()
        relative = "paired-co-primary-differences.svg"
        fig.savefig(figure_root / relative, format="svg", metadata={"Date": None})
        plt.close(fig)
        generated.append(f"figures/{relative}")

    delay_rows = [
        item
        for item in metrics
        if item["metric_name"] == "departure_delay_s"
        and item["record_level"] == "request_observation"
        and item["event_observed"] is True
        and item["value"] is not None
    ]
    if delay_rows:
        grouped = {
            algorithm_id: [
                float(item["value"]) for item in delay_rows if item["algorithm_id"] == algorithm_id
            ]
            for algorithm_id in (BASELINE_ID, CANDIDATE_ID)
        }
        if all(grouped.values()):
            fig, axis = plt.subplots(figsize=(8, 4.5))
            axis.boxplot(
                [grouped[BASELINE_ID], grouped[CANDIDATE_ID]],
                tick_labels=[BASELINE_ID, CANDIDATE_ID],
                showfliers=True,
            )
            axis.set_ylabel("completed-only departure delay (s)")
            axis.set_title("Departure-delay distribution from saved request records")
            fig.tight_layout()
            relative = "departure-delay-completed-only.svg"
            fig.savefig(figure_root / relative, format="svg", metadata={"Date": None})
            plt.close(fig)
            generated.append(f"figures/{relative}")
    return tuple(generated)


def _render_report(
    handle: TextIO,
    *,
    pair_count: int,
    statistics: Mapping[str, Any],
    failures: Sequence[Mapping[str, Any]],
    figures: Sequence[str],
    research_gate: Mapping[str, Any],
) -> None:
    handle.write("# C6 正式实验阶段性报告\n\n")
    handle.write(
        "本报告只由已保存的 RunManifest、MetricRecord、请求记录和失败记录再生。"
        "当前证据来自 synthetic 正式小单元, 不能外推为真实停车场收益。\n\n"
    )
    handle.write(f"- 完整配对单元数: {pair_count}\n")
    handle.write(f"- 失败/回退记录数: {len(failures)}\n")
    handle.write(f"- 滚动研究保留门: `{research_gate['status']}`\n\n")
    handle.write("## 配对结果 (滚动候选减在线基线)\n\n")
    handle.write("| 指标 | n | 均值差 | 标准差 | 中位数 | IQR | 95% bootstrap CI | 相对均值差 |\n")
    handle.write("|---|---:|---:|---:|---:|---:|---:|---:|\n")
    for metric_name, value in sorted(statistics.items()):
        paired = value["paired"]
        relative = paired["relative_difference_mean"]
        relative_text = "NA" if relative is None else f"{relative:.6f}"
        handle.write(
            f"| `{metric_name}` | {paired['descriptive']['n']} | "
            f"{paired['descriptive']['mean']:.6f} | "
            f"{paired['descriptive']['standard_deviation']:.6f} | "
            f"{paired['descriptive']['median']:.6f} | "
            f"{paired['descriptive']['iqr']:.6f} | "
            f"[{paired['ci_lower']:.6f}, {paired['ci_upper']:.6f}] | "
            f"{relative_text} |\n"
        )
    handle.write("\n")
    handle.write(
        "样本量不足完整 20-seed 核心矩阵时, 置信区间只验证统计流水线,不得用于通过研究保留门。\n\n"
    )
    handle.write("## 静态图\n\n")
    for figure in figures:
        handle.write(f"- [{figure}]({figure})\n")
    if not figures:
        handle.write("- 当前保存记录不足以生成图。\n")
    handle.write("\n## 未完成的冻结分析\n\n")
    handle.write(
        "- 0/1/2 缓冲比较、资源容量 1/2、双恢复策略、软信息、取消和预算敏感性"
        "需要剩余正式矩阵; 当前不得据此下结论。\n"
    )
    handle.write("- 所有不利场景、失败、超时、右删失与显式降级均保留在原始产物中。\n")


def generate_report(
    *,
    experiment_root: Path,
    protocol: dict[str, Any],
) -> dict[str, Any]:
    """Verify completed runs and regenerate every report artifact from disk."""

    report_root = experiment_root / "report"
    report_root.mkdir(parents=True, exist_ok=True)
    indexes: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    metrics_by_run: dict[str, tuple[dict[str, Any], ...]] = {}
    all_metrics: list[dict[str, Any]] = []
    all_failures: list[dict[str, Any]] = list(_failed_attempt_rows(experiment_root))
    for run_root in _completed_run_roots(experiment_root):
        index = validate_completed_run(run_root)
        unit_id = str(index["unit_id"])
        algorithm_id = str(index["algorithm_id"])
        if algorithm_id in indexes[unit_id]:
            raise ValueError(f"duplicate algorithm run for unit {unit_id}: {algorithm_id}")
        indexes[unit_id][algorithm_id] = index
        run_metrics = _read_jsonl(run_root / "metrics.jsonl")
        metrics_by_run[str(index["run_id"])] = run_metrics
        all_metrics.extend(run_metrics)
        for failure in _read_jsonl(run_root / "failures.jsonl"):
            all_failures.append(
                {
                    "run_id": index["run_id"],
                    "algorithm_id": algorithm_id,
                    "record": failure,
                }
            )

    complete_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    rolling_only_units: list[dict[str, Any]] = []
    incomplete_units: list[str] = []
    for unit_id, algorithms in sorted(indexes.items()):
        slice_name = str(next(iter(algorithms.values())).get("experiment_slice", "core"))
        if slice_name == "budget":
            if CANDIDATE_ID not in algorithms:
                incomplete_units.append(unit_id)
            else:
                rolling_only_units.append(algorithms[CANDIDATE_ID])
            continue
        if BASELINE_ID not in algorithms or CANDIDATE_ID not in algorithms:
            incomplete_units.append(unit_id)
            continue
        baseline = algorithms[BASELINE_ID]
        candidate = algorithms[CANDIDATE_ID]
        _validate_pair(baseline, candidate)
        complete_pairs.append((baseline, candidate))
    if not complete_pairs and not rolling_only_units:
        raise ValueError("report requires a complete pair or rolling-only budget unit")

    observed_formal_ids = {
        unit_id
        for unit_id, algorithms in indexes.items()
        if any(index["seed_partition"] == "formal_core" for index in algorithms.values())
    }
    if observed_formal_ids:
        expected_formal_ids = {unit.unit_id for unit in core_experiment_units(protocol)}
        unknown_formal_ids = observed_formal_ids - expected_formal_ids
        if unknown_formal_ids:
            raise ValueError(
                f"formal runs contain units outside the frozen core matrix: "
                f"{sorted(unknown_formal_ids)}"
            )
        incomplete_units = sorted(
            set(incomplete_units) | (expected_formal_ids - observed_formal_ids)
        )
    observed_extension_ids = {
        unit_id
        for unit_id, algorithms in indexes.items()
        if any(index["seed_partition"] == "formal_extension" for index in algorithms.values())
    }
    if observed_extension_ids:
        expected_extension_ids = {unit.unit_id for unit in sensitivity_experiment_units(protocol)}
        unknown_extension_ids = observed_extension_ids - expected_extension_ids
        if unknown_extension_ids:
            raise ValueError(
                "formal extension contains units outside the sensitivity plan: "
                f"{sorted(unknown_extension_ids)}"
            )
        incomplete_units = sorted(
            set(incomplete_units) | (expected_extension_ids - observed_extension_ids)
        )

    metric_pairs: dict[str, tuple[list[float], list[float]]] = {}
    co_primary_pairs = (
        [
            pair
            for pair in complete_pairs
            if all(index["seed_partition"] == "formal_core" for index in pair)
        ]
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
            common_metrics = set(algorithm_values[BASELINE_ID]) & set(
                algorithm_values[CANDIDATE_ID]
            )
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
        pair
        for pair in complete_pairs
        if all(index["seed_partition"] == "formal_core" for index in pair)
    ]
    formal_seed_count = len({int(index["random_seed"]) for pair in formal_pairs for index in pair})
    required_seed_count = len(protocol["seed_sets"]["formal_core"])
    required_formal_pair_count = len(core_experiment_units(protocol))
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
