"""Materialize one validated, resumable experiment run from frozen inputs."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, cast

from parking_opt.contracts import (
    SchemaCatalog,
    canonical_json_bytes,
    canonical_sha256,
    validate_layout_semantics,
    validate_scenario_semantics,
)
from parking_opt.demand.scenario import generate_synthetic_scenario
from parking_opt.domain.invariants import assert_state_invariants
from parking_opt.evaluation.metrics import (
    MetricContext,
    compute_metrics,
    write_metric_jsonl,
)
from parking_opt.experiments.protocol import (
    ExperimentUnit,
    algorithm_ids_for_unit,
    validate_unit,
)
from parking_opt.layout.model import layout_from_mapping
from parking_opt.logging.event_writer import FileEventSink
from parking_opt.logging.run_metadata import (
    build_run_manifest,
    git_identity,
    write_run_manifest,
)
from parking_opt.optimization.rolling import RollingCandidatePolicy
from parking_opt.simulation.engine import DeterministicSimulation, approved_config_from_scenario
from parking_opt.strategies.online_rule import OnlineRulePolicy

ALGORITHM_VERSION = "1.0.0"
ROLLING_BOUNDS = {
    "max_requests_per_solve": 12,
    "max_positions_per_arrival": 8,
    "max_buffer_matchings_per_departure": 4,
    "max_action_plans_total": 64,
    "max_soft_future_records": 20,
}
_FAILURE_EVENT_TYPES = {
    "ACTION_FAILED_KNOWN_POSITION",
    "ACTION_FAILED_POSITION_UNKNOWN",
    "MANUAL_INTERVENTION_REQUESTED",
}
REQUIRED_RUN_ARTIFACTS = frozenset(
    {
        "layout.json",
        "scenario.json",
        "events.jsonl",
        "decisions.jsonl",
        "metrics.jsonl",
        "requests.jsonl",
        "failures.jsonl",
        "run-manifest.json",
    }
)


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return cast(dict[str, Any], value)


def _write_object(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def _write_jsonl(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    payload = bytearray()
    for record in records:
        payload.extend(canonical_json_bytes(record))
        payload.extend(b"\n")
    path.write_bytes(bytes(payload))


def sha256_file(path: Path) -> str:
    """Hash one exact saved artifact."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def layout_path_for_unit(repo_root: Path, unit: ExperimentUnit) -> Path:
    """Resolve the preregistered fixed-total layout fixture for a unit."""

    family = "mixed-depth" if unit.layout_class == "mixed_depth" else "independent"
    if unit.facility_comparison_mode == "extra_buffer_space":
        filename = f"mixed-depth-extra-buffer-b{unit.buffer_count}-v1.synthetic.json"
    else:
        filename = f"{family}-fixed-total-b{unit.buffer_count}-v1.synthetic.json"
    return repo_root / "data" / "synthetic" / "fixtures" / "c2" / "layouts" / filename


def run_id_for(unit: ExperimentUnit, algorithm_id: str) -> str:
    """Return a stable run identifier for resume and pairing."""

    partition = {
        "development": "dev",
        "formal_core": "formal",
        "formal_extension": "extension",
        "tuning": "tuning",
    }[unit.partition.value]
    layout = {"mixed_depth": "mixed", "independent": "independent"}[unit.layout_class]
    algorithm = {
        "online-rule-v1": "online",
        "rolling-candidate-v1": "rolling",
    }[algorithm_id]
    core_id = (
        f"c6-{partition}-{layout}-{unit.load_level}-b{unit.buffer_count}"
        f"-e{unit.relocation_executor_capacity}-seed{unit.seed}-{algorithm}"
    )
    if unit.experiment_slice == "core":
        return core_id
    cancellation = str(unit.user_cancellation_probability).replace(".", "p")
    budget = (
        "none"
        if unit.experiment_budget_s is None
        else str(unit.experiment_budget_s).replace(".", "p")
    )
    return (
        f"c6-{partition}-{unit.experiment_slice}-{layout}-{unit.load_level}"
        f"-b{unit.buffer_count}-e{unit.relocation_executor_capacity}"
        f"-{unit.departure_information_source}-cancel{cancellation}"
        f"-budget{budget}-seed{unit.seed}-{algorithm}"
    )


def _percentile_95(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, int(0.95 * len(ordered)) - 1))]


def _decision_diagnostics(
    decisions: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    *,
    deadline_s: float,
) -> dict[str, Any]:
    timings = [float(item["timing"]["end_to_end_s"]) for item in decisions]
    fallback_decisions = [item for item in decisions if item["fallback_record"] is not None]
    fallback_decision_ids = Counter(str(item["decision_id"]) for item in fallback_decisions)
    logged_fallback_ids = Counter(
        str(item["payload"].get("decision_id"))
        for item in events
        if item["event_type"] == "FALLBACK_USED"
    )
    unlogged_fallbacks = sum((fallback_decision_ids - logged_fallback_ids).values())
    orphan_fallback_logs = sum((logged_fallback_ids - fallback_decision_ids).values())
    statuses = Counter(str(item["solver_status"]) for item in decisions)
    reasons = Counter(
        str(item["fallback_record"]["reason"])
        for item in fallback_decisions
        if item["fallback_record"] is not None
    )
    return {
        "decision_count": len(decisions),
        "solver_status_counts": dict(sorted(statuses.items())),
        "fallback_reason_counts": dict(sorted(reasons.items())),
        "fallback_count": len(fallback_decisions),
        "fallback_rate": len(fallback_decisions) / len(decisions) if decisions else 0.0,
        "logged_fallback_count": sum(logged_fallback_ids.values()),
        "unlogged_fallback_count": unlogged_fallbacks,
        "orphan_fallback_log_count": orphan_fallback_logs,
        "fallback_log_mismatch_count": unlogged_fallbacks + orphan_fallback_logs,
        "hard_deadline_violation_count": sum(value > deadline_s for value in timings),
        "decision_end_to_end_s_max": max(timings, default=0.0),
        "decision_end_to_end_s_p95": _percentile_95(timings),
    }


def _failure_records(
    decisions: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    records: list[dict[str, Any]] = []
    for decision in decisions:
        fallback = decision["fallback_record"]
        if fallback is not None:
            records.append(
                {
                    "record_type": "fallback",
                    "decision_id": decision["decision_id"],
                    "reason": fallback["reason"],
                    "original_solver_status": fallback["original_solver_status"],
                    "used_strategy": fallback["used_strategy"],
                    "elapsed_s": fallback["elapsed_s"],
                }
            )
    for event in events:
        if event["event_type"] in _FAILURE_EVENT_TYPES:
            records.append(
                {
                    "record_type": "event_failure",
                    "event_id": event["event_id"],
                    "event_type": event["event_type"],
                    "sim_time_s": event["sim_time_s"],
                    "anonymous_vehicle_id": event["anonymous_vehicle_id"],
                    "payload": event["payload"],
                }
            )
    return tuple(records)


def _completed_index_is_valid(
    run_root: Path,
    *,
    schema_catalog: SchemaCatalog | None = None,
) -> bool:
    index_path = run_root / "artifact-index.json"
    if not index_path.exists():
        return False
    try:
        index = _read_object(index_path)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    if index.get("run_status") != "COMPLETED":
        return False
    hashes = index.get("artifact_sha256")
    if not isinstance(hashes, dict):
        return False
    if set(hashes) != REQUIRED_RUN_ARTIFACTS:
        return False
    if not all(
        isinstance(relative, str)
        and isinstance(expected, str)
        and len(expected) == 64
        and (path := run_root / relative).is_file()
        and path.parent == run_root
        and sha256_file(path) == expected
        for relative, expected in hashes.items()
    ):
        return False
    try:
        manifest = _read_object(run_root / "run-manifest.json")
        if schema_catalog is not None:
            schema_catalog.validate("run-manifest.schema.json", manifest)
        if (
            manifest.get("run_status") != "COMPLETED"
            or manifest.get("run_id") != index.get("run_id")
            or manifest.get("algorithm_id") != index.get("algorithm_id")
            or manifest.get("algorithm_version") != index.get("algorithm_version")
            or manifest.get("random_seed") != index.get("random_seed")
        ):
            return False
        scenario = _read_object(run_root / "scenario.json")
        layout = _read_object(run_root / "layout.json")
        if schema_catalog is not None:
            schema_catalog.validate("scenario.schema.json", scenario)
            schema_catalog.validate("layout.schema.json", layout)
        if (
            scenario.get("scenario_id") != manifest.get("scenario_id")
            or scenario.get("layout_id") != layout.get("layout_id")
            or canonical_sha256(scenario) != index.get("scenario_sha256")
            or canonical_sha256(layout) != index.get("layout_sha256")
        ):
            return False
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return False
    return True


def validate_completed_run(
    run_root: Path,
    *,
    schema_catalog: SchemaCatalog | None = None,
) -> dict[str, Any]:
    """Validate every indexed byte before a run is reused."""

    if not _completed_index_is_valid(run_root, schema_catalog=schema_catalog):
        raise ValueError(f"completed run is missing or has a hash mismatch: {run_root}")
    return _read_object(run_root / "artifact-index.json")


def run_experiment(
    *,
    repo_root: Path,
    output_root: Path,
    protocol: dict[str, Any],
    unit: ExperimentUnit,
    algorithm_id: str,
    command: str,
) -> dict[str, Any]:
    """Run or safely resume one algorithm on one frozen scenario unit."""

    validate_unit(
        protocol,
        unit,
        require_core_membership=unit.partition.value == "formal_core",
    )
    if algorithm_id not in {"online-rule-v1", "rolling-candidate-v1"}:
        raise ValueError(f"algorithm is not in the approved C6 comparison: {algorithm_id}")
    if algorithm_id not in algorithm_ids_for_unit(protocol, unit):
        raise ValueError(f"{algorithm_id} is not approved for slice {unit.experiment_slice}")
    if unit.partition.value in {"formal_core", "formal_extension"}:
        _, dirty = git_identity(repo_root)
        if dirty:
            raise RuntimeError("formal-core runs require a clean Git worktree")
    run_id = run_id_for(unit, algorithm_id)
    catalog = SchemaCatalog(repo_root / "schemas" / "v1")
    run_root = output_root / "runs" / unit.unit_id / algorithm_id
    if run_root.exists():
        if _completed_index_is_valid(run_root, schema_catalog=catalog):
            index = validate_completed_run(run_root, schema_catalog=catalog)
            index["resume_status"] = "SKIPPED_ALREADY_COMPLETED"
            return index
        raise FileExistsError(f"incomplete or invalid run directory retained for audit: {run_root}")
    run_root.parent.mkdir(parents=True, exist_ok=True)
    attempt_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    artifact_root = output_root / "attempts" / unit.unit_id / algorithm_id / attempt_id
    artifact_root.mkdir(parents=True)

    protocol_hash = canonical_sha256(protocol)
    layout_path = layout_path_for_unit(repo_root, unit)
    layout_mapping = _read_object(layout_path)
    catalog.validate("layout.schema.json", layout_mapping)
    validate_layout_semantics(layout_mapping)
    layout = layout_from_mapping(layout_mapping)
    generated = generate_synthetic_scenario(
        layout=layout,
        layout_family=unit.layout_class,
        load_level=unit.load_level,
        seed=unit.seed,
        seed_partition=unit.partition,
        protocol=protocol,
        recoverability_policy=unit.recoverability_policy,
        relocation_executor_capacity=unit.relocation_executor_capacity,
        cancellation_probability=unit.user_cancellation_probability,
        departure_information_source=unit.departure_information_source,
    )
    scenario = generated.scenario
    catalog.validate("scenario.schema.json", scenario)
    validate_scenario_semantics(scenario, layout_mapping)
    _write_object(artifact_root / "layout.json", layout_mapping)
    _write_object(artifact_root / "scenario.json", scenario)

    if unit.experiment_budget_s is None:
        decision_target_s = float(protocol["time"]["decision_target_s"])
        decision_deadline_s = float(protocol["time"]["decision_deadline_s"])
        optimization_budget_s = decision_target_s
    else:
        decision_target_s = unit.experiment_budget_s
        decision_deadline_s = unit.experiment_budget_s
        optimization_budget_s = unit.experiment_budget_s
    rolling = algorithm_id == "rolling-candidate-v1"
    overrides = (
        {
            "rolling_enabled": True,
            "optimization_budget_s": optimization_budget_s,
            "use_soft_departure_information": (unit.departure_information_source != "unknown"),
            **ROLLING_BOUNDS,
        }
        if rolling
        else None
    )
    decision_config = approved_config_from_scenario(scenario)
    if overrides is not None:
        decision_config.update(overrides)
    config_sha256 = canonical_sha256(decision_config)
    event_path = artifact_root / "events.jsonl"
    event_path.write_bytes(b"")
    started_at = datetime.now(UTC).isoformat()
    started_clock = perf_counter()
    try:
        policy = (
            RollingCandidatePolicy(schema_catalog=catalog)
            if rolling
            else OnlineRulePolicy(schema_catalog=catalog)
        )
        with FileEventSink(event_path) as sink:
            simulation = DeterministicSimulation(
                run_id=run_id,
                layout=layout,
                scenario=scenario,
                policy=policy,
                schema_catalog=catalog,
                event_sink=sink,
                event_log_path=event_path,
                decision_config_overrides=overrides,
                algorithm_id=algorithm_id,
                algorithm_version=ALGORITHM_VERSION,
                decision_target_s=decision_target_s,
                decision_deadline_s=decision_deadline_s,
            )
            result = simulation.run()
        assert_state_invariants(result.final_state)
    except Exception as exc:
        ended_at = datetime.now(UTC).isoformat()
        _write_object(
            artifact_root / "run-failure.json",
            {
                "run_id": run_id,
                "run_status": "FAILED",
                "exception_type": type(exc).__name__,
                "message": str(exc),
                "recorded_at": datetime.now(UTC).isoformat(),
            },
        )
        failed_manifest = build_run_manifest(
            repo_root=repo_root,
            run_id=run_id,
            scenario_id=scenario["scenario_id"],
            algorithm_id=algorithm_id,
            algorithm_version=ALGORITHM_VERSION,
            config_sha256=config_sha256,
            input_data_sha256=generated.scenario_content_sha256,
            random_seed=unit.seed,
            started_at=started_at,
            ended_at=ended_at,
            command=command,
            run_status="FAILED",
        )
        write_run_manifest(
            artifact_root / "run-manifest.json",
            failed_manifest,
            schema_catalog=catalog,
        )
        failure_artifacts = (
            "layout.json",
            "scenario.json",
            "events.jsonl",
            "run-failure.json",
            "run-manifest.json",
        )
        _write_object(
            artifact_root / "attempt-index.json",
            {
                "schema_version": "1.0.0",
                "record_type": "c6_failed_attempt_index",
                "run_id": run_id,
                "unit_id": unit.unit_id,
                "algorithm_id": algorithm_id,
                "run_status": "FAILED",
                "experiment_slice": unit.experiment_slice,
                "soft_information_truncation_count": (generated.soft_information_truncation_count),
                "artifact_sha256": {
                    name: sha256_file(artifact_root / name) for name in failure_artifacts
                },
            },
        )
        raise
    ended_at = datetime.now(UTC).isoformat()
    wall_clock_s = perf_counter() - started_clock

    decisions = result.decisions
    _write_jsonl(artifact_root / "decisions.jsonl", decisions)
    context = MetricContext(
        run_id=run_id,
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
        layout=layout,
        context=context,
    )
    write_metric_jsonl(artifact_root / "metrics.jsonl", metrics, schema_catalog=catalog)
    requests = tuple(item for item in metrics if item["record_level"] == "request_observation")
    _write_jsonl(artifact_root / "requests.jsonl", requests)
    failures = _failure_records(decisions, result.events)
    _write_jsonl(artifact_root / "failures.jsonl", failures)

    manifest = build_run_manifest(
        repo_root=repo_root,
        run_id=run_id,
        scenario_id=scenario["scenario_id"],
        algorithm_id=algorithm_id,
        algorithm_version=ALGORITHM_VERSION,
        config_sha256=config_sha256,
        input_data_sha256=generated.scenario_content_sha256,
        random_seed=unit.seed,
        started_at=started_at,
        ended_at=ended_at,
        command=command,
        run_status="COMPLETED",
    )
    write_run_manifest(artifact_root / "run-manifest.json", manifest, schema_catalog=catalog)
    diagnostics = _decision_diagnostics(
        decisions,
        result.events,
        deadline_s=decision_deadline_s,
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
        "run_id": run_id,
        "unit_id": unit.unit_id,
        "seed_partition": unit.partition.value,
        "experiment_slice": unit.experiment_slice,
        "departure_information_source": unit.departure_information_source,
        "facility_comparison_mode": unit.facility_comparison_mode,
        "user_cancellation_probability": unit.user_cancellation_probability,
        "soft_information_truncation_count": (generated.soft_information_truncation_count),
        "experiment_budget_s": unit.experiment_budget_s,
        "budget_role": (
            protocol["time"]["ten_second_role"]
            if unit.experiment_budget_s == 10.0
            else "online_sensitivity"
            if unit.experiment_budget_s is not None
            else None
        ),
        "algorithm_id": algorithm_id,
        "algorithm_version": ALGORITHM_VERSION,
        "random_seed": unit.seed,
        "protocol_sha256": protocol_hash,
        "layout_sha256": canonical_sha256(layout_mapping),
        "scenario_sha256": generated.scenario_content_sha256,
        "event_truth_sha256": generated.event_truth_sha256,
        "arrival_count": generated.arrival_count,
        "realized_offered_load_ratio": generated.realized_offered_load_ratio,
        "event_count": len(result.events),
        "metric_record_count": len(metrics),
        "request_record_count": len(requests),
        "failure_record_count": len(failures),
        "pending_request_count_at_horizon": len(result.final_state.pending_requests),
        "state_invariant_violation_count": 0,
        "wall_clock_s": wall_clock_s,
        "decision_diagnostics": diagnostics,
        "artifact_sha256": {name: sha256_file(artifact_root / name) for name in artifact_names},
        "resume_status": "EXECUTED",
    }
    if diagnostics["fallback_log_mismatch_count"] != 0:
        raise RuntimeError("fallback decisions and FALLBACK_USED events are not one-to-one")
    _write_object(artifact_root / "artifact-index.json", index)
    artifact_root.replace(run_root)
    return index
