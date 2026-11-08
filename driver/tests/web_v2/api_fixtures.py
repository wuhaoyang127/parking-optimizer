from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from parking_opt.api.app import create_app as _create_app
from parking_opt.api.models import DataMode
from parking_opt.api.sources import ScenarioProfile

REPO_ROOT = Path(__file__).resolve().parents[2]


def create_app(*, data_mode: DataMode = DataMode.SYNTHETIC) -> FastAPI:
    profile = ScenarioProfile.LEGACY if data_mode is DataMode.SYNTHETIC else None
    return _create_app(data_mode=data_mode, scenario_profile=profile)


def _journey_payload(*, suffix: str, namespace: str = "driver") -> dict[str, object]:
    return {
        "schema_version": "2.0.0",
        "namespace": namespace,
        "scenario_id": "school-demo",
        "journey_id": f"journey-{suffix}",
        "attempt_id": f"attempt-{suffix}",
        "algorithm_id": "online-rule-v2",
        "idempotency_key": f"recommend-{suffix}",
        "driver": {
            "schema_version": "2.0.0",
            "request_id": f"request-{suffix}",
            "idempotency_key": f"driver-{suffix}",
            "session_id": f"session-{suffix}",
            "parking_lot_id": "lot-school",
            "entrance_node_id": "entry",
            "requires_charging": False,
            "requested_at": "2026-08-13T09:00:00Z",
            "expected_departure_at": None,
        },
    }
