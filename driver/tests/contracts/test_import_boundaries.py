"""Approved stage boundaries must not leak truth or third-party objects."""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "src" / "parking_opt"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
    return names


def test_domain_layer_has_no_third_party_or_downstream_imports() -> None:
    for path in (PACKAGE_ROOT / "domain").glob("*.py"):
        for imported in _imports(path):
            assert not imported.startswith(
                (
                    "jsonschema",
                    "networkx",
                    "ortools",
                    "parking_opt.contracts",
                    "parking_opt.demand",
                    "parking_opt.simulation",
                    "simpy",
                )
            )


def test_contract_layer_has_no_simulator_or_optimizer_imports() -> None:
    for path in (PACKAGE_ROOT / "contracts").glob("*.py"):
        for imported in _imports(path):
            assert not imported.startswith(
                (
                    "networkx",
                    "ortools",
                    "parking_opt.optimization",
                    "parking_opt.simulation",
                    "simpy",
                )
            )


def test_networkx_is_confined_to_the_path_cost_adapter() -> None:
    importers = {
        path.relative_to(PACKAGE_ROOT).as_posix()
        for path in PACKAGE_ROOT.rglob("*.py")
        if any(name == "networkx" or name.startswith("networkx.") for name in _imports(path))
    }
    assert importers == {"layout/networkx_adapter.py"}


def test_unenabled_simpy_and_ortools_are_not_imported() -> None:
    for path in PACKAGE_ROOT.rglob("*.py"):
        assert not any(name.startswith(("ortools", "simpy")) for name in _imports(path))


def test_strategies_cannot_import_truth_simulation_or_graph_internals() -> None:
    for path in (PACKAGE_ROOT / "strategies").glob("*.py"):
        for imported in _imports(path):
            assert not imported.startswith(
                (
                    "networkx",
                    "parking_opt.demand",
                    "parking_opt.optimization",
                    "parking_opt.simulation",
                    "simpy",
                )
            )


def test_optimization_is_offline_and_cannot_import_runtime_truth() -> None:
    for path in (PACKAGE_ROOT / "optimization").glob("*.py"):
        for imported in _imports(path):
            assert not imported.startswith(
                (
                    "networkx",
                    "parking_opt.demand",
                    "parking_opt.simulation",
                    "simpy",
                )
            )


def test_c4_did_not_create_c5_or_later_stage_packages() -> None:
    forbidden = {
        "network",
        "policies",
    }
    assert not forbidden & {path.name for path in PACKAGE_ROOT.iterdir() if path.is_dir()}
