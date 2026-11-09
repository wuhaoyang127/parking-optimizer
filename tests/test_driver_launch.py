"""车主端一键启动（launch）纯逻辑测试（不依赖 Streamlit）。"""

from __future__ import annotations

from driver_bridge.launch import _healthy, _integration_root, _load_secrets_toml


def test_integration_root_honors_env(monkeypatch):
    monkeypatch.setenv("PARKING_INTEGRATION_ROOT", "D:/罚函数/停车场/parking-integrated")
    root = _integration_root()
    assert root.name == "parking-integrated"
    assert (root / "driver" / ".venv" / "Scripts" / "python.exe").is_file()


def test_integration_root_discovers_sibling(monkeypatch):
    monkeypatch.delenv("PARKING_INTEGRATION_ROOT", raising=False)
    assert _integration_root().name == "parking-integrated"


def test_healthy_detects_unreachable_port():
    assert _healthy("http://127.0.0.1:1") is False


def test_load_secrets_toml_reads_supabase(tmp_path):
    secrets = tmp_path / "secrets.toml"
    secrets.write_text(
        '[supabase]\nSUPABASE_URL = "https://example.supabase.co"\nSUPABASE_ANON_KEY = "anon"\n',
        encoding="utf-8",
    )
    loaded = _load_secrets_toml(secrets)
    assert loaded == {"SUPABASE_URL": "https://example.supabase.co", "SUPABASE_ANON_KEY": "anon"}


def test_load_secrets_toml_missing_returns_empty(tmp_path):
    assert _load_secrets_toml(tmp_path / "missing.toml") == {}
