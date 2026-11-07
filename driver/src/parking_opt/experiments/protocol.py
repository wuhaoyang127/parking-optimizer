"""Strict projections of the approved stage-B experiment protocol."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Any

from parking_opt.demand.scenario import SeedPartition, validate_seed_partition

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


def sensitivity_experiment_units(protocol: dict[str, Any]) -> tuple[ExperimentUnit, ...]:
    """Expand every approved formal-extension sensitivity slice deterministically."""

    slices = protocol["sensitivity_slices"]
    seeds = tuple(int(seed) for seed in protocol["seed_sets"]["formal_extension"])
    default_layout_class = "mixed_depth"
    default_buffer_count = 1
    default_executor_capacity = 1
    default_recoverability_policy = "risk_accepting"
    default_departure_source = "unknown"
    default_facility_mode = "fixed_total_positions"
    units: list[ExperimentUnit] = []

    def add(
        slice_name: str,
        *,
        layout_classes: tuple[str, ...] = (default_layout_class,),
        load_levels: tuple[str, ...],
        buffer_counts: tuple[int, ...] = (default_buffer_count,),
        executor_capacities: tuple[int, ...] = (default_executor_capacity,),
        recoverability_policies: tuple[str, ...] = (default_recoverability_policy,),
        departure_sources: tuple[str, ...] = (default_departure_source,),
        facility_modes: tuple[str, ...] = (default_facility_mode,),
        cancellation_probabilities: tuple[float, ...] = (0.0,),
        budgets: tuple[float | None, ...] = (None,),
    ) -> None:
        for values in product(
            layout_classes,
            load_levels,
            buffer_counts,
            executor_capacities,
            recoverability_policies,
            departure_sources,
            facility_modes,
            cancellation_probabilities,
            budgets,
            seeds,
        ):
            (
                layout_class,
                load_level,
                buffer_count,
                executor_capacity,
                recoverability_policy,
                departure_source,
                facility_mode,
                cancellation_probability,
                budget,
                seed,
            ) = values
            units.append(
                ExperimentUnit(
                    partition=SeedPartition.FORMAL_EXTENSION,
                    layout_class=str(layout_class),
                    load_level=str(load_level),
                    buffer_count=int(buffer_count),
                    relocation_executor_capacity=int(executor_capacity),
                    recoverability_policy=str(recoverability_policy),
                    departure_information_source=str(departure_source),
                    facility_comparison_mode=str(facility_mode),
                    seed=int(seed),
                    experiment_slice=slice_name,
                    user_cancellation_probability=float(cancellation_probability),
                    experiment_budget_s=None if budget is None else float(budget),
                )
            )

    recoverability = slices["recoverability"]
    add(
        "recoverability",
        load_levels=tuple(recoverability["load_level"]),
        buffer_counts=tuple(recoverability["buffer_count"]),
        executor_capacities=tuple(recoverability["relocation_executor_capacity"]),
        recoverability_policies=tuple(recoverability["recoverability_policy"]),
    )
    executor = slices["executor_capacity"]
    add(
        "executor_capacity",
        load_levels=tuple(executor["load_level"]),
        buffer_counts=tuple(executor["buffer_count"]),
        executor_capacities=tuple(executor["relocation_executor_capacity"]),
        recoverability_policies=tuple(executor["recoverability_policy"]),
    )
    independent = slices["independent_reference"]
    add(
        "independent_reference",
        layout_classes=tuple(independent["layout_class"]),
        load_levels=tuple(independent["load_level"]),
        buffer_counts=tuple(independent["buffer_count"]),
    )
    extra = slices["extra_buffer_space"]
    add(
        "extra_buffer_space",
        layout_classes=tuple(extra["layout_class"]),
        load_levels=tuple(extra["load_level"]),
        buffer_counts=tuple(extra["buffer_count"]),
        facility_modes=tuple(extra["facility_comparison_mode"]),
    )
    soft = slices["soft_information"]
    add(
        "soft_information",
        load_levels=tuple(soft["load_level"]),
        buffer_counts=tuple(soft["buffer_count"]),
        departure_sources=tuple(soft["departure_information_source"]),
    )
    cancellation = slices["cancellation_robustness"]
    add(
        "cancellation_robustness",
        load_levels=tuple(cancellation["load_level"]),
        buffer_counts=tuple(cancellation["buffer_count"]),
        executor_capacities=tuple(cancellation["relocation_executor_capacity"]),
        recoverability_policies=tuple(cancellation["recoverability_policy"]),
        cancellation_probabilities=tuple(cancellation["user_cancellation_probability"]),
    )
    add(
        "budget",
        load_levels=("medium", "high"),
        budgets=tuple(float(value) for value in protocol["time"]["budget_sensitivity_s"]),
    )
    for unit in units:
        validate_unit(protocol, unit, require_core_membership=False)
    if len({unit.unit_id for unit in units}) != len(units):
        raise ValueError("formal-extension sensitivity unit IDs are not unique")
    return tuple(units)


def validate_unit(
    protocol: dict[str, Any],
    unit: ExperimentUnit,
    *,
    require_core_membership: bool = True,
) -> None:
    """Reject seed contamination or values outside the approved matrix."""

    validate_seed_partition(protocol, unit.seed, unit.partition)
    matrix = protocol["core_matrix"]
    fields = {
        "layout_class": unit.layout_class,
        "load_level": unit.load_level,
        "buffer_count": unit.buffer_count,
        "relocation_executor_capacity": unit.relocation_executor_capacity,
        "recoverability_policy": unit.recoverability_policy,
        "departure_information_source": unit.departure_information_source,
        "facility_comparison_mode": unit.facility_comparison_mode,
    }
    if require_core_membership:
        outside = [name for name, value in fields.items() if value not in matrix[name]]
        if outside:
            raise ValueError(f"unit values are outside the frozen core matrix: {outside}")
    else:
        if unit.layout_class not in {"independent", "mixed_depth"}:
            raise ValueError("development layout class is invalid")
        if unit.load_level not in protocol["synthetic_demand"]["offered_load_ratio"]:
            raise ValueError("development load level is invalid")
        if unit.buffer_count not in {0, 1, 2}:
            raise ValueError("development buffer count is invalid")
    if unit.partition is not SeedPartition.FORMAL_EXTENSION:
        if unit.departure_information_source != "unknown":
            raise ValueError("core/development runner does not accept soft information")
        if unit.facility_comparison_mode != "fixed_total_positions":
            raise ValueError("core/development runner requires fixed_total_positions")
        if unit.experiment_slice != "core":
            raise ValueError("core/development units must use experiment_slice=core")
        if unit.user_cancellation_probability != 0.0 or unit.experiment_budget_s is not None:
            raise ValueError("core/development units cannot carry sensitivity values")
        return
    if unit.experiment_slice not in {
        "recoverability",
        "executor_capacity",
        "independent_reference",
        "extra_buffer_space",
        "soft_information",
        "cancellation_robustness",
        "budget",
    }:
        raise ValueError("unknown formal-extension sensitivity slice")
    if unit.departure_information_source not in {
        "unknown",
        "reservation",
        "user_estimate",
        "model_prediction",
    }:
        raise ValueError("invalid formal-extension departure information source")
    if unit.facility_comparison_mode not in {
        "fixed_total_positions",
        "extra_buffer_space",
    }:
        raise ValueError("invalid formal-extension facility mode")
    if unit.user_cancellation_probability not in {0.0, 0.05}:
        raise ValueError("invalid formal-extension cancellation probability")
    if unit.experiment_slice == "budget":
        if unit.experiment_budget_s not in {
            float(value) for value in protocol["time"]["budget_sensitivity_s"]
        }:
            raise ValueError("budget slice value is not frozen")
    elif unit.experiment_budget_s is not None:
        raise ValueError("only the budget slice may set experiment_budget_s")
    fixed_defaults = (
        unit.layout_class == "mixed_depth"
        and unit.relocation_executor_capacity == 1
        and unit.recoverability_policy == "risk_accepting"
        and unit.departure_information_source == "unknown"
        and unit.facility_comparison_mode == "fixed_total_positions"
        and unit.user_cancellation_probability == 0.0
    )
    slice_config = protocol["sensitivity_slices"]
    valid = False
    if unit.experiment_slice == "recoverability":
        spec = slice_config["recoverability"]
        valid = (
            unit.layout_class == "mixed_depth"
            and unit.load_level in spec["load_level"]
            and unit.buffer_count in spec["buffer_count"]
            and unit.relocation_executor_capacity in spec["relocation_executor_capacity"]
            and unit.recoverability_policy in spec["recoverability_policy"]
            and unit.departure_information_source == "unknown"
            and unit.facility_comparison_mode == "fixed_total_positions"
            and unit.user_cancellation_probability == 0.0
        )
    elif unit.experiment_slice == "executor_capacity":
        spec = slice_config["executor_capacity"]
        valid = (
            unit.layout_class == "mixed_depth"
            and unit.load_level in spec["load_level"]
            and unit.buffer_count in spec["buffer_count"]
            and unit.relocation_executor_capacity in spec["relocation_executor_capacity"]
            and unit.recoverability_policy in spec["recoverability_policy"]
            and unit.departure_information_source == "unknown"
            and unit.facility_comparison_mode == "fixed_total_positions"
            and unit.user_cancellation_probability == 0.0
        )
    elif unit.experiment_slice == "independent_reference":
        spec = slice_config["independent_reference"]
        valid = (
            unit.layout_class in spec["layout_class"]
            and unit.load_level in spec["load_level"]
            and unit.buffer_count in spec["buffer_count"]
            and unit.relocation_executor_capacity == 1
            and unit.recoverability_policy == "risk_accepting"
            and unit.departure_information_source == "unknown"
            and unit.facility_comparison_mode == "fixed_total_positions"
            and unit.user_cancellation_probability == 0.0
        )
    elif unit.experiment_slice == "extra_buffer_space":
        spec = slice_config["extra_buffer_space"]
        valid = (
            unit.layout_class in spec["layout_class"]
            and unit.load_level in spec["load_level"]
            and unit.buffer_count in spec["buffer_count"]
            and unit.facility_comparison_mode in spec["facility_comparison_mode"]
            and unit.relocation_executor_capacity == 1
            and unit.recoverability_policy == "risk_accepting"
            and unit.departure_information_source == "unknown"
            and unit.user_cancellation_probability == 0.0
        )
    elif unit.experiment_slice == "soft_information":
        spec = slice_config["soft_information"]
        valid = (
            unit.layout_class == "mixed_depth"
            and unit.load_level in spec["load_level"]
            and unit.buffer_count in spec["buffer_count"]
            and unit.departure_information_source in spec["departure_information_source"]
            and unit.relocation_executor_capacity == 1
            and unit.recoverability_policy == "risk_accepting"
            and unit.facility_comparison_mode == "fixed_total_positions"
            and unit.user_cancellation_probability == 0.0
        )
    elif unit.experiment_slice == "cancellation_robustness":
        spec = slice_config["cancellation_robustness"]
        valid = (
            unit.layout_class == "mixed_depth"
            and unit.load_level in spec["load_level"]
            and unit.buffer_count in spec["buffer_count"]
            and unit.relocation_executor_capacity in spec["relocation_executor_capacity"]
            and unit.recoverability_policy in spec["recoverability_policy"]
            and unit.user_cancellation_probability in spec["user_cancellation_probability"]
            and unit.departure_information_source == "unknown"
            and unit.facility_comparison_mode == "fixed_total_positions"
        )
    elif unit.experiment_slice == "budget":
        valid = fixed_defaults and unit.load_level in {"medium", "high"} and unit.buffer_count == 1
    if not valid:
        raise ValueError(f"unit values are outside the frozen {unit.experiment_slice} slice")
