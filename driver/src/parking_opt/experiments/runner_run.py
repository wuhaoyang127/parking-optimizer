"""Materialize one validated, resumable experiment run from frozen inputs."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from parking_opt.contracts import (
    SchemaCatalog,
    canonical_sha256,
    validate_layout_semantics,
    validate_scenario_semantics,
)
from parking_opt.demand.scenario import generate_synthetic_scenario
from parking_opt.experiments.protocol import (
    ExperimentUnit,
    algorithm_ids_for_unit,
    validate_unit,
)
from parking_opt.experiments.runner import (
    ROLLING_BOUNDS,
    _read_object,
    _write_object,
    layout_path_for_unit,
    run_id_for,
)
from parking_opt.experiments.runner_diagnostics import (
    _completed_index_is_valid,
    validate_completed_run,
)
from parking_opt.experiments.runner_index import build_index
from parking_opt.experiments.runner_simulate import run_simulation
from parking_opt.layout.model import layout_from_mapping
from parking_opt.logging.run_metadata import git_identity
from parking_opt.simulation.engine import approved_config_from_scenario


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

    ctx = {
        "repo_root": repo_root,
        "run_id": run_id,
        "catalog": catalog,
        "run_root": run_root,
        "artifact_root": artifact_root,
        "protocol": protocol,
        "protocol_hash": protocol_hash,
        "unit": unit,
        "algorithm_id": algorithm_id,
        "command": command,
        "layout_mapping": layout_mapping,
        "layout": layout,
        "scenario": scenario,
        "generated": generated,
        "scenario_content_sha256": generated.scenario_content_sha256,
        "rolling": rolling,
        "overrides": overrides,
        "decision_config": decision_config,
        "config_sha256": config_sha256,
        "decision_target_s": decision_target_s,
        "decision_deadline_s": decision_deadline_s,
    }
    result = run_simulation(ctx)
    return build_index(ctx, result)
