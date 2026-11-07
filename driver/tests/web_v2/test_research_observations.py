"""Expanded publication lifecycle and per-session input isolation."""
from datetime import timedelta
from pathlib import Path
import csv
import io
import json
import subprocess
import pytest
from fastapi.testclient import TestClient
from parking_opt.api.app import create_app
from parking_opt.api.sources import ScenarioProfile
from parking_opt.api.research_runtime import canonical_hash
from parking_opt.api.research_projection import project_observations
from parking_opt.api.research_inputs import VisibleObservations
from test_research_expanded import trained_model

PUB = {"Authorization": "Bearer " + "p"*40}
ADMIN = {"Authorization": "Bearer " + "a"*40}


@pytest.fixture
def live(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKING_PUBLISH_TOKEN", "p"*40)
    monkeypatch.setenv("PARKING_ADMIN_TOKEN", "a"*40)
    monkeypatch.setenv("PARKING_RELEASE_DB", str(tmp_path / "releases.db"))
    app = create_app(scenario_profile=ScenarioProfile.LEGACY)
    return TestClient(app), app


@pytest.mark.parametrize("algorithm", ["random", "duration_greedy", "risk_scoring", "peak_offpeak_fusion", "rho_rolling", "ml_duration_tree", "ml_degenerate"])
def test_expanded_release_activation_real_recommend_and_complete_trip(live, algorithm, trained_model):
    client, app = live
    degenerate = algorithm == "ml_degenerate"
    if degenerate:
        algorithm = "ml_duration_tree"
    caps = client.get("/api/research/v1/capabilities", headers=PUB).json()
    body = {"release_id": "expanded", "algorithm_id": algorithm, "source_hash": caps["source_hash"]}
    # Risk weights remain configurable; w_risk=0 is an explicit deployment choice
    # for this no-occupant-estimate fixture, not an undocumented runtime repair.
    if algorithm == "risk_scoring":
        body["params"] = {"w_risk": 0.0}
    if algorithm == "ml_duration_tree":
        body["model"] = dict(trained_model, degenerate=True) if degenerate else trained_model
    assert client.post("/api/research/v1/releases", headers=PUB, json=body).status_code == 200
    validated = client.post("/api/research/v1/releases/expanded/validate", headers=ADMIN)
    assert validated.json()["validation"]["passed"], validated.text
    client.post("/api/admin/v1/driver-algorithm-activations", headers=ADMIN, json={"release_id": "expanded"})
    bundle = app.state.data_source.get_bundle("lot-commercial")
    driver = {"request_id": "r", "idempotency_key": "i", "session_id": "expanded-session",
        "parking_lot_id": "lot-commercial", "entrance_node_id": bundle.layout.entrance_node_ids[0],
        "requested_at": bundle.cost_snapshot.observed_at.isoformat(),
        "expected_departure_at": (bundle.cost_snapshot.observed_at + timedelta(hours=2)).isoformat()}
    # Explicit synthetic occupant predictions are scoped to this one test session.
    observed = {"session_id": driver["session_id"], "parking_lot_id": driver["parking_lot_id"],
        "layout_hash": canonical_hash(bundle.layout.model_dump(mode="json")), "source": "synthetic",
        "observed_at": bundle.cost_snapshot.observed_at.isoformat(), "occupants": [
            {"space_id": s.space_id, "arrival_at": (bundle.cost_snapshot.observed_at-timedelta(minutes=10)).isoformat(),
             "known_at": bundle.cost_snapshot.observed_at.isoformat(), "source": "prediction",
             "expected_departure_at": (bundle.cost_snapshot.observed_at+timedelta(hours=1)).isoformat()}
            for s in bundle.layout.spaces if s.status.value == "occupied"]}
    assert client.post("/api/admin/v1/visible-observations", headers=ADMIN, json=observed).status_code == 200
    response = client.post("/api/v2/journeys/recommendations", json={"scenario_id": bundle.scenario_id,
        "journey_id": "expanded-trip", "attempt_id": "expanded-attempt", "idempotency_key": "hold", "driver": driver})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["recommendation"]["algorithm_id"] == "research-" + algorithm, result
    if degenerate or algorithm == "rho_rolling":
        assert result["recommendation"]["degraded"]
        assert result["recommendation"]["degradation_reason"]
    record = result["journey"]
    for action, expected in (("confirm", "session_reserved"), ("start-navigation", "navigating"),
                             ("occupy", "occupied"), ("depart", "departed")):
        command = {"expected_version": record["version"], "idempotency_key": action}
        if action == "confirm":
            command["accepted"] = True
        response = client.post(f"/api/v2/journeys/expanded-trip/{action}", json=command)
        assert response.status_code == 200, response.text
        record = response.json()
        assert record["state"] == expected
    sessions = client.get("/api/admin/v1/driver-sessions", headers=ADMIN).json()
    assert sessions[0]["session_id"] == driver["session_id"]
    response = client.get("/api/admin/v1/completed-history.csv", headers=ADMIN,
        params={"session_id": driver["session_id"], "parking_lot_id": driver["parking_lot_id"]})
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert len(rows) == 1 and rows[0]["record_id"] == "expanded-trip"
    isolated = client.get("/api/admin/v1/completed-history.csv", headers=ADMIN,
        params={"session_id": "other", "parking_lot_id": driver["parking_lot_id"]})
    assert list(csv.DictReader(io.StringIO(isolated.text))) == []


def test_observations_never_cross_session_and_stale_data_is_rejected(live):
    _, app = live
    snapshot = {"session_id": "s", "parking_lot_id": "lot", "layout_hash": "0"*64,
        "observed_at": "2026-08-01T00:00:00Z", "source": "synthetic"}
    app.state.release_store.observations("s", "lot", snapshot)
    assert app.state.release_store.observations("other", "lot") is None
    now = VisibleObservations.model_validate(snapshot).observed_at.timestamp()
    value = {"time_s": now+301, "layout_hash": "0"*64, "spaces": []}
    with pytest.raises(ValueError, match="STALE"):
        project_observations(value, snapshot, "synthetic")
    value["time_s"] = now
    value["layout_hash"] = "1"*64
    with pytest.raises(ValueError, match="LAYOUT_STATE"):
        project_observations(value, snapshot, "synthetic")
