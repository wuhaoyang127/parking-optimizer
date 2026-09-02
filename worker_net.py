"""worker 网络层：Supabase 配置读取、自愈 RPC 客户端、凭据管理。"""
import json
import os
import re
import time
from pathlib import Path

from supabase import create_client
import httpx

ROOT = Path(__file__).resolve().parent


def _is_transient_net(e: Exception) -> bool:
    """网络瞬时错误（连接被重置/超时/断连，如 WinError 10053）。"""
    if isinstance(e, httpx.HTTPError):
        return True
    return isinstance(e, (ConnectionError, TimeoutError, OSError))


class _SupabaseClient:
    """带网络抖动自愈的 Supabase RPC 客户端。

    公网到 Supabase 的连接可能被代理/负载均衡器重置（常见 WinError 10053：
    软件中断了已建立的连接）。RPC 调用遇到瞬时网络错误时自动退避重试，
    并重建底层连接池，避免「循环异常 10053」刷屏或任务卡住。
    """

    def __init__(self, url: str, key: str):
        self.url = url
        self.key = key
        self.client = create_client(url, key)

    def rpc(self, name: str, params: dict, *, tries: int = 4, backoff: float = 1.5):
        for i in range(tries):
            try:
                return self.client.rpc(name, params).execute()
            except Exception as e:
                if not _is_transient_net(e) or i == tries - 1:
                    raise
                print(f"[!] 网络抖动（{type(e).__name__}），{backoff:.0f}s 后重试"
                      f"（{i + 1}/{tries - 1}）…")
                time.sleep(backoff)
                backoff *= 1.5
                try:
                    self.client = create_client(self.url, self.key)
                except Exception:
                    pass


def _read_secret(key: str) -> str:
    val = os.environ.get(key)
    if val:
        return val
    # 操作员本地计算包：与 local_worker.py 同级的 worker_config.toml
    cfg_path = ROOT / "worker_config.toml"
    if not cfg_path.exists():
        cfg_path = ROOT / ".streamlit" / "secrets.toml"
    try:
        text = cfg_path.read_text(encoding="utf-8")
        m = re.search(rf'^{key}\s*=\s*"([^"]+)"\s*$', text, re.M)
        if m:
            return m.group(1)
    except Exception:
        pass
    return ""


def _load_cached_credentials():
    """读取本地缓存的 worker 登录凭据（交互登录成功后写入）。"""
    p = ROOT / "worker_credentials.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return str(data.get("username", "") or ""), str(data.get("password", "") or "")
    except Exception:
        return "", ""


def _save_cached_credentials(username: str, password: str):
    """交互登录成功后缓存凭据，下次免输入。"""
    try:
        (ROOT / "worker_credentials.json").write_text(
            json.dumps({"username": username, "password": password}, ensure_ascii=False),
            encoding="utf-8")
    except Exception:
        pass


def _prompt_credentials():
    """交互式询问账号密码（双击启动无命令行参数时）。"""
    print("首次使用：请输入你在停车场 App 里的账号密码（操作员/管理员均可）。")
    username = input("用户名：").strip()
    password = input("密码：").strip()
    return username, password


def _read_credentials(username: str, password: str):
    if username and password:
        return username, password
    cred_path = ROOT / "credentials.local.txt"
    try:
        text = cred_path.read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("#") or ":" not in line:
                continue
            k, v = line.split(":", 1)
            if k.strip() == "username":
                username = v.strip()
            elif k.strip() == "password":
                password = v.strip()
    except Exception:
        pass
    if username and password:
        return username, password
    username, password = _load_cached_credentials()
    if username and password:
        return username, password
    return _prompt_credentials()
