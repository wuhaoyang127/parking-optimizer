"""车主端服务自动启动与健康等待（研究端「打开车主端」一键启动）。"""
import os
import subprocess
import time
import urllib.request
from pathlib import Path


def _integration_root() -> Path:
    """定位包含 driver/.venv 的 parking-integrated 根目录。

    优先读环境变量 PARKING_INTEGRATION_ROOT；否则从本模块向上找含
    driver/.venv/Scripts/python.exe 的目录（研究端运行时位于
    <root>/research/src/driver_bridge/）。
    """
    env = os.environ.get("PARKING_INTEGRATION_ROOT")
    if env:
        return Path(env)
    current = Path(__file__).resolve().parent
    for candidate in (current, *current.parents):
        if (candidate / "driver" / ".venv" / "Scripts" / "python.exe").is_file():
            return candidate
    raise RuntimeError("未找到 parking-integrated 根目录，可设置 PARKING_INTEGRATION_ROOT")


def _healthy(url: str) -> bool:
    try:
        with urllib.request.urlopen(url + "/api/v2/health", timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


def ensure_driver_running(port: int = 8000, timeout_s: float = 20.0) -> str:
    """确保车主端（serve 同源）运行，返回车主端 URL。"""
    url = f"http://127.0.0.1:{port}"
    if _healthy(url):
        return url
    root = _integration_root()
    python = root / "driver" / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        raise RuntimeError(f"未找到车主端 Python：{python}")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        [str(python), "-m", "uvicorn", "serve:app", "--app-dir", "driver",
         "--host", "127.0.0.1", "--port", str(port), "--http", "h11"],
        cwd=str(root),
        creationflags=creationflags,
    )
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        time.sleep(0.5)
        if _healthy(url):
            return url
    raise RuntimeError("车主端启动超时，请检查 driver/.venv 与前端 dist 是否就绪")
