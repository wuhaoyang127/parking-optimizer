"""All reviewed online strategies against immutable, as-of visible projections."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import random
import sys
import types
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "driver_bridge"))
from catalog import SUPPORTED, catalog, validate_params


def source_hash():
    digest = hashlib.sha256()
    paths = list((ROOT / "src" / "parking_opt").rglob("*.py"))
    paths += list((ROOT / "driver_bridge").glob("*.py"))
    for path in sorted(paths):
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def rank(payload):
    from loaders import bootstrap, instantiate, input_requirements, seed_duration_history
    registry = bootstrap(ROOT)
    from parking_opt.domain.spot import Spot, SpotType
    from parking_opt.simulation.parking_lot import ParkingLot
    algorithm, params = payload["algorithm"], payload.get("params", {})
    random.seed(payload.get("seed", 0))
    candidates = payload["candidates"]
    allowed = {c["space_id"] for c in candidates}
    observations = payload.get("observations") or {}
    now = payload.get("time_s", 0)
    spots = payload.get("spaces", candidates)
    occupied = {s["space_id"] for s in spots if s.get("status") == "occupied"}
    class VisibleLot(ParkingLot):
        def get_available_spots(self):
            return [s for s in self.spots.values() if s.spot_id in allowed
                    and s.spot_id not in self.buffer_in_use]
    lot = VisibleLot([Spot(s["space_id"], SpotType.TANDEM if s["tandem"] else SpotType.STANDALONE,
        s["space_id"], s["group"], s["depth"], is_occupied=s["space_id"] in occupied,
        occupied_by="occupant-" + s["space_id"] if s["space_id"] in occupied else None) for s in spots])
    lot.unknown_status = any(s.get("status") == "unknown" for s in spots)
    for item in observations.get("occupants", []):
        if item["space_id"] not in occupied:
            raise ValueError("OCCUPANT_STATE_MISMATCH")
        lot.vehicles["occupant-" + item["space_id"]] = types.SimpleNamespace(
            arrival_time=item["arrival_s"], estimated_duration=item.get("duration_s"),
            entry_id=item.get("entrance_node_id"))
    distances = {c["space_id"]: c["distance_m"] for c in candidates}
    class Paths:
        def distance_to_spot(self, node, entry=None):
            return distances[node]
    vehicle = types.SimpleNamespace(vehicle_id=payload["request_id"], arrival_time=now,
        estimated_duration=payload.get("duration_s"), entry_id=payload["entrance_node_id"])
    model = payload.get("model")
    if model and datetime.fromisoformat(model["trained_before"].replace("Z", "+00:00")).timestamp() > now:
        raise ValueError("MODEL_TRAINED_AFTER_REQUEST_AS_OF")
    evidence = {"history_count": len(observations.get("arrivals", [])), "seed": payload.get("seed", 0)}
    evidence["history_source"] = observations.get("history_source", observations.get("source", "none"))
    order = []
    while lot.get_available_spots():
        # Fresh instances prevent alternative ranking from mutating a warmup counter
        # repeatedly for the same request. History is replayed identically each time.
        strategy = instantiate(registry, algorithm, params, model)
        seed_duration_history(strategy, observations.get("arrivals", []))
        if algorithm == "rho_rolling":
            for event in sorted(observations.get("arrivals", []), key=lambda e: (e["time_s"], e["event_id"])):
                if event["time_s"] > now:
                    raise ValueError("FUTURE_ARRIVAL_REJECTED")
                prior = types.SimpleNamespace(vehicle_id=event["event_id"], arrival_time=event["time_s"])
                strategy._observe_arrival(prior, event["time_s"])
                strategy._roll_check(event["time_s"])
                strategy._event_check(event["time_s"])
            strategy._observe_arrival(vehicle, now)
            strategy._roll_check(now)
            strategy._event_check(now)
            evidence.update(rho_mode=strategy._mode, cold_start=not observations.get("arrivals"))
        input_requirements(strategy, vehicle, lot)
        spot, status = strategy.assign(vehicle, now, lot, Paths())
        if status != "assigned" or spot is None or spot.spot_id not in allowed or spot.spot_id in order:
            raise ValueError("INVALID_RESEARCH_ASSIGNMENT")
        order.append(spot.spot_id)
        lot.buffer_in_use.add(spot.spot_id)
    if model:
        evidence.update(model_training_hash=model["training_hash"], model_degenerate=model["degenerate"],
                        model_source=model["source"], holdout_mae_s=model["holdout_mae_s"])
    return {"space_ids": order, "input_hash": payload["input_hash"], "source_hash": source_hash(),
            "evidence": evidence}


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["--describe"]:
            from loaders import bootstrap
            registry = bootstrap(ROOT)
            names = list(registry.all().keys())
            if "ml_duration_tree" not in names:
                names.append("ml_duration_tree")
            result = {"source_hash": source_hash(), "supported": names, "catalog": catalog(names)}
        elif sys.argv[1:] == ["--check-release"]:
            payload = json.loads(sys.stdin.buffer.read(131073))
            validate_params(payload["algorithm_id"], payload.get("params", {}))
            result = {"valid": True}
        else:
            result = rank(json.loads(sys.stdin.buffer.read(1_000_001)))
        print(json.dumps(result, allow_nan=False))
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__ + ":" + str(exc)[:180]}))
