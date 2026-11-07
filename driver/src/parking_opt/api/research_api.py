"""Server-authenticated publish/validate/activate APIs separate from driver sessions."""
import os
import secrets
from datetime import datetime, UTC, timedelta
from pathlib import Path
from time import monotonic
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from parking_opt.api.research_models import ResearchRelease, DriverActivation, TrialStartRequest, TrialDecision, TrialRatioUpdate
from parking_opt.api.research_runtime import ResearchRuntime, canonical_hash
from parking_opt.api.research_store import ReleaseStore
from parking_opt.api.research_dispatch import ResearchDispatcher
from parking_opt.api.models import DriverRequest
from parking_opt.api.research_inputs import VisibleObservations
from parking_opt.api.research_projection import validation_observations


def connect_research(app, baseline, routes, repo_root):
    root = Path(os.environ.get("PARKING_RESEARCH_ROOT", str(repo_root.parent / "research")))
    store = ReleaseStore(Path(os.environ.get("PARKING_RELEASE_DB",
                                             str(repo_root / "runtime" / "releases.sqlite3"))))
    runtime = ResearchRuntime(root, os.environ.get("PARKING_RESEARCH_PYTHON"))
    dispatcher = ResearchDispatcher(baseline, routes, runtime, store)
    router = APIRouter(tags=["research integration"])

    @app.middleware("http")
    async def research_boundary(request, call_next):
        protected = request.url.path.startswith(("/api/research/", "/api/admin/"))
        if protected and len(await request.body()) > 131072:
            return JSONResponse({"detail": "integration request too large"}, status_code=413)
        response = await call_next(request)
        if protected:
            response.headers["Cache-Control"] = "no-store"
        return response

    def authorize(authorization, env):
        token = os.environ.get(env, "")
        if len(token) < 32:
            raise HTTPException(503, "integration credential is not configured (minimum 32 chars)")
        if not authorization or not secrets.compare_digest(
            authorization.encode("utf-8"), ("Bearer " + token).encode("utf-8")
        ):
            raise HTTPException(401, "invalid integration credential")

    def publisher(authorization: str | None = Header(default=None)):
        authorize(authorization, "PARKING_PUBLISH_TOKEN")

    def admin(authorization: str | None = Header(default=None)):
        authorize(authorization, "PARKING_ADMIN_TOKEN")

    @router.get("/api/research/v1/capabilities", dependencies=[Depends(publisher)])
    def capabilities():
        try:
            return runtime.describe()
        except Exception as exc:
            raise HTTPException(503, "research runtime unavailable") from exc

    @router.post("/api/research/v1/releases", dependencies=[Depends(publisher)])
    def publish(payload: ResearchRelease):
        try:
            if runtime.describe()["source_hash"] != payload.source_hash:
                raise ValueError("research source hash does not match installed source")
            runtime.check_release(payload.model_dump(mode="json"))
            return store.publish(payload)
        except Exception as exc:
            raise HTTPException(409, str(exc)[:200]) from exc

    @router.get("/api/research/v1/releases", dependencies=[Depends(publisher)])
    def releases():
        return store.list()

    @router.post("/api/research/v1/releases/{release_id}/validate", dependencies=[Depends(admin)])
    def validate(release_id: str):
        from parking_opt.api.scenarios import built_in_scenarios
        release = store.get(release_id)
        if not release:
            raise HTTPException(404, "release not found")
        checks = []
        for name, bundle in built_in_scenarios().items():
            for charging in (False, True):
                start = monotonic()
                try:
                    driver = DriverRequest(request_id="validation", idempotency_key="validation",
                        session_id="validation", parking_lot_id=bundle.layout.parking_lot_id,
                        entrance_node_id=bundle.layout.entrance_node_ids[0], requires_charging=charging,
                        requested_at=bundle.cost_snapshot.observed_at,
                        expected_departure_at=bundle.cost_snapshot.observed_at + timedelta(hours=2))
                    base = baseline.recommend(driver, bundle.layout, bundle.cost_snapshot,
                                              bundle.parking_lot.data_source)
                    payload = dispatcher.payload(release, driver, bundle.layout,
                                                 bundle.cost_snapshot, base)
                    payload["observations"] = validation_observations(driver, bundle.layout, bundle.cost_snapshot)
                    payload["input_hash"] = canonical_hash({k: v for k, v in payload.items() if k != "input_hash"})
                    first = runtime.rank(payload, release["source_hash"])
                    assert first == runtime.rank(payload, release["source_hash"])
                    checks.append({"fixture": name, "charging": charging, "passed": True,
                                   "input_hash": payload["input_hash"], "count": len(first),
                                   "elapsed_ms": round((monotonic()-start)*1000, 3)})
                except Exception as exc:
                    checks.append({"fixture": name, "charging": charging, "passed": False,
                                   "error": type(exc).__name__ + ":" + str(exc)[:160]})
        evidence = {"validator": "visible-candidates-1.0.0", "checked_at": datetime.now(UTC).isoformat(),
                    "passed": bool(checks) and all(c["passed"] for c in checks), "checks": checks,
                    "scope": "synthetic fixture compatibility; not production certification"}
        return store.validated(release_id, evidence)

    @router.get("/api/admin/v1/driver-algorithm-activations/active", dependencies=[Depends(admin)])
    def active():
        return {"active": store.active(), "fallback": "online-rule-v2"}

    @router.post("/api/admin/v1/driver-algorithm-activations", dependencies=[Depends(admin)])
    def activate(payload: DriverActivation):
        try:
            if payload.release_id:
                release = store.get(payload.release_id)
                if not release or runtime.describe()["source_hash"] != release["source_hash"]:
                    raise ValueError("source unavailable or changed; validate a new release")
            return {"active": store.activate(payload), "fallback": "online-rule-v2"}
        except Exception as exc:
            raise HTTPException(409, str(exc)[:200]) from exc

    @router.get("/api/admin/v1/algorithms/current", dependencies=[Depends(admin)])
    def current():
        return store.current()

    @router.post("/api/admin/v1/trials/start", dependencies=[Depends(admin)])
    def start_trial(payload: TrialStartRequest):
        try:
            return store.start_trial(payload.release_id, payload.ratio, payload.research_score)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/api/admin/v1/trials/stop", dependencies=[Depends(admin)])
    def stop_trial():
        try:
            return store.stop_trial()
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/api/admin/v1/trials/ratio", dependencies=[Depends(admin)])
    def trial_ratio(payload: TrialRatioUpdate):
        try:
            return store.set_trial_ratio(payload.ratio)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/api/admin/v1/trials/decide", dependencies=[Depends(admin)])
    def decide(payload: TrialDecision):
        try:
            return store.decide(payload.release_id, payload.decision)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get("/api/admin/v1/backups", dependencies=[Depends(admin)])
    def backups():
        return store.backups()

    @router.post("/api/admin/v1/backups/restore", dependencies=[Depends(admin)])
    def restore_backup(payload: TrialDecision):
        try:
            return store.restore_backup(payload.release_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/api/admin/v1/backups/delete", dependencies=[Depends(admin)])
    def delete_backup(payload: TrialDecision):
        try:
            return store.delete_backup(payload.release_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get("/api/admin/v1/execution-receipts", dependencies=[Depends(admin)])
    def receipts():
        return store.audit()

    @router.post("/api/admin/v1/visible-observations", dependencies=[Depends(admin)])
    def save_observations(payload: VisibleObservations):
        try:
            value = payload.model_dump(mode="json")
            value["observed_at"] = payload.observed_at.astimezone(UTC).isoformat()
            store.observations(payload.session_id, payload.parking_lot_id, value)
            store.audit({"kind": "observation_import", "session_id": payload.session_id,
                         "parking_lot_id": payload.parking_lot_id,
                         "input_hash": canonical_hash(value), "source": payload.source})
            return {"saved": True, "input_hash": canonical_hash(value)}
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get("/api/admin/v1/visible-observations", dependencies=[Depends(admin)])
    def observations(session_id: str, parking_lot_id: str):
        return store.observations(session_id, parking_lot_id)

    from parking_opt.api.research_observed_context import install_observed_context, session_observations
    install_observed_context(router, app, admin)
    dispatcher.observation_provider = lambda driver, layout, costs: session_observations(app, driver, layout, costs)

    app.include_router(router)
    app.state.release_store = store
    app.state.research_runtime = runtime
    return dispatcher
