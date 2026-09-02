"""auth 包网络自愈回归测试。"""

import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import auth  # noqa: E402
import auth._base as auth_base  # noqa: E402
import auth.tasks as auth_tasks  # noqa: E402


def test_is_transient_net_detects_connection_reset():
    """WinError 10053（连接被重置）与 httpx 传输错误应视为瞬时网络错误。"""
    assert auth._is_transient_net(ConnectionResetError(10053, "连接被重置"))
    assert auth._is_transient_net(httpx.RemoteProtocolError("Server disconnected"))
    assert not auth._is_transient_net(ValueError("业务参数错误"))


def test_rpc_with_retry_recovers_after_transient_error(monkeypatch):
    """瞬时网络错误时重建连接池并退避重试，最终成功。"""
    calls = []

    class FakeResponse:
        data = {"success": True, "status": "done"}

    class FlakyClient:
        def rpc(self, name, params):
            calls.append(name)
            if len(calls) == 1:
                raise httpx.RemoteProtocolError("Server disconnected")
            return FakeRequest()

    class FakeRequest:
        def execute(self):
            return FakeResponse()

    monkeypatch.setattr(auth_base, "get_supabase", lambda: FlakyClient())
    res = auth_base._rpc_with_retry("get_compute_task", {"p_token": "t"})
    assert res == {"success": True, "status": "done"}
    assert calls == ["get_compute_task", "get_compute_task"]


def test_rpc_with_retry_returns_error_for_non_transient(monkeypatch):
    """非瞬时错误按原契约返回错误 dict，不重试。"""

    class BadClient:
        def rpc(self, name, params):
            raise ValueError("boom")

    monkeypatch.setattr(auth_base, "get_supabase", lambda: BadClient())
    res = auth_base._rpc_with_retry("validate_session", {"p_token": "t"})
    assert res == {"success": False, "error": "boom"}


def test_get_latest_compute_task_calls_rpc(monkeypatch):
    """get_latest_compute_task 走只读 RPC 重试通道并原样返回。"""
    captured = {}

    def fake_rpc(name, params):
        captured["name"] = name
        captured["params"] = params
        return {"success": True, "task": {"id": "x"}}

    monkeypatch.setattr(auth_tasks, "_rpc_with_retry", fake_rpc)
    res = auth.get_latest_compute_task("tok")
    assert res == {"success": True, "task": {"id": "x"}}
    assert captured == {"name": "get_latest_compute_task", "params": {"p_token": "tok"}}


def test_delete_compute_task_calls_rpc(monkeypatch):
    """删除任务 RPC 封装：传 token 与 task_id，原样返回。"""
    captured = {}

    def fake_rpc(name, params):
        captured["name"] = name
        captured["params"] = params
        return {"success": True}

    monkeypatch.setattr(auth_tasks, "_rpc", fake_rpc)
    res = auth.delete_compute_task("tok", "task-1")
    assert res == {"success": True}
    assert captured == {"name": "delete_compute_task",
                        "params": {"p_token": "tok", "p_task_id": "task-1"}}


def test_get_latest_compute_task_any_calls_rpc(monkeypatch):
    """任意状态最近任务查询 RPC 封装：走只读重试通道并原样返回。"""
    captured = {}

    def fake_rpc(name, params):
        captured["name"] = name
        captured["params"] = params
        return {"success": True, "task": {"id": "x", "status": "running"}}

    monkeypatch.setattr(auth_tasks, "_rpc_with_retry", fake_rpc)
    res = auth.get_latest_compute_task_any("tok")
    assert res == {"success": True, "task": {"id": "x", "status": "running"}}
    assert captured == {"name": "get_latest_compute_task_any", "params": {"p_token": "tok"}}
