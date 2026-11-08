"""Run one deterministic simulation attempt with failure handling."""

from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from parking_opt.domain.invariants import assert_state_invariants
from parking_opt.experiments.runner import (
    ALGORITHM_VERSION,
    _write_object,
    sha256_file,
)
from parking_opt.logging.event_writer import FileEventSink
from parking_opt.logging.run_metadata import build_run_manifest, write_run_manifest
from parking_opt.optimization.rolling import RollingCandidatePolicy
from parking_opt.simulation.engine import DeterministicSimulation
from parking_opt.strategies.online_rule import OnlineRulePolicy


def run_simulation(ctx: dict[str, Any]):
    """Execute the policy inside an event sink, writing failure artifacts on error."""

    artifact_root = ctx["artifact_root"]
    event_path = artifact_root / "events.jsonl"
    event_path.write_bytes(b"")
    started_at = datetime.now(UTC).isoformat()
    started_clock = perf_counter()
    try:
        policy = (
            RollingCandidatePolicy(schema_catalog=ctx["catalog"])
            if ctx["rolling"]
            else OnlineRulePolicy(schema_catalog=ctx["catalog"])
        )
        with FileEventSink(event_path) as sink:
            simulation = DeterministicSimulation(
                run_id=ctx["run_id"],
                layout=ctx["layout"],
                scenario=ctx["scenario"],
                policy=policy,
                schema_catalog=ctx["catalog"],
                event_sink=sink,
                event_log_path=event_path,
                decision_config_overrides=ctx["overrides"],
                algorithm_id=ctx["algorithm_id"],
                algorithm_version=ALGORITHM_VERSION,
                decision_target_s=ctx["decision_target_s"],
                decision_deadline_s=ctx["decision_deadline_s"],
            )
            result = simulation.run()
        assert_state_invariants(result.final_state)
    except Exception as exc:
        ended_at = datetime.now(UTC).isoformat()
        _write_object(
            artifact_root / "run-failure.json",
            {
                "run_id": ctx["run_id"],
                "run_status": "FAILED",
                "exception_type": type(exc).__name__,
                "message": str(exc),
                "recorded_at": datetime.now(UTC).isoformat(),
            },
        )
        failed_manifest = build_run_manifest(
            repo_root=ctx["repo_root"],
            run_id=ctx["run_id"],
            scenario_id=ctx["scenario"]["scenario_id"],
            algorithm_id=ctx["algorithm_id"],
            algorithm_version=ALGORITHM_VERSION,
            config_sha256=ctx["config_sha256"],
            input_data_sha256=ctx["scenario_content_sha256"],
            random_seed=ctx["unit"].seed,
            started_at=started_at,
            ended_at=ended_at,
            command=ctx["command"],
            run_status="FAILED",
        )
        write_run_manifest(
            artifact_root / "run-manifest.json",
            failed_manifest,
            schema_catalog=ctx["catalog"],
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
                "run_id": ctx["run_id"],
                "unit_id": ctx["unit"].unit_id,
                "algorithm_id": ctx["algorithm_id"],
                "run_status": "FAILED",
                "experiment_slice": ctx["unit"].experiment_slice,
                "soft_information_truncation_count": (
                    ctx["generated"].soft_information_truncation_count
                ),
                "artifact_sha256": {
                    name: sha256_file(artifact_root / name) for name in failure_artifacts
                },
            },
        )
        raise
    ctx["ended_at"] = datetime.now(UTC).isoformat()
    ctx["wall_clock_s"] = perf_counter() - started_clock
    return result
