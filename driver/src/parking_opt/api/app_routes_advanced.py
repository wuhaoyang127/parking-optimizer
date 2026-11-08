"""Advanced-mode read/write endpoints authenticated by the shared Supabase account."""

from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException
from pydantic import ValidationError

from parking_opt.api import auth_supabase
from parking_opt.api.models_layout import Layout


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


def _advanced_layouts(app: FastAPI) -> dict:
    store = getattr(app.state, "advanced_layouts", None)
    if store is None:
        store = {}
        app.state.advanced_layouts = store
    return store


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

    @app.get("/api/v2/advanced/layouts", tags=["advanced"])
    def list_layouts(authorization: str | None = Header(default=None)) -> list[dict]:
        _account(authorization)
        return [
            {"parking_lot_id": lot_id, "layout_version": layout.layout_version,
             "spaces": len(layout.spaces), "buffers": len(layout.buffers)}
            for lot_id, layout in _advanced_layouts(app).items()
        ]

    @app.post("/api/v2/advanced/layouts", tags=["advanced"])
    def import_layout(payload: dict, authorization: str | None = Header(default=None)) -> dict:
        _account(authorization)
        try:
            layout = Layout.model_validate(payload)
        except ValidationError as exc:
            first = exc.errors()[0] if exc.errors() else {}
            detail = first.get("msg", "invalid layout")
            raise HTTPException(status_code=422, detail=detail) from exc
        _advanced_layouts(app)[layout.parking_lot_id] = layout
        return {"saved": True, "parking_lot_id": layout.parking_lot_id,
                "layout_version": layout.layout_version, "spaces": len(layout.spaces)}

