"""Frozen descriptive and paired-bootstrap statistics using the standard library."""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class DescriptiveSummary:
    """Frozen descriptive fields for one finite numeric sample."""

    n: int
    mean: float
    standard_deviation: float
    median: float
    q1: float
    q3: float
    iqr: float

    def to_mapping(self) -> dict[str, int | float]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PairedBootstrapSummary:
    """Candidate-minus-baseline paired differences and percentile interval."""

    descriptive: DescriptiveSummary
    confidence_level: float
    bootstrap_resamples: int
    bootstrap_seed: int
    ci_lower: float
    ci_upper: float
    relative_difference_mean: float | None

    def to_mapping(self) -> dict[str, Any]:
        value = asdict(self)
        value["descriptive"] = self.descriptive.to_mapping()
        return value


def _quantile(sorted_values: Sequence[float], probability: float) -> float:
    if not sorted_values:
        raise ValueError("a quantile requires at least one value")
    if not 0 <= probability <= 1:
        raise ValueError("probability must be in [0,1]")
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    index = (len(sorted_values) - 1) * probability
    lower = math.floor(index)
    upper = math.ceil(index)
    fraction = index - lower
    return float(sorted_values[lower] * (1 - fraction) + sorted_values[upper] * fraction)


def descriptive_summary(values: Sequence[float]) -> DescriptiveSummary:
    """Return n, mean, sample SD, median and linear-interpolated IQR."""

    if not values:
        raise ValueError("descriptive statistics require at least one value")
    finite = [float(value) for value in values]
    if any(not math.isfinite(value) for value in finite):
        raise ValueError("statistics do not accept non-finite values")
    ordered = sorted(finite)
    q1 = _quantile(ordered, 0.25)
    q3 = _quantile(ordered, 0.75)
    return DescriptiveSummary(
        n=len(ordered),
        mean=statistics.fmean(ordered),
        standard_deviation=statistics.stdev(ordered) if len(ordered) > 1 else 0.0,
        median=statistics.median(ordered),
        q1=q1,
        q3=q3,
        iqr=q3 - q1,
    )


def paired_bootstrap_summary(
    baseline: Sequence[float],
    candidate: Sequence[float],
    *,
    resamples: int,
    confidence_level: float,
    seed: int,
) -> PairedBootstrapSummary:
    """Bootstrap candidate-minus-baseline means with fixed paired indices."""

    if len(baseline) != len(candidate) or not baseline:
        raise ValueError("paired samples must be non-empty and equal length")
    if resamples < 1:
        raise ValueError("bootstrap resamples must be positive")
    if not 0 < confidence_level < 1:
        raise ValueError("confidence level must be in (0,1)")
    differences = [
        float(candidate_value) - float(baseline_value)
        for baseline_value, candidate_value in zip(baseline, candidate, strict=True)
    ]
    descriptive = descriptive_summary(differences)
    rng = random.Random(seed)
    n = len(differences)
    boot_means = sorted(
        statistics.fmean(differences[rng.randrange(n)] for _ in range(n)) for _ in range(resamples)
    )
    alpha = 1 - confidence_level
    baseline_mean = statistics.fmean(float(value) for value in baseline)
    relative = descriptive.mean / baseline_mean if baseline_mean != 0 else None
    return PairedBootstrapSummary(
        descriptive=descriptive,
        confidence_level=confidence_level,
        bootstrap_resamples=resamples,
        bootstrap_seed=seed,
        ci_lower=_quantile(boot_means, alpha / 2),
        ci_upper=_quantile(boot_means, 1 - alpha / 2),
        relative_difference_mean=relative,
    )
