"""Advanced-mode read endpoints authenticated by the shared Supabase account."""

from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException

from parking_opt.api import auth_supabase


def _account(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少登录凭证")
    token = authorization.removeprefix("Bearer ")
    try:
        result = auth_supabase.validate_session(token)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not result.get("success"):
        raise HTTPException(status_code=401, detail=result.get("error", "会话无效"))
    return result


def register_advanced_routes(app: FastAPI) -> None:
    @app.get("/api/v2/advanced/status", tags=["advanced"])
    def status(authorization: str | None = Header(default=None)) -> dict:
        account = _account(authorization)
        store = app.state.release_store
        current = store.current()
        receipts = [r for r in store.audit() if r.get("kind") == "execution"][:20]
        return {
            "account": {"username": account.get("username"), "role": account.get("role")},
            "active": current.get("active"),
            "trial": current.get("trial"),
            "trial_stats": current.get("trial_stats"),
            "recent_receipts": receipts,
        }
