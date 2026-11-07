"""Scoped server observations and completed request-history export for research."""
import csv
import io
from fastapi import Depends, HTTPException
from fastapi.responses import Response
from parking_opt.api.research_runtime import canonical_hash
from parking_opt.api.sessions import SessionNamespace


def session_observations(app, driver, layout, costs):
    now = costs.observed_at.timestamp()
    occupied = {s.space_id for s in layout.spaces if s.status.value == "occupied"}
    arrivals, occupants = [], []
    pairs = app.state.journey_service.visible_driver_inputs(driver.session_id)
    for request, record in pairs:
        if record.parking_lot_id != layout.parking_lot_id:
            continue
        t = record.created_at.timestamp()
        if 0 <= now-t <= 86400 and request.request_id != driver.request_id:
            duration = ((request.expected_departure_at-request.requested_at).total_seconds()
                        if request.expected_departure_at else None)
            arrivals.append({"event_id": record.journey_id, "time_s": t,
                             "duration_s": duration, "estimate_source": "user_estimate" if duration else "unknown"})
        if record.state.value == "occupied" and record.space_id in occupied:
            expected = request.expected_departure_at
            duration = (expected.timestamp()-t) if expected and expected.timestamp() > now else None
            occupants.append({"space_id": record.space_id, "arrival_s": t,
                "duration_s": duration, "source": "user_estimate" if duration else "unknown",
                "entrance_node_id": request.entrance_node_id})
    return {"arrivals": sorted(arrivals, key=lambda e: e["time_s"])[-256:],
            "occupants": occupants, "history_source": "driver_request_events"}


def install_observed_context(router, app, admin):
    @router.get("/api/admin/v1/driver-sessions", dependencies=[Depends(admin)])
    def sessions():
        store = app.state.session_store
        found = {}
        for event in reversed(store.events()[-1000:]):
            record = store.get_journey(event.journey_id)
            if record and record.namespace is SessionNamespace.DRIVER:
                key = (record.session_id, record.parking_lot_id)
                found.setdefault(key, {"session_id": record.session_id,
                    "parking_lot_id": record.parking_lot_id, "state": record.state.value})
            if len(found) >= 100:
                break
        return list(found.values())

    @router.get("/api/admin/v1/completed-history.csv", dependencies=[Depends(admin)])
    def history(session_id: str, parking_lot_id: str):
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["record_id", "arrival_at", "departed_at", "entrance_node_id"])
        writer.writeheader()
        for request, record in app.state.journey_service.visible_driver_inputs(session_id):
            if record.parking_lot_id == parking_lot_id and record.state.value == "departed":
                writer.writerow({"record_id": record.journey_id, "arrival_at": record.created_at.isoformat(),
                    "departed_at": record.updated_at.isoformat(), "entrance_node_id": request.entrance_node_id})
        return Response(output.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="completed-history.csv"'})

    @router.get("/api/admin/v1/driver-input-context", dependencies=[Depends(admin)])
    def input_context(session_id: str, parking_lot_id: str):
        from parking_opt.api.models import DriverRequest
        from datetime import timedelta
        try:
            source = app.state.data_source
            bundle = (source.get_driver_bundle(parking_lot_id, session_id=session_id)
                      if hasattr(source, "get_driver_bundle") else source.get_bundle(parking_lot_id))
        except Exception as exc:
            raise HTTPException(503, "driver source unavailable") from exc
        driver = DriverRequest(request_id="context-preview", idempotency_key="context-preview",
            session_id=session_id, parking_lot_id=parking_lot_id,
            entrance_node_id=bundle.layout.entrance_node_ids[0], requested_at=bundle.cost_snapshot.observed_at)
        observed = session_observations(app, driver, bundle.layout, bundle.cost_snapshot)
        return {"session_id": session_id, "parking_lot_id": parking_lot_id,
            "layout_hash": canonical_hash(bundle.layout.model_dump(mode="json")),
            "observed_at": bundle.cost_snapshot.observed_at.isoformat(),
            "data_source": bundle.parking_lot.data_source.model_dump(mode="json"),
            "occupied_space_ids": [s.space_id for s in bundle.layout.spaces if s.status.value == "occupied"],
            "visible_inputs": observed,
            "note": "来源为本会话已发生的停车请求；不代表真实车辆传感器观测"}
