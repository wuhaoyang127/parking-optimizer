"""Advanced-mode authentication routes (Supabase account shared with research app)."""

from __future__ import annotations

import time
from threading import Lock

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from parking_opt.api import auth_supabase


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class SessionRequest(BaseModel):
    token: str = Field(min_length=1)


# 登录失败限流：同一用户名 5 次失败 / 5 分钟窗口内 → 429（防暴力破解）
_MAX_LOGIN_FAILS = 5
_LOGIN_WINDOW_S = 300.0
_login_fails: dict[str, list[float]] = {}
_login_lock = Lock()


def _login_blocked(username: str) -> bool:
    with _login_lock:
        now = time.time()
        recent = [t for t in _login_fails.get(username, ()) if now - t < _LOGIN_WINDOW_S]
        _login_fails[username] = recent
        return len(recent) >= _MAX_LOGIN_FAILS


def _login_failed(username: str) -> None:
    with _login_lock:
        _login_fails.setdefault(username, []).append(time.time())


def register_auth_routes(app: FastAPI) -> None:
    @app.post("/api/v2/auth/login", tags=["auth"])
    def login(payload: LoginRequest, request: Request) -> dict:
        if _login_blocked(payload.username):
            raise HTTPException(status_code=429, detail="尝试次数过多，请稍后再试")
        try:
            result = auth_supabase.login(payload.username, payload.password)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if not result.get("success"):
            _login_failed(payload.username)
            raise HTTPException(status_code=401, detail=result.get("error", "登录失败"))
        return result

    @app.post("/api/v2/auth/session", tags=["auth"])
    def validate(payload: SessionRequest) -> dict:
        try:
            result = auth_supabase.validate_session(payload.token)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if not result.get("success"):
            raise HTTPException(status_code=401, detail=result.get("error", "会话无效"))
        return result
