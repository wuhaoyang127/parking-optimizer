"""Single-origin deployment entry: FastAPI APIs plus the built React application."""
from pathlib import Path
import sys
from fastapi import HTTPException
from fastapi.responses import FileResponse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from parking_opt.api.app import create_app
from parking_opt.api.sources import ScenarioProfile


def create_serving_app(static_root=None):
    api = create_app(scenario_profile=ScenarioProfile.PUBLIC)
    static = Path(static_root or ROOT / "apps/web/dist").resolve()

    @api.middleware("http")
    async def serving_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        return response

    @api.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "API not found")
        target = (static / path).resolve()
        if not target.is_relative_to(static):
            raise HTTPException(404, "file not found")
        if target.is_file():
            response = FileResponse(target)
            response.headers["Cache-Control"] = "public,max-age=31536000,immutable" if path.startswith("assets/") else "no-cache"
            return response
        if path and path.split("/")[0] not in ("parking", "recommend", "journey"):
            raise HTTPException(404, "page not found")
        if not (static / "index.html").is_file():
            raise HTTPException(503, "frontend build missing; run npm --prefix apps/web run build")
        return FileResponse(static / "index.html", headers={"Cache-Control": "no-cache"})

    return api


app = create_serving_app()
