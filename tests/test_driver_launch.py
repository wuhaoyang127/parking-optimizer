"""车主端一键启动（launch）纯逻辑测试（不依赖 Streamlit）。"""

from __future__ import annotations

from driver_bridge.launch import _healthy, _integration_root


def test_integration_root_honors_env(monkeypatch):
    monkeypatch.setenv("PARKING_INTEGRATION_ROOT", "D:/罚函数/停车场/parking-integrated")
    root = _integration_root()
    assert root.name == "parking-integrated"
    assert (root / "driver" / ".venv" / "Scripts" / "python.exe").is_file()


def test_healthy_detects_unreachable_port():
    assert _healthy("http://127.0.0.1:1") is False
