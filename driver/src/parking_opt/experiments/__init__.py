"""Configuration-driven experiment execution and paired reporting."""

from parking_opt.experiments.protocol import ExperimentUnit, core_experiment_units
from parking_opt.experiments.statistics import (
    DescriptiveSummary,
    PairedBootstrapSummary,
    descriptive_summary,
    paired_bootstrap_summary,
)

__all__ = [
    "DescriptiveSummary",
    "ExperimentUnit",
    "PairedBootstrapSummary",
    "core_experiment_units",
    "descriptive_summary",
    "paired_bootstrap_summary",
]
