"""Strict validation of experiment-protocol units against frozen slices."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from parking_opt.demand.scenario import SeedPartition, validate_seed_partition

if TYPE_CHECKING:
    from parking_opt.experiments.protocol import ExperimentUnit


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
