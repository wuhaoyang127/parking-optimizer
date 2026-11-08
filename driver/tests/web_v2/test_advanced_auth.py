"""Advanced-mode authentication route regression (Supabase shared account)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from parking_opt.api.app import create_app
from parking_opt.api.sources import ScenarioProfile


@pytest.fixture
def client():
    app = create_app(scenario_profile=ScenarioProfile.LEGACY)
    with TestClient(app) as test_client:
        yield test_client


def test_login_success_returns_account(client, monkeypatch):
    monkeypatch.setattr(
        "parking_opt.api.auth_supabase.login",
        lambda u, p: {"success": True, "username": u, "role": "admin", "token": "t"},
    )
    response = client.post("/api/v2/auth/login", json={"username": "u", "password": "p"})
    assert response.status_code == 200
    assert response.json()["role"] == "admin"


def test_login_failure_is_401(client, monkeypatch):
    monkeypatch.setattr(
        "parking_opt.api.auth_supabase.login",
        lambda u, p: {"success": False, "error": "bad password"},
    )
    response = client.post("/api/v2/auth/login", json={"username": "u", "password": "x"})
    assert response.status_code == 401


def test_login_missing_config_is_503(client, monkeypatch):
    def raise_config(*args, **kwargs):
        raise RuntimeError("Supabase 未配置")

    monkeypatch.setattr("parking_opt.api.auth_supabase.login", raise_config)
    response = client.post("/api/v2/auth/login", json={"username": "u", "password": "p"})
    assert response.status_code == 503


def test_session_validation(client, monkeypatch):
    monkeypatch.setattr(
        "parking_opt.api.auth_supabase.validate_session",
        lambda t: {"success": True, "username": "u", "role": "admin"},
    )
    response = client.post("/api/v2/auth/session", json={"token": "t"})
    assert response.status_code == 200
    assert response.json()["username"] == "u"


def test_session_invalid_is_401(client, monkeypatch):
    monkeypatch.setattr(
        "parking_opt.api.auth_supabase.validate_session",
        lambda t: {"success": False, "error": "expired"},
    )
    response = client.post("/api/v2/auth/session", json={"token": "bad"})
    assert response.status_code == 401


def test_advanced_status_requires_session(client):
    response = client.get("/api/v2/advanced/status")
    assert response.status_code == 401


def test_advanced_status_returns_algorithm_and_trial(client, monkeypatch):
    monkeypatch.setattr(
        "parking_opt.api.auth_supabase.validate_session",
        lambda t: {"success": True, "username": "u", "role": "admin"},
    )
    response = client.get("/api/v2/advanced/status", headers={"Authorization": "Bearer t"})
    assert response.status_code == 200
    body = response.json()
    assert body["account"]["username"] == "u"
    assert "trial_stats" in body
    assert "recent_receipts" in body


def _minimal_layout() -> dict:
    return {
        "schema_version": "2.0.0",
        "parking_lot_id": "lot-adv",
        "layout_version": "v1",
        "coordinate_origin_note": "origin",
        "entrance_node_ids": ["entry"],
        "exit_node_ids": ["exit"],
        "nodes": [
            {"node_id": "entry", "kind": "entrance", "coordinate": {"x_m": 0.0, "y_m": 0.0}, "label": "入口"},
            {"node_id": "exit", "kind": "exit", "coordinate": {"x_m": 10.0, "y_m": 0.0}, "label": "出口"},
            {"node_id": "access", "kind": "space_access", "coordinate": {"x_m": 5.0, "y_m": 0.0}, "label": "车位入口"},
        ],
        "edges": [
            {"edge_id": "e1", "from_node_id": "entry", "to_node_id": "access", "distance_m": 5.0, "base_travel_time_s": 5.0, "channel_zone_ids": []},
            {"edge_id": "e2", "from_node_id": "access", "to_node_id": "exit", "distance_m": 5.0, "base_travel_time_s": 5.0, "channel_zone_ids": []},
        ],
        "channel_zones": [],
        "spaces": [
            {"space_id": "A", "parking_lot_id": "lot-adv", "access_node_id": "access",
             "coordinate": {"x_m": 5.0, "y_m": 1.0}, "status": "available",
             "stack_group_id": "g1", "depth": 1, "assignable": True},
        ],
    }


def test_import_layout_validates_and_lists(client, monkeypatch):
    monkeypatch.setattr(
        "parking_opt.api.auth_supabase.validate_session",
        lambda t: {"success": True, "username": "u", "role": "admin"},
    )
    headers = {"Authorization": "Bearer t"}
    assert client.get("/api/v2/advanced/layouts", headers=headers).status_code == 200
    response = client.post("/api/v2/advanced/layouts", json=_minimal_layout(), headers=headers)
    assert response.status_code == 200
    assert response.json()["parking_lot_id"] == "lot-adv"
    listed = client.get("/api/v2/advanced/layouts", headers=headers).json()
    assert any(item["parking_lot_id"] == "lot-adv" for item in listed)


def test_import_layout_rejects_invalid(client, monkeypatch):
    monkeypatch.setattr(
        "parking_opt.api.auth_supabase.validate_session",
        lambda t: {"success": True, "username": "u", "role": "admin"},
    )
    headers = {"Authorization": "Bearer t"}
    bad = _minimal_layout()
    bad["spaces"][0]["access_node_id"] = "missing"
    response = client.post("/api/v2/advanced/layouts", json=bad, headers=headers)
    assert response.status_code == 422


def test_compare_returns_trial_and_baseline_metrics(client, monkeypatch):
    monkeypatch.setattr(
        "parking_opt.api.auth_supabase.validate_session",
        lambda t: {"success": True, "username": "u", "role": "admin"},
    )
    headers = {"Authorization": "Bearer t"}
    response = client.get("/api/v2/advanced/compare", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["baseline_algorithm"] == "online-rule-v2"
    assert "trial_metrics" in body
    assert "baseline_metrics" in body
