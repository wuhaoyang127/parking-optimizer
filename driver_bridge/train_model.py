"""Train the original CART strategy only on completed, historical records."""
import hashlib
import json
import math
from pathlib import Path
import sys
import types
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "driver_bridge"))
from catalog import validate_params
from loaders import bootstrap


def train(payload):
    params = payload.get("params", {})
    validate_params("ml_duration_tree", params)
    rows = payload["samples"]
    if not 10 <= len(rows) <= 1000:
        raise ValueError("HISTORICAL_SAMPLE_COUNT_MUST_BE_10_TO_1000")
    cutoff = datetime.fromisoformat(payload["trained_before"].replace("Z", "+00:00"))
    if cutoff.tzinfo is None or cutoff > datetime.now(timezone.utc):
        raise ValueError("TRAINING_CUTOFF_MUST_BE_OBSERVED_PAST")
    ids, vehicles = set(), []
    for row in rows:
        if set(row) != {"record_id", "arrival_at", "departed_at", "entrance_node_id"}:
            raise ValueError("HISTORICAL_SAMPLE_FIELDS")
        arrival = datetime.fromisoformat(row["arrival_at"].replace("Z", "+00:00"))
        departed = datetime.fromisoformat(row["departed_at"].replace("Z", "+00:00"))
        if arrival.tzinfo is None or departed.tzinfo is None or not arrival < departed <= cutoff:
            raise ValueError("UNFINISHED_OR_FUTURE_TRAINING_SAMPLE")
        if row["record_id"] in ids:
            raise ValueError("DUPLICATE_HISTORICAL_RECORD")
        ids.add(row["record_id"])
        duration = (departed-arrival).total_seconds()
        if not 0 < duration <= 604800:
            raise ValueError("TRAINING_DURATION_OUT_OF_RANGE")
        vehicles.append(types.SimpleNamespace(arrival_time=arrival.timestamp(),
            parking_duration=duration, entry_id=row["entrance_node_id"]))
    if len({v.entry_id for v in vehicles}) > 32:
        raise ValueError("TOO_MANY_ENTRANCES")
    bootstrap(ROOT)
    from parking_opt.strategies.ml_duration import MlDurationTreeStrategy
    vehicles.sort(key=lambda v: v.arrival_time)
    split = max(2, int(len(vehicles) * .8))
    strategy = MlDurationTreeStrategy(**params)
    # Keep the latest chronological 20% out of the fitted model. Never refit it
    # after measuring the holdout, so the reported error belongs to the artifact.
    strategy.prepare(vehicles[:split], None, None)
    if strategy._tree is None:
        raise ValueError("INSUFFICIENT_TRAINING_SAMPLES_FOR_LEAF_SIZE")
    error = sum(abs(strategy._predict_duration(v)-v.parking_duration) for v in vehicles[split:])
    mae = error / (len(vehicles) - split)
    def serialize(node):
        item = {"value": float(node.value)}
        if node.feature is not None:
            item.update(feature=int(node.feature), threshold=float(node.threshold),
                        left=serialize(node.left), right=serialize(node.right))
        return item
    canonical = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {"contract": "cart-duration-1.0.0", "source": payload["source"],
        "trained_before": cutoff.isoformat(), "sample_count": len(rows),
        "training_hash": hashlib.sha256(canonical.encode()).hexdigest(),
        "holdout_mae_s": mae, "entries": strategy._entries, "use_entry": strategy.use_entry,
        "max_depth": strategy.max_depth, "min_samples_leaf": strategy.min_samples_leaf,
        "threshold_s": strategy._threshold, "fallback_s": strategy._fallback,
        "degenerate": strategy._degenerate, "tree": serialize(strategy._tree.root)}


if __name__ == "__main__":
    try:
        result = train(json.loads(sys.stdin.buffer.read(2_000_001)))
        print(json.dumps({"model": result}, allow_nan=False))
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__ + ":" + str(exc)[:160]}))
