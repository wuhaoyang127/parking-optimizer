"""local_worker 回归测试。

覆盖：
1. Windows GBK（cp936）stdout 下打印 Unicode 符号不崩溃；
2. 网络瞬时错误（WinError 10053 类）识别与 RPC 退避重试自愈。
"""

import os
import subprocess
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import local_worker  # noqa: E402
import worker_net  # noqa: E402


def test_local_worker_unicode_print_survives_gbk_stdout():
    """在 GBK stdout 下导入 local_worker 并打印 ✓，进程不得崩溃。"""
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "import local_worker\n"
        "print('✓ ok')\n"
    )
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "gbk"
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="gbk",
        timeout=60,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "ok" in proc.stdout


def test_is_transient_net_detects_connection_reset():
    """WinError 10053（连接被重置）与 httpx 传输错误应视为瞬时网络错误。"""
    assert worker_net._is_transient_net(ConnectionResetError(10053, "连接被重置"))
    assert worker_net._is_transient_net(httpx.RemoteProtocolError("Server disconnected"))
    assert not worker_net._is_transient_net(ValueError("业务参数错误"))


def test_supabase_client_rpc_retries_transient_then_succeeds(monkeypatch):
    """瞬时网络错误发生时重建客户端并退避重试，最终成功。"""
    calls = []

    class FakeResponse:
        data = {"success": True}

    class FlakyClient:
        def rpc(self, name, params):
            calls.append(name)
            if len(calls) == 1:
                raise httpx.RemoteProtocolError("Server disconnected")
            return FakeRequest()

    class GoodClient:
        def rpc(self, name, params):
            calls.append(name)
            return FakeRequest()

    class FakeRequest:
        def execute(self):
            return FakeResponse()

    monkeypatch.setattr(worker_net, "create_client", lambda url, key: GoodClient())
    holder = worker_net._SupabaseClient.__new__(worker_net._SupabaseClient)
    holder.url = "https://example.supabase.co"
    holder.key = "x" * 32
    holder.client = FlakyClient()

    res = holder.rpc("claim_compute_task", {"p_token": "t"})
    assert res.data == {"success": True}
    assert calls == ["claim_compute_task", "claim_compute_task"]


def test_worker_cached_credentials_roundtrip(monkeypatch, tmp_path):
    """交互登录成功后凭据缓存到 worker_credentials.json，下次免输入。"""
    monkeypatch.setattr(worker_net, "ROOT", tmp_path)
    assert worker_net._load_cached_credentials() == ("", "")
    worker_net._save_cached_credentials("op1", "pw1")
    assert worker_net._load_cached_credentials() == ("op1", "pw1")


def test_local_compute_has_no_ui_deps():
    """操作员包只需精简依赖：local_compute 不得 import Streamlit/Pandas/Plotly。"""
    pkg = ROOT / "src" / "local_compute"
    src = "\n".join(p.read_text(encoding="utf-8") for p in pkg.rglob("*.py"))
    for bad in ("streamlit", "pandas", "plotly"):
        assert bad not in src
