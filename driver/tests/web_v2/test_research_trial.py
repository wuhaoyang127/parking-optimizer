"""Trial-ratio dispatch, trial receipt, and promote/discard regression."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from parking_opt.api.app import create_app
from parking_opt.api.research_dispatch import ResearchDispatcher
from parking_opt.api.sources import ScenarioProfile

PUB = {"Authorization": "Bearer " + "p" * 40}
ADMIN = {"Authorization": "Bearer " + "a" * 40}


@pytest.fixture
def connected(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKING_RELEASE_DB", str(tmp_path / "releases.db"))
    monkeypatch.setenv("PARKING_PUBLISH_TOKEN", "p" * 40)
    monkeypatch.setenv("PARKING_ADMIN_TOKEN", "a" * 40)
    app = create_app(scenario_profile=ScenarioProfile.LEGACY)
    with TestClient(app) as client:
        yield client, app


def _release(client, algorithm="nearest", release_id="release-1"):
    caps = client.get("/api/research/v1/capabilities", headers=PUB).json()
    body = {"release_id": release_id, "algorithm_id": algorithm, "source_hash": caps["source_hash"]}
    assert client.post("/api/research/v1/releases", json=body, headers=PUB).status_code == 200
    assert client.post(f"/api/research/v1/releases/{release_id}/validate", headers=ADMIN).status_code == 200


def _journey(client, suffix):
    driver = {"request_id": "req-" + suffix, "idempotency_key": "idem-" + suffix,
              "session_id": "session-" + suffix, "parking_lot_id": "lot-school",
              "entrance_node_id": "entry", "requested_at": "2026-08-13T09:00:00Z"}
    response = client.post("/api/v2/journeys/recommendations", json={
        "scenario_id": "school-demo", "journey_id": "journey-" + suffix,
        "attempt_id": "attempt-" + suffix, "idempotency_key": "hold-" + suffix,
        "driver": driver})
    assert response.status_code == 200, response.text
    return response.json(), driver


def test_trial_ratio_one_dispatches_all_and_records_receipt(connected):
    client, app = connected
    _release(client)
    started = client.post("/api/admin/v1/trials/start", headers=ADMIN, json={
        "release_id": "release-1", "ratio": 1.0, "research_score": 80.0})
    assert started.status_code == 200, started.text
    result, _ = _journey(client, "trial-full")
    assert result["recommendation"]["algorithm_id"] == "research-nearest"
    receipt = next(r for r in app.state.release_store.audit() if r["kind"] == "execution")
    assert receipt["dispatched_to_trial"] is True
    assert receipt["trial_ratio"] == 1.0
    assert receipt["research_score"] == 80.0
    assert receipt["executed_algorithm"] == "research-nearest"


def test_trial_stop_falls_back_and_decide_promotes(connected):
    client, app = connected
    _release(client)
    client.post("/api/admin/v1/trials/start", headers=ADMIN, json={
        "release_id": "release-1", "ratio": 1.0, "research_score": 80.0})
    running, _ = _journey(client, "trial-running")
    assert running["recommendation"]["algorithm_id"] == "research-nearest"
    assert client.post("/api/admin/v1/trials/stop", headers=ADMIN).status_code == 200
    stopped, _ = _journey(client, "trial-stopped")
    assert stopped["recommendation"]["algorithm_id"] == "online-rule-v2"
    assert client.post("/api/admin/v1/trials/decide", headers=ADMIN, json={
        "release_id": "release-1", "decision": "promote"}).status_code == 200
    promoted, _ = _journey(client, "trial-promoted")
    assert promoted["recommendation"]["algorithm_id"] == "research-nearest"


def test_trial_discard_does_not_activate(connected):
    client, app = connected
    _release(client)
    client.post("/api/admin/v1/trials/start", headers=ADMIN, json={
        "release_id": "release-1", "ratio": 1.0, "research_score": 80.0})
    client.post("/api/admin/v1/trials/stop", headers=ADMIN)
    assert client.post("/api/admin/v1/trials/decide", headers=ADMIN, json={
        "release_id": "release-1", "decision": "discard"}).status_code == 200
    result, _ = _journey(client, "trial-discarded")
    assert result["recommendation"]["algorithm_id"] == "online-rule-v2"
    assert app.state.release_store.active() is None


def test_trial_selected_is_deterministic_and_bounded():
    trial = {"trial_ratio": 0.5}
    picked = sum(ResearchDispatcher._trial_selected(trial, f"req-{i}") for i in range(1000))
    assert 400 <= picked <= 600
    assert ResearchDispatcher._trial_selected({"trial_ratio": 1.0}, "any") is True
    assert ResearchDispatcher._trial_selected({"trial_ratio": 0.0}, "any") is False
    assert ResearchDispatcher._trial_selected({}, "any") is True


def test_trial_failure_falls_back_with_receipt(connected, monkeypatch):
    client, app = connected
    _release(client)
    client.post("/api/admin/v1/trials/start", headers=ADMIN, json={
        "release_id": "release-1", "ratio": 1.0, "research_score": 80.0})

    def fail(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(app.state.research_runtime, "rank", fail)
    result, _ = _journey(client, "trial-fallback")
    assert result["recommendation"]["algorithm_id"] == "online-rule-v2"
    assert result["recommendation"]["degraded"]
    receipt = next(r for r in app.state.release_store.audit() if r["kind"] == "execution")
    assert receipt["dispatched_to_trial"] is True
    assert receipt["executed_algorithm"] == "online-rule-v2"
    assert "boom" in receipt["fallback_reason"]


def test_trial_stats_summarizes_dispatch(connected):
    client, app = connected
    _release(client)
    client.post("/api/admin/v1/trials/start", headers=ADMIN, json={
        "release_id": "release-1", "ratio": 1.0, "research_score": 80.0})
    _journey(client, "trial-stats")
    stats = app.state.release_store.trial_stats()
    assert stats["trial_request_count"] == 1
    assert stats["trial_success_count"] == 1
    assert stats["trial_fallback_count"] == 0
    current = client.get("/api/admin/v1/algorithms/current", headers=ADMIN).json()
    assert current["trial_stats"]["trial_request_count"] == 1
