"""Fail-closed loading entry point for saved C6 comparison evidence."""

from __future__ import annotations

import hmac
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from parking_opt.application.presentation.models import (
    ComparisonEvidenceView,
    ComparisonMetricView,
)
from parking_opt.application.presentation.evidence import (
    _BASELINE_ID,
    _CANDIDATE_ID,
    _PAIR_FIELDS,
    ComparisonEvidenceError,
    _metric_unit,
    _read_object,
    _require_fields,
    _resolve_evidence_root,
    _run_view,
    _sha256,
)


def _metric_views(
    statistics: Mapping[str, Any],
    *,
    pair_count: int,
) -> tuple[ComparisonMetricView, ...]:
    raw_metrics = statistics.get("metrics")
    if not isinstance(raw_metrics, dict):
        raise ComparisonEvidenceError("D4_METRICS_OBJECT_REQUIRED")
    views: list[ComparisonMetricView] = []
    for metric_name, raw in sorted(raw_metrics.items()):
        if not isinstance(raw, dict):
            raise ComparisonEvidenceError(f"D4_METRIC_OBJECT_REQUIRED: {metric_name}")
        baseline_values = raw.get("baseline_values")
        candidate_values = raw.get("candidate_values")
        paired = raw.get("paired")
        if (
            not isinstance(baseline_values, list)
            or not isinstance(candidate_values, list)
            or not isinstance(paired, dict)
            or len(baseline_values) != pair_count
            or len(candidate_values) != pair_count
        ):
            raise ComparisonEvidenceError(f"D4_PAIR_COUNT_MISMATCH: {metric_name}")
        descriptive = paired.get("descriptive")
        if not isinstance(descriptive, dict) or int(descriptive.get("n", -1)) != pair_count:
            raise ComparisonEvidenceError(f"D4_STATISTIC_N_MISMATCH: {metric_name}")
        if pair_count != 1:
            raise ComparisonEvidenceError("D4_FIXTURE_SCOPE_REQUIRES_ONE_PAIR")
        baseline_value = float(baseline_values[0])
        candidate_value = float(candidate_values[0])
        difference = float(descriptive["mean"])
        if not math.isclose(
            difference,
            candidate_value - baseline_value,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise ComparisonEvidenceError(f"D4_PAIRED_DIFFERENCE_MISMATCH: {metric_name}")
        name = str(metric_name)
        views.append(
            ComparisonMetricView(
                metric_name=name,
                unit=_metric_unit(name),
                baseline_value=baseline_value,
                candidate_value=candidate_value,
                paired_difference=difference,
                sample_n=pair_count,
                completed_only=name.endswith("_completed_only_mean"),
                censoring_rate=name.endswith("_censoring_rate"),
            )
        )
    return tuple(views)


def load_comparison_evidence(
    path: Path,
    *,
    allowed_root: Path,
) -> ComparisonEvidenceView:
    root = _resolve_evidence_root(path, allowed_root)
    metadata_path = root / "evidence-metadata.json"
    statistics_path = root / "paired-statistics.json"
    report_path = root / "report-index.json"
    metadata = _read_object(metadata_path)
    statistics = _read_object(statistics_path)
    report = _read_object(report_path)
    _require_fields(
        metadata,
        (
            "schema_version",
            "record_type",
            "source_kind",
            "purpose",
            "paired_statistics_sha256",
            "report_index_sha256",
            "rolling_default_enabled",
            "ten_second_budget_role",
            "baseline",
            "candidate",
        ),
        label="evidence metadata",
    )
    if metadata["schema_version"] != "1.0.0" or metadata["record_type"] != "d4_comparison_evidence":
        raise ComparisonEvidenceError("D4_METADATA_VERSION")
    expected_hashes = {
        "paired-statistics.json": cast(str, metadata["paired_statistics_sha256"]),
        "report-index.json": cast(str, metadata["report_index_sha256"]),
    }
    for artifact, expected in expected_hashes.items():
        if not hmac.compare_digest(_sha256(root / artifact), expected):
            raise ComparisonEvidenceError(f"D4_HASH_MISMATCH: {artifact}")
    report_artifacts = report.get("artifact_sha256")
    if (
        not isinstance(report_artifacts, dict)
        or report_artifacts.get("paired-statistics.json")
        != expected_hashes["paired-statistics.json"]
    ):
        raise ComparisonEvidenceError("D4_REPORT_INDEX_HASH_MISMATCH")
    if statistics.get("record_type") != "c6_paired_statistics":
        raise ComparisonEvidenceError("D4_STATISTICS_RECORD_TYPE")
    if report.get("record_type") != "c6_report_index":
        raise ComparisonEvidenceError("D4_REPORT_RECORD_TYPE")
    statistics_gate = statistics.get("research_gate")
    report_gate = report.get("research_gate")
    if not isinstance(statistics_gate, dict) or statistics_gate != report_gate:
        raise ComparisonEvidenceError("D4_RESEARCH_GATE_MISMATCH")
    _require_fields(
        statistics_gate,
        (
            "formal_pair_count",
            "required_formal_pair_count",
            "formal_seed_count",
            "required_formal_seed_count",
            "status",
        ),
        label="research gate",
    )
    pair_count = int(statistics.get("pair_count", -1))
    if pair_count != int(statistics_gate["formal_pair_count"]):
        raise ComparisonEvidenceError("D4_FORMAL_PAIR_COUNT_MISMATCH")
    if not isinstance(metadata["baseline"], dict) or not isinstance(metadata["candidate"], dict):
        raise ComparisonEvidenceError("D4_RUN_EVIDENCE_OBJECT_REQUIRED")
    baseline_raw = cast(Mapping[str, Any], metadata["baseline"])
    candidate_raw = cast(Mapping[str, Any], metadata["candidate"])
    mismatched = [
        field for field in _PAIR_FIELDS if baseline_raw.get(field) != candidate_raw.get(field)
    ]
    if mismatched:
        raise ComparisonEvidenceError(f"D4_PAIRED_INPUT_MISMATCH: {mismatched}")
    baseline = _run_view(baseline_raw)
    candidate = _run_view(candidate_raw)
    if baseline.algorithm_id != _BASELINE_ID or candidate.algorithm_id != _CANDIDATE_ID:
        raise ComparisonEvidenceError("D4_ALGORITHM_ROLE_MISMATCH")
    if baseline.run_status != "COMPLETED" or candidate.run_status != "COMPLETED":
        raise ComparisonEvidenceError("D4_INCOMPLETE_RUN")
    if baseline.scenario_id != candidate.scenario_id:
        raise ComparisonEvidenceError("D4_SCENARIO_MISMATCH")
    if metadata["source_kind"] != "synthetic":
        raise ComparisonEvidenceError("D4_FIXTURE_SOURCE_MUST_BE_SYNTHETIC")
    if metadata["rolling_default_enabled"] is not False:
        raise ComparisonEvidenceError("D4_ROLLING_DEFAULT_MUST_BE_FALSE")
    metrics = _metric_views(statistics, pair_count=pair_count)
    artifact_hashes = (
        ("paired-statistics.json", expected_hashes["paired-statistics.json"]),
        ("report-index.json", expected_hashes["report-index.json"]),
        (
            "source-baseline-artifact-index.json",
            cast(str, baseline_raw["source_artifact_index_sha256"]),
        ),
        (
            "source-candidate-artifact-index.json",
            cast(str, candidate_raw["source_artifact_index_sha256"]),
        ),
    )
    return ComparisonEvidenceView(
        source_kind=cast(str, metadata["source_kind"]),
        purpose=cast(str, metadata["purpose"]),
        pair_key_status="MATCHED",
        pair_key=tuple((field, cast(str | int, baseline_raw[field])) for field in _PAIR_FIELDS),
        baseline=baseline,
        candidate=candidate,
        metrics=metrics,
        formal_pair_count=int(statistics_gate["formal_pair_count"]),
        required_formal_pair_count=int(statistics_gate["required_formal_pair_count"]),
        formal_seed_count=int(statistics_gate["formal_seed_count"]),
        required_formal_seed_count=int(statistics_gate["required_formal_seed_count"]),
        research_gate_status=cast(str, statistics_gate["status"]),
        rolling_default_enabled=False,
        ten_second_budget_role=cast(str, metadata["ten_second_budget_role"]),
        artifact_sha256=artifact_hashes,
    )
