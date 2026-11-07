"""Strict conversion of scope-bound observations into online-only algorithm inputs."""
from datetime import timedelta
from parking_opt.api.research_inputs import VisibleObservations


def project_observations(payload, snapshot, data_mode):
    if not snapshot:
        return {"arrivals": [], "occupants": []}
    observed = VisibleObservations.model_validate(snapshot)
    now = payload["time_s"]
    age = now - observed.observed_at.timestamp()
    if not 0 <= age <= 300:
        raise ValueError("OBSERVATIONS_FUTURE_OR_STALE")
    if observed.layout_hash != payload["layout_hash"]:
        raise ValueError("OBSERVATION_LAYOUT_STATE_MISMATCH")
    if observed.source != ("synthetic" if str(data_mode) == "synthetic" else "observed"):
        raise ValueError("OBSERVATION_DATA_MODE_MISMATCH")
    occupied = {s["space_id"] for s in payload["spaces"] if s["status"] == "occupied"}
    occupants = []
    for item in observed.occupants:
        if item.space_id not in occupied:
            raise ValueError("OCCUPANT_NOT_CURRENTLY_OCCUPIED")
        duration = None
        if item.expected_departure_at is not None:
            if item.expected_departure_at.timestamp() <= now:
                raise ValueError("OCCUPANT_ESTIMATE_EXPIRED")
            duration = (item.expected_departure_at - item.arrival_at).total_seconds()
        occupants.append({"space_id": item.space_id, "arrival_s": item.arrival_at.timestamp(),
                          "duration_s": duration, "source": item.source,
                          "entrance_node_id": item.entrance_node_id})
    return {"source": observed.source, "observed_at": observed.observed_at.isoformat(),
            "arrivals": [{"event_id": a.event_id, "time_s": a.occurred_at.timestamp(),
                          "duration_s": a.expected_duration_s, "estimate_source": a.estimate_source}
                         for a in observed.arrivals], "occupants": occupants}


def validation_observations(driver, layout, costs):
    """Explicit synthetic test data only; never used as runtime missing-data defaults."""
    return {"contract": "visible-observations-1.0.0", "session_id": driver.session_id,
        "parking_lot_id": layout.parking_lot_id, "source": "synthetic",
        "observed_at": costs.observed_at.isoformat(),
        "arrivals": [{"event_id": "synthetic-arrival-" + str(i),
            "time_s": costs.observed_at.timestamp() - 1200 + i * 60} for i in range(12)],
        "occupants": [{"space_id": s.space_id, "arrival_s": costs.observed_at.timestamp() - 600,
            "duration_s": 7200, "source": "prediction", "entrance_node_id": layout.entrance_node_ids[0]}
            for s in layout.spaces if s.status.value == "occupied"]}
