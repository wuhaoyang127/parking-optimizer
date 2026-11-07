"""Export authoritative Pydantic v2 contracts and deterministic scenario fixtures."""

from __future__ import annotations

import json
from pathlib import Path

from parking_opt.api.discovery import export_discovery_area
from parking_opt.api.models import SCHEMA_MODELS
from parking_opt.api.scenarios import export_scenarios

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    schema_dir = REPO_ROOT / "schemas" / "v2"
    schema_dir.mkdir(parents=True, exist_ok=True)
    expected_schema_names = {f"{name}.schema.json" for name in SCHEMA_MODELS}
    for stale in schema_dir.glob("*.schema.json"):
        if stale.name not in expected_schema_names:
            stale.unlink()
    for name, model in sorted(SCHEMA_MODELS.items()):
        schema = model.model_json_schema(
            ref_template=f"https://parksim.example/schemas/v2/{name}.schema.json#/$defs/{{model}}"
        )
        schema["$id"] = f"https://parksim.example/schemas/v2/{name}.schema.json"
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        (schema_dir / f"{name}.schema.json").write_text(
            json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    scenario_dir = REPO_ROOT / "data" / "synthetic" / "web-v2"
    expected_scenario_names = {
        "commercial-demo.scenario.json",
        "hospital-demo.scenario.json",
        "school-demo.scenario.json",
        "transport-hub-demo.scenario.json",
    }
    scenario_dir.mkdir(parents=True, exist_ok=True)
    for stale in scenario_dir.glob("*.scenario.json"):
        if stale.name not in expected_scenario_names:
            stale.unlink()
    export_scenarios(scenario_dir)
    export_discovery_area(scenario_dir / "discovery-area.v1.json")


if __name__ == "__main__":
    main()
