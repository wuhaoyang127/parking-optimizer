"""Export a deterministic OpenAPI snapshot for the web-v2 API."""

from __future__ import annotations

import json
from pathlib import Path

from parking_opt.api.app import create_app
from parking_opt.api.sources import ScenarioProfile

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    path = REPO_ROOT / "schemas" / "v2" / "openapi.json"
    path.write_text(
        json.dumps(
            create_app(scenario_profile=ScenarioProfile.LEGACY).openapi(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
