"""RunManifest construction and validated JSON writing."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from parking_opt.contracts.canonical import canonical_json_bytes
from parking_opt.contracts.schema_validation import SchemaCatalog

_LICENSES = {
    "jsonschema": "MIT",
    "referencing": "MIT",
    "networkx": "BSD-3-Clause",
    "matplotlib": "PSF-based",
}


def _package_record(name: str) -> dict[str, str] | None:
    try:
        installed = version(name)
    except PackageNotFoundError:
        return None
    return {"name": name, "version": installed, "license": _LICENSES[name]}


def git_identity(repo_root: Path) -> tuple[str, bool]:
    """Return the exact commit and dirty flag without changing Git state."""

    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return commit, bool(status.strip())


def build_run_manifest(
    *,
    repo_root: Path,
    run_id: str,
    scenario_id: str,
    algorithm_id: str,
    algorithm_version: str,
    config_sha256: str,
    input_data_sha256: str,
    random_seed: int | None,
    started_at: str,
    ended_at: str,
    command: str,
    run_status: str,
) -> dict[str, Any]:
    """Build a complete no-solver C3 run manifest."""

    commit, dirty = git_identity(repo_root)
    dependencies = [
        record
        for name in ("jsonschema", "referencing", "networkx", "matplotlib")
        if (record := _package_record(name)) is not None
    ]
    return {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "scenario_id": scenario_id,
        "algorithm_id": algorithm_id,
        "algorithm_version": algorithm_version,
        "git_commit": commit,
        "git_dirty": dirty,
        "config_sha256": config_sha256,
        "input_data_sha256": input_data_sha256,
        "random_seed": random_seed,
        "started_at": started_at,
        "ended_at": ended_at,
        "python_version": platform.python_version(),
        "dependencies": dependencies,
        "solver": {"name": None, "version": None},
        "operating_system": platform.platform(),
        "hardware_summary": (
            f"{platform.machine()} {platform.processor() or 'processor-unknown'}; "
            f"logical-cpus={os.cpu_count() or 'unknown'}; Python {sys.version_info.major}."
            f"{sys.version_info.minor}.{sys.version_info.micro}"
        ),
        "command": command,
        "run_status": run_status,
    }


def write_run_manifest(
    path: Path,
    manifest: dict[str, Any],
    *,
    schema_catalog: SchemaCatalog,
) -> None:
    """Validate and write one canonical UTF-8 manifest."""

    schema_catalog.validate("run-manifest.schema.json", manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(manifest) + b"\n")
