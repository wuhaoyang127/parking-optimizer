"""Advanced-mode authentication routes (Supabase account shared with research app)."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from parking_opt.api import auth_supabase


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class SessionRequest(BaseModel):
    token: str = Field(min_length=1)


def register_auth_routes(app: FastAPI) -> None:
    @app.post("/api/v2/auth/login", tags=["auth"])
    def login(payload: LoginRequest) -> dict:
        try:
            result = auth_supabase.login(payload.username, payload.password)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if not result.get("success"):
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
