from __future__ import annotations

import hashlib
from pathlib import Path

from jsonschema import Draft202012Validator

from parking_opt.api.models import SCHEMA_MODELS, DataMode, ScenarioBundle
from parking_opt.api.scenarios import SCENARIO_IDS, built_in_scenarios, load_scenarios

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_all_v2_schemas_are_valid_draft_2020_12() -> None:
    for model in SCHEMA_MODELS.values():
        Draft202012Validator.check_schema(model.model_json_schema())


def test_exported_schema_files_match_registered_contracts() -> None:
    schema_dir = REPO_ROOT / "schemas" / "v2"
    exported = {path.name for path in schema_dir.glob("*.schema.json")}
    expected = {f"{name}.schema.json" for name in SCHEMA_MODELS}
    assert exported == expected


def test_four_synthetic_scenarios_are_complete_and_deterministic() -> None:
    loaded = load_scenarios(REPO_ROOT / "data" / "synthetic" / "web-v2")
    built = built_in_scenarios()
    assert tuple(sorted(loaded)) == tuple(sorted(SCENARIO_IDS))
    assert loaded == built
    for bundle in loaded.values():
        assert bundle.parking_lot.synthetic is True
        assert bundle.parking_lot.data_source.mode is DataMode.SYNTHETIC
        assert bundle.parking_lot.total_spaces == 8
        assert len(bundle.layout.tandem_groups) == 2
        assert len(bundle.layout.buffers) == 1
        ScenarioBundle.model_validate_json(bundle.model_dump_json())


def test_v1_readonly_hash_baseline_is_unchanged() -> None:
    baseline = REPO_ROOT / "docs" / "architecture" / "web-v2" / "m2-v1-readonly-baseline.sha256"
    for line in baseline.read_text(encoding="utf-8").splitlines():
        expected, relative_path = line.split(maxsplit=1)
        actual = hashlib.sha256((REPO_ROOT / relative_path).read_bytes()).hexdigest()
        assert actual == expected.lower(), relative_path
