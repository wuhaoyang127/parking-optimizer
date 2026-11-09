"""车主端服务自动启动：前端构建、Supabase 配置传递与健康等待。"""
import os
import subprocess
import time
import tomllib
import urllib.request
from pathlib import Path

_SUPABASE_KEYS = ("SUPABASE_URL", "SUPABASE_ANON_KEY")


def _integration_root() -> Path:
    """定位包含 driver/.venv 的 parking-integrated 根目录。

    按序尝试：
    1. 环境变量 PARKING_INTEGRATION_ROOT；
    2. 从本模块向上找含 driver/.venv/Scripts/python.exe 的目录（运行时位于
       <root>/research/src/driver_bridge/）；
    3. 祖先目录下的 parking-integrated 兄弟目录（git 仓库 parking-optimizer
       与运行时 parking-integrated 并列时的场景）。
    """
    env = os.environ.get("PARKING_INTEGRATION_ROOT")
    if env:
        return Path(env)
    current = Path(__file__).resolve().parent
    candidates: list[Path] = []
    for ancestor in (current, *current.parents):
        candidates.append(ancestor)
        candidates.append(ancestor / "parking-integrated")
    for candidate in candidates:
        if (candidate / "driver" / ".venv" / "Scripts" / "python.exe").is_file():
            return candidate
    raise RuntimeError("未找到 parking-integrated 根目录，可设置 PARKING_INTEGRATION_ROOT")


def _healthy(url: str) -> bool:
    try:
        with urllib.request.urlopen(url + "/api/v2/health", timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


def _read_supabase_env(root: Path) -> dict[str, str]:
    """读取研究端 Supabase 配置：环境变量优先，回退 .streamlit/secrets.toml。"""
    env: dict[str, str] = {}
    secrets = _load_secrets_toml(root / "research" / ".streamlit" / "secrets.toml")
    for key in _SUPABASE_KEYS:
        value = os.environ.get(key) or secrets.get(key)
        if value:
            env[key] = value
    return env


def _load_secrets_toml(path: Path) -> dict[str, str]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        return {}
    supabase = data.get("supabase", {})
    return {str(k): str(v) for k, v in supabase.items() if isinstance(v, str)}


def _ensure_frontend_built(root: Path) -> None:
    """确保前端 dist 已构建；缺失时自动 npm install + build。"""
    web = root / "driver" / "apps" / "web"
    if (web / "dist" / "index.html").is_file():
        return
    if not (web / "node_modules").is_dir():
        subprocess.run(["npm", "ci", "--no-audit", "--no-fund"], cwd=str(web), check=True)
    subprocess.run(["npm", "run", "build"], cwd=str(web), check=True)


def ensure_driver_running(port: int = 8000, timeout_s: float = 60.0) -> str:
    """确保车主端（serve 同源）运行，返回车主端 URL。

    自动完成：前端构建（如缺失）、Supabase 配置传递、后台启动、健康等待。
    """
    url = f"http://127.0.0.1:{port}"
    if _healthy(url):
        return url
    root = _integration_root()
    python = root / "driver" / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        raise RuntimeError(f"未找到车主端 Python：{python}")
    _ensure_frontend_built(root)
    env = os.environ.copy()
    env.update(_read_supabase_env(root))
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        [str(python), "-m", "uvicorn", "serve:app", "--app-dir", "driver",
         "--host", "127.0.0.1", "--port", str(port), "--http", "h11"],
        cwd=str(root),
        env=env,
        creationflags=creationflags,
    )
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        time.sleep(0.5)
        if _healthy(url):
            return url
    raise RuntimeError("车主端启动超时，请检查 driver/.venv 与前端 dist 是否就绪")
