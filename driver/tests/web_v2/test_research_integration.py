"""Actual research source execution, API administration and Journey regression."""
import subprocess
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from parking_opt.api.app import create_app
from parking_opt.api.sources import ScenarioProfile
from parking_opt.api.research_store import ReleaseStore

PUB = {"Authorization": "Bearer " + "p" * 40}
ADMIN = {"Authorization": "Bearer " + "a" * 40}
RELEASES = "/api/research/v1/releases"
ACTIVATE = "/api/admin/v1/driver-algorithm-activations"


@pytest.fixture
def connected(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKING_RELEASE_DB", str(tmp_path / "releases.db"))
    monkeypatch.setenv("PARKING_PUBLISH_TOKEN", "p" * 40)
    monkeypatch.setenv("PARKING_ADMIN_TOKEN", "a" * 40)
    app = create_app(scenario_profile=ScenarioProfile.LEGACY)
    with TestClient(app) as client:
        yield client, app


def release(client, algorithm="nearest", release_id="release-1", validate=True):
    capability = client.get("/api/research/v1/capabilities", headers=PUB).json()
    payload = {"release_id": release_id, "algorithm_id": algorithm,
               "source_hash": capability["source_hash"]}
    response = client.post(RELEASES, json=payload, headers=PUB)
    assert response.status_code == 200, response.text
    if validate:
        response = client.post(f"{RELEASES}/{release_id}/validate", headers=ADMIN)
        assert response.status_code == 200, response.text
        assert response.json()["validation"]["passed"], response.text
    return response.json()


def journey(client, suffix):
    driver = {"request_id": "req-" + suffix, "idempotency_key": "idem-" + suffix,
              "session_id": "session-" + suffix, "parking_lot_id": "lot-school",
              "entrance_node_id": "entry", "requested_at": "2026-08-13T09:00:00Z"}
    response = client.post("/api/v2/journeys/recommendations", json={
        "scenario_id": "school-demo", "journey_id": "journey-" + suffix,
        "attempt_id": "attempt-" + suffix, "idempotency_key": "hold-" + suffix,
        "driver": driver})
    assert response.status_code == 200, response.text
    return response.json(), driver


@pytest.mark.parametrize("algorithm", ["nearest", "fcfs", "greedy", "departure_greedy"])
def test_actual_source_release_to_journey_and_rollback(connected, algorithm):
    client, app = connected
    item = release(client, algorithm)
    assert client.post(ACTIVATE, headers=ADMIN, json={"release_id": "release-1"}).status_code == 200
    result, driver = journey(client, algorithm)
    rec = result["recommendation"]
    assert rec["algorithm_id"] == "research-" + algorithm
    assert rec["claim_status"] == "soft_held"
    assert rec["route"]["to_node_id"]
    record = result["journey"]
    for action, expected in (("confirm", "session_reserved"),
                             ("start-navigation", "navigating"),
                             ("occupy", "occupied"), ("depart", "departed")):
        command = {"expected_version": record["version"], "idempotency_key": action + algorithm}
        if action == "confirm":
            command["accepted"] = True
        response = client.post(f"/api/v2/journeys/{record['journey_id']}/{action}", json=command)
        assert response.status_code == 200, response.text
        record = response.json()
        assert record["state"] == expected
    assert client.post(ACTIVATE, headers=ADMIN, json={
        "release_id": None, "expected_active_hash": item["release_hash"]}).status_code == 200
    pinned = client.post("/api/v2/recommendations", json={"driver": driver}).json()
    assert pinned["algorithm_id"] == rec["algorithm_id"]
    fresh, _ = journey(client, algorithm + "-new")
    assert fresh["recommendation"]["algorithm_id"] == "online-rule-v2"
    current = client.get("/api/v2/driver-session/current-journey",
                         headers={"X-Session-ID": driver["session_id"]}).json()
    # The completed Journey still retains its original recommendation evidence.
    context = app.state.journey_service._require_context(result["journey"]["journey_id"])
    assert context.result.recommendation.algorithm_id == rec["algorithm_id"]
    records = client.get("/api/admin/v1/execution-receipts", headers=ADMIN).json()
    assert any(r.get("executed_algorithm") == rec["algorithm_id"] for r in records)


def test_auth_unvalidated_conflicting_and_unsupported(connected):
    client, app = connected
    assert client.get(RELEASES).status_code == 401
    assert client.get(ACTIVATE + "/active", headers=PUB).status_code == 401
    item = release(client, validate=False)
    assert client.post(ACTIVATE, headers=ADMIN, json={"release_id": "release-1"}).status_code == 409
    payload = {k: item[k] for k in ("release_id", "algorithm_id", "source_hash")}
    assert client.post(RELEASES, headers=PUB, json=payload).status_code == 200
    payload["algorithm_id"] = "fcfs"
    assert client.post(RELEASES, headers=PUB, json=payload).status_code == 409
    payload["algorithm_id"] = "mosa"
    assert client.post(RELEASES, headers=PUB, json=payload).status_code == 422
    payload["algorithm_id"] = "nearest"
    payload["source_hash"] = "0" * 64
    assert client.post(RELEASES, headers=PUB, json=payload).status_code == 409


@pytest.mark.parametrize("failure", [ValueError("bad candidate"), subprocess.TimeoutExpired("runner", 2)])
def test_failed_execution_has_explicit_fallback_and_receipt(connected, monkeypatch, failure):
    client, app = connected
    release(client)
    client.post(ACTIVATE, headers=ADMIN, json={"release_id": "release-1"})
    def fail(*args):
        raise failure
    monkeypatch.setattr(app.state.research_runtime, "rank", fail)
    result, _ = journey(client, "fallback")
    rec = result["recommendation"]
    assert rec["algorithm_id"] == "online-rule-v2" and rec["degraded"]
    assert rec["claim_status"] == "soft_held"
    assert app.state.release_store.audit()[0]["fallback_reason"]


def test_runtime_rejects_duplicate_unknown_missing_and_stale_outputs(connected, monkeypatch):
    _, app = connected
    runtime = app.state.research_runtime
    source_hash = runtime.describe()["source_hash"]
    payload = {"input_hash": "i", "candidates": [{"space_id": "A"}, {"space_id": "B"}]}
    for ids in (["A", "A"], ["A", "foreign"], ["A"], None):
        monkeypatch.setattr(runtime, "_run", lambda *args, ids=ids: {
            "source_hash": source_hash, "space_ids": ids, "input_hash": "i"})
        with pytest.raises(ValueError, match="INVALID_CANDIDATES"):
            runtime.rank(payload, source_hash)
    monkeypatch.setattr(runtime, "_run", lambda *args: {"source_hash": "changed"})
    with pytest.raises(ValueError, match="SOURCE_CHANGED"):
        runtime.rank(payload, source_hash)


def test_activation_is_persistent_and_compare_and_swap(connected):
    client, app = connected
    first = release(client)
    release(client, "fcfs", "release-2")
    assert client.post(ACTIVATE, headers=ADMIN, json={"release_id": "release-1"}).status_code == 200
    assert client.post(ACTIVATE, headers=ADMIN, json={"release_id": "release-2"}).status_code == 409
    assert client.post(ACTIVATE, headers=ADMIN, json={"release_id": "release-2",
        "expected_active_hash": first["release_hash"]}).status_code == 200
    import os
    reopened = ReleaseStore(Path(os.environ["PARKING_RELEASE_DB"]))
    assert reopened.active()["release_id"] == "release-2"


def test_management_boundary_size_roles_and_disabled_credentials(connected, monkeypatch):
    client, app = connected
    assert client.post(RELEASES + "/missing/validate", headers=PUB).status_code == 401
    response = client.get(RELEASES, headers=PUB)
    assert response.headers["Cache-Control"] == "no-store"
    oversized = client.post(RELEASES, headers=PUB, content=b"x" * 131073)
    assert oversized.status_code == 413
    monkeypatch.delenv("PARKING_PUBLISH_TOKEN")
    assert client.get(RELEASES, headers=PUB).status_code == 503
