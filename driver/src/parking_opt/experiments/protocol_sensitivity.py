"""Formal-extension sensitivity slice expansion for the experiment protocol."""

from __future__ import annotations

from itertools import product
from typing import Any

from parking_opt.demand.scenario import SeedPartition
from parking_opt.experiments.protocol import ExperimentUnit
from parking_opt.experiments.protocol_validation import validate_unit


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
