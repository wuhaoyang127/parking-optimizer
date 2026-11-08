"""Supabase 认证客户端：标准库直调 REST RPC，不新增第三方依赖。

复用研究端账号体系（login_user / validate_session RPC），密钥仅从环境变量读取。
"""

from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _settings() -> tuple[str, str]:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_ANON_KEY", "")
    if not url or not key:
        raise RuntimeError("Supabase 未配置：请设置 SUPABASE_URL 与 SUPABASE_ANON_KEY")
    return url, key


def _rpc(name: str, params: dict) -> dict:
    url, key = _settings()
    request = Request(
        f"{url}/rest/v1/rpc/{name}",
        data=json.dumps(params).encode("utf-8"),
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=15) as response:
            data = json.load(response)
    except HTTPError as exc:
        return {"success": False, "error": exc.read(2000).decode("utf-8", "replace")}
    except (URLError, TimeoutError, OSError) as exc:
        return {"success": False, "error": str(exc)}
    if isinstance(data, dict):
        return data
    if isinstance(data, list) and data:
        return data[0] if isinstance(data[0], dict) else {"success": False, "error": "无响应"}
    return {"success": False, "error": "无响应"}


def login(username: str, password: str) -> dict:
    """登录，返回 {success, username, role, token} 或 {success: False, error}。"""
    return _rpc("login_user", {"p_username": username, "p_password": password})


def validate_session(token: str) -> dict:
    """校验会话 token，返回 {success, ...} 或 {success: False, error}。"""
    return _rpc("validate_session", {"p_token": token})
