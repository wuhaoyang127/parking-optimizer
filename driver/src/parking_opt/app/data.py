"""Read-only loading of committed synthetic D2 demonstration bundles."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from parking_opt.app.design import ScreenshotState
from parking_opt.application.data_adaptation import (
    AdaptationPolicy,
    DataAdaptationReport,
    validate_data_source,
)
from parking_opt.application.presentation import (
    ComparisonEvidenceView,
    ImportPolicy,
    ValidatedDemoBundle,
    load_comparison_evidence,
    load_demo_bundle,
)

_FIXTURE_ROOT = Path("data") / "synthetic" / "fixtures" / "d2"
_REPLAY_FIXTURE_ROOT = Path("data") / "synthetic" / "fixtures" / "d3"
_EVIDENCE_FIXTURE_ROOT = Path("data") / "synthetic" / "fixtures" / "d4"
_ADAPTATION_FIXTURE_ROOT = Path("data") / "synthetic" / "fixtures" / "d5"


@dataclass(frozen=True, slots=True)
class DemoCatalog:
    """Two validated topologies used by the six D2 visual-reference states."""

    independent: ValidatedDemoBundle
    mixed_depth: ValidatedDemoBundle

    def for_state(self, state: ScreenshotState) -> ValidatedDemoBundle:
        """Select a topology without exposing filesystem paths to the page."""

        if state is ScreenshotState.INDEPENDENT_NORMAL:
            return self.independent
        return self.mixed_depth


def load_builtin_catalog(repository_root: Path) -> DemoCatalog:
    """Strictly validate and load the committed synthetic bundles through D1."""

    root = repository_root.resolve(strict=True)
    fixture_root = (root / _FIXTURE_ROOT).resolve(strict=True)
    schema_dir = (root / "schemas" / "v1").resolve(strict=True)
    policy = ImportPolicy(
        allowed_root=fixture_root,
        schema_dir=schema_dir,
        max_file_bytes=4 * 1024 * 1024,
        max_total_bytes=16 * 1024 * 1024,
        max_records=10_000,
    )
    return DemoCatalog(
        independent=load_demo_bundle(fixture_root / "independent-b0", policy=policy),
        mixed_depth=load_demo_bundle(fixture_root / "mixed-b1", policy=policy),
    )


def load_builtin_replay(repository_root: Path) -> ValidatedDemoBundle:
    """Strictly load the committed large synthetic replay through the D1 boundary."""

    root = repository_root.resolve(strict=True)
    fixture_root = (root / _REPLAY_FIXTURE_ROOT).resolve(strict=True)
    policy = ImportPolicy(
        allowed_root=fixture_root,
        schema_dir=(root / "schemas" / "v1").resolve(strict=True),
        max_file_bytes=8 * 1024 * 1024,
        max_total_bytes=24 * 1024 * 1024,
        max_records=25_000,
    )
    return load_demo_bundle(fixture_root / "mixed-b1-replay", policy=policy)


def load_stress_replay(repository_root: Path) -> ValidatedDemoBundle:
    """Load the committed 1,606-event pressure fixture outside the UI startup path."""

    root = repository_root.resolve(strict=True)
    fixture_root = (root / _REPLAY_FIXTURE_ROOT).resolve(strict=True)
    policy = ImportPolicy(
        allowed_root=fixture_root,
        schema_dir=(root / "schemas" / "v1").resolve(strict=True),
        max_file_bytes=8 * 1024 * 1024,
        max_total_bytes=24 * 1024 * 1024,
        max_records=25_000,
    )
    return load_demo_bundle(fixture_root / "large-c3-pressure", policy=policy)


def load_builtin_evidence(repository_root: Path) -> ComparisonEvidenceView:
    """Verify and load the committed synthetic C6 formal-evidence projection."""

    root = repository_root.resolve(strict=True)
    fixture_root = (root / _EVIDENCE_FIXTURE_ROOT).resolve(strict=True)
    return load_comparison_evidence(
        fixture_root / "formal-core-seed3101",
        allowed_root=fixture_root,
    )


def load_builtin_adaptation_report(repository_root: Path) -> DataAdaptationReport:
    """Validate the committed anonymous synthetic source without writing a migration copy."""

    root = repository_root.resolve(strict=True)
    fixture_root = (root / _ADAPTATION_FIXTURE_ROOT).resolve(strict=True)
    policy = AdaptationPolicy(
        input_root=fixture_root,
        output_root=(root / "data" / "interim").resolve(strict=True),
        schema_dir=(root / "schemas" / "v1").resolve(strict=True),
        max_file_bytes=2 * 1024 * 1024,
        max_total_bytes=8 * 1024 * 1024,
        max_records=10_000,
    )
    return validate_data_source(fixture_root / "anonymous-tiny", policy=policy)
