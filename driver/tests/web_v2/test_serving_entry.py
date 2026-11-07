"""Same-origin deploy entry must never turn missing API calls into SPA success."""
from pathlib import Path
import importlib.util
from fastapi.testclient import TestClient


def test_same_origin_spa_api_and_traversal_boundaries(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKING_RELEASE_DB", str(tmp_path / "releases.db"))
    source = Path(__file__).resolve().parents[2] / "serve.py"
    spec = importlib.util.spec_from_file_location("parking_serving_test", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    static = tmp_path / "dist"
    static.mkdir()
    (static / "index.html").write_text("<h1>Parking integration</h1>")
    with TestClient(module.create_serving_app(static)) as client:
        assert client.get("/").status_code == 200
        assert client.get("/journey").status_code == 200
        assert client.get("/api/v2/health").json()["status"] == "ok"
        assert client.get("/api/does-not-exist").status_code == 404
        assert client.get("/assets/missing.js").status_code == 404
        assert client.get("/%2e%2e/secrets.toml").status_code == 404
        assert client.get("/").headers["X-Content-Type-Options"] == "nosniff"
