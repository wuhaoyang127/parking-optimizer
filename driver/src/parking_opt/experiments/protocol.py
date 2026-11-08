"""Strict projections of the approved stage-B experiment protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from parking_opt.demand.scenario import SeedPartition
from parking_opt.experiments.protocol_validation import validate_unit

ALGORITHM_ID_BY_PROTOCOL_KEY = {
    "online_rule_v1": "online-rule-v1",
    "rolling_candidate_v1": "rolling-candidate-v1",
}


@dataclass(frozen=True, slots=True)
class ExperimentUnit:
    """One paired scenario unit read from the frozen machine protocol."""

    partition: SeedPartition
    layout_class: str
    load_level: str
    buffer_count: int
    relocation_executor_capacity: int
    recoverability_policy: str
    departure_information_source: str
    facility_comparison_mode: str
    seed: int
    experiment_slice: str = "core"
    user_cancellation_probability: float = 0.0
    experiment_budget_s: float | None = None

    @property
    def unit_id(self) -> str:
        """Return a filesystem-safe stable unit identifier."""

        core_id = (
            f"{self.partition.value}-{self.layout_class}-{self.load_level}"
            f"-b{self.buffer_count}-e{self.relocation_executor_capacity}"
            f"-{self.recoverability_policy}-{self.departure_information_source}"
            f"-{self.facility_comparison_mode}-seed{self.seed}"
        )
        if self.experiment_slice == "core":
            return core_id
        cancellation = str(self.user_cancellation_probability).replace(".", "p")
        budget = (
            "none"
            if self.experiment_budget_s is None
            else str(self.experiment_budget_s).replace(".", "p")
        )
        return (
            f"{self.partition.value}-{self.experiment_slice}-{self.layout_class}"
            f"-{self.load_level}-b{self.buffer_count}"
            f"-e{self.relocation_executor_capacity}-{self.recoverability_policy}"
            f"-{self.departure_information_source}-{self.facility_comparison_mode}"
            f"-cancel{cancellation}-budget{budget}-seed{self.seed}"
        )


def formal_algorithm_ids(protocol: dict[str, Any]) -> tuple[str, ...]:
    """Return only approved online algorithms eligible for formal comparison."""

    algorithms = protocol["algorithms"]
    required_keys = ("online_rule_v1", "rolling_candidate_v1")
    missing = [key for key in required_keys if key not in algorithms]
    if missing:
        raise ValueError(f"protocol is missing formal algorithms: {missing}")
    if algorithms["online_rule_v1"]["role"] != "required_online_baseline":
        raise ValueError("online_rule_v1 no longer has its frozen baseline role")
    if algorithms["rolling_candidate_v1"]["role"] != "conditional_dynamic_candidate":
        raise ValueError("rolling_candidate_v1 no longer has its frozen candidate role")
    return tuple(ALGORITHM_ID_BY_PROTOCOL_KEY[key] for key in required_keys)


def algorithm_ids_for_unit(
    protocol: dict[str, Any],
    unit: ExperimentUnit,
) -> tuple[str, ...]:
    """Keep budget sensitivity rolling-only; all other slices use the paired algorithms."""

    if unit.experiment_slice == "budget":
        return ("rolling-candidate-v1",)
    return formal_algorithm_ids(protocol)


def core_experiment_units(protocol: dict[str, Any]) -> tuple[ExperimentUnit, ...]:
    """Expand the frozen core matrix without duplicating any matrix values."""

    from itertools import product

    matrix = protocol["core_matrix"]
    seeds = protocol["seed_sets"]["formal_core"]
    units = [
        ExperimentUnit(
            partition=SeedPartition.FORMAL_CORE,
            layout_class=str(layout_class),
            load_level=str(load_level),
            buffer_count=int(buffer_count),
            relocation_executor_capacity=int(executor_capacity),
            recoverability_policy=str(recoverability_policy),
            departure_information_source=str(departure_information_source),
            facility_comparison_mode=str(facility_mode),
            seed=int(seed),
        )
        for (
            layout_class,
            load_level,
            buffer_count,
            executor_capacity,
            recoverability_policy,
            departure_information_source,
            facility_mode,
            seed,
        ) in product(
            matrix["layout_class"],
            matrix["load_level"],
            matrix["buffer_count"],
            matrix["relocation_executor_capacity"],
            matrix["recoverability_policy"],
            matrix["departure_information_source"],
            matrix["facility_comparison_mode"],
            seeds,
        )
    ]
    for unit in units:
        validate_unit(protocol, unit)
    return tuple(units)


def development_unit(
    protocol: dict[str, Any],
    *,
    layout_class: str,
    load_level: str,
    buffer_count: int,
    seed: int,
) -> ExperimentUnit:
    """Build a development smoke unit using frozen core defaults."""

    matrix = protocol["core_matrix"]
    unit = ExperimentUnit(
        partition=SeedPartition.DEVELOPMENT,
        layout_class=layout_class,
        load_level=load_level,
        buffer_count=buffer_count,
        relocation_executor_capacity=int(matrix["relocation_executor_capacity"][0]),
        recoverability_policy=str(matrix["recoverability_policy"][0]),
        departure_information_source=str(matrix["departure_information_source"][0]),
        facility_comparison_mode=str(matrix["facility_comparison_mode"][0]),
        seed=seed,
    )
    validate_unit(protocol, unit, require_core_membership=False)
    return unit


from parking_opt.experiments.protocol_sensitivity import sensitivity_experiment_units  # noqa: E402
