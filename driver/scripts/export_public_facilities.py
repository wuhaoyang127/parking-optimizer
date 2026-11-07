"""Export deterministic M4 public facility resources without touching legacy fixtures."""

from __future__ import annotations

import json
from pathlib import Path

from parking_opt.api.facility_scenarios import build_public_facility_scenarios

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    output_dir = REPO_ROOT / "data" / "synthetic" / "web-v2-public"
    output_dir.mkdir(parents=True, exist_ok=True)
    expected: set[str] = set()
    for scenario in build_public_facility_scenarios().values():
        stem = scenario.base_state.scenario_id
        resources = {
            f"{stem}.facility-layout.json": scenario.layout,
            f"{stem}.facility-state.json": scenario.base_state,
            f"{stem}.scenario.json": scenario.bundle,
        }
        expected.update(resources)
        for name, model in resources.items():
            (output_dir / name).write_text(
                json.dumps(model.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    for stale in output_dir.glob("*.json"):
        if stale.name not in expected:
            stale.unlink()


if __name__ == "__main__":
    main()
