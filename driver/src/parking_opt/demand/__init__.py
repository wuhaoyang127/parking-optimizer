"""Synthetic demand generation and exact confirmed-event replay."""

from parking_opt.demand.replay import replay_validated_events
from parking_opt.demand.scenario import (
    ScenarioGenerationResult,
    SeedPartition,
    generate_synthetic_scenario,
    load_experiment_protocol,
    validate_seed_partition,
)

__all__ = [
    "ScenarioGenerationResult",
    "SeedPartition",
    "generate_synthetic_scenario",
    "load_experiment_protocol",
    "replay_validated_events",
    "validate_seed_partition",
]
