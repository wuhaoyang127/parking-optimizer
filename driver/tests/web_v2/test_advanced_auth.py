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
