"""Real execution of every online strategy and bounded model/observation inputs."""
from datetime import UTC, datetime, timedelta
from pathlib import Path
import json
import subprocess
import pytest
from pydantic import ValidationError
from parking_opt.api.research_inputs import HistoricalDurationModel, VisibleObservations
from parking_opt.api.research_models import ResearchRelease
from parking_opt.api.research_runtime import ResearchRuntime, canonical_hash

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ResearchRuntime(ROOT.parent / "research")
ALGORITHMS = ("fcfs", "nearest", "random", "greedy", "departure_greedy", "duration_greedy",
              "risk_scoring", "peak_offpeak_fusion", "rho_rolling", "ml_duration_tree")


@pytest.fixture(scope="module")
def trained_model():
    rows = []
    origin = datetime(2026, 8, 1, tzinfo=UTC)
    for i in range(40):
        at = origin + timedelta(hours=i)
        rows.append({"record_id": f"history-{i}", "arrival_at": at.isoformat(),
                     "departed_at": (at + timedelta(minutes=30 if i % 2 == 0 else 120)).isoformat(),
                     "entrance_node_id": "entry"})
    payload = {"samples": rows, "source": "synthetic", "trained_before": "2026-08-10T00:00:00Z",
               "params": {"max_depth": 3, "min_samples_leaf": 2, "use_entry": True}}
    result = subprocess.run([RUNTIME.python, "-I", str(RUNTIME.root / "driver_bridge/train_model.py")],
        input=json.dumps(payload).encode(), capture_output=True, timeout=30)
    model = json.loads(result.stdout)
    assert "error" not in model, model
    return HistoricalDurationModel.model_validate(model["model"]).model_dump(mode="json")


def payload(algorithm, model=None):
    candidates = [{"space_id": "A", "group": "g", "depth": 1, "tandem": True, "distance_m": 10},
                  {"space_id": "B", "group": "g", "depth": 2, "tandem": True, "distance_m": 20},
                  {"space_id": "C", "group": "c", "depth": 1, "tandem": False, "distance_m": 40}]
    value = {"algorithm": algorithm, "params": {}, "seed": 17, "duration_s": 7200,
        "request_id": "current", "entrance_node_id": "entry", "time_s": 1787000000,
        "candidates": candidates, "spaces": [dict(c, status="available") for c in candidates],
        "observations": {"arrivals": [{"event_id": "past-" + str(i), "time_s": 1785999000+i*60}
                                        for i in range(10)], "occupants": []}, "model": model}
    if model:
        value["params"] = {"max_depth": model["max_depth"], "min_samples_leaf": model["min_samples_leaf"]}
    value["input_hash"] = canonical_hash(value)
    return value


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_all_ten_original_strategies_really_execute(algorithm, trained_model):
    value = payload(algorithm, trained_model if algorithm == "ml_duration_tree" else None)
    source_hash = RUNTIME.describe()["source_hash"]
    first = RUNTIME.rank(value, source_hash)
    assert set(first) == {"A", "B", "C"}
    assert first == RUNTIME.rank(value, source_hash)
    if algorithm == "rho_rolling":
        assert first.evidence["history_count"] == 10
        assert first.evidence["cold_start"] is False
    if algorithm == "ml_duration_tree":
        assert first.evidence["model_training_hash"] == trained_model["training_hash"]


@pytest.mark.parametrize("params", [{"threshold": -1}, {"warmup": True}, {"extra": 1}])
def test_illegal_parameters_fail_at_release_boundary(params):
    with pytest.raises(ValueError):
        RUNTIME.check_release({"algorithm_id": "duration_greedy", "params": params})


def test_missing_duration_and_occupied_estimate_are_not_fabricated():
    source_hash = RUNTIME.describe()["source_hash"]
    value = payload("duration_greedy")
    value["duration_s"] = None
    with pytest.raises(ValueError, match="DEPARTURE_ESTIMATE_REQUIRED"):
        RUNTIME.rank(value, source_hash)
    value = payload("risk_scoring")
    value["spaces"].append({"space_id": "O", "group": "g", "depth": 3,
                            "tandem": True, "status": "occupied"})
    with pytest.raises(ValueError, match="OCCUPANT_DEPARTURE_ESTIMATE_REQUIRED"):
        RUNTIME.rank(value, source_hash)


def test_future_history_and_unknown_fusion_status_fail_closed():
    source_hash = RUNTIME.describe()["source_hash"]
    value = payload("rho_rolling")
    value["observations"]["arrivals"][0]["time_s"] = value["time_s"] + 1
    with pytest.raises(ValueError, match="FUTURE_ARRIVAL"):
        RUNTIME.rank(value, source_hash)
    value = payload("peak_offpeak_fusion")
    value["spaces"].append({"space_id": "U", "group": "u", "depth": 1,
                            "tandem": False, "status": "unknown"})
    with pytest.raises(ValueError, match="OCCUPANCY_UNKNOWN"):
        RUNTIME.rank(value, source_hash)


def test_ml_cannot_publish_without_model_or_with_invalid_tree(trained_model):
    common = {"release_id": "ml", "algorithm_id": "ml_duration_tree", "source_hash": "0"*64}
    with pytest.raises(ValidationError):
        ResearchRelease(**common)
    corrupted = dict(trained_model, tree={"value": 12, "exec": "bad"})
    with pytest.raises(ValidationError):
        ResearchRelease(**common, model=corrupted)
    with pytest.raises(ValidationError):
        ResearchRelease(**common, model=trained_model, params={"use_entry": False})


def test_visible_observations_reject_future_and_duplicate_events():
    base = {"session_id": "s", "parking_lot_id": "lot", "layout_hash": "0"*64,
            "source": "synthetic", "observed_at": "2026-08-01T00:00:00Z"}
    with pytest.raises(ValidationError):
        VisibleObservations(**base, arrivals=[{"event_id": "f", "occurred_at": "2026-08-01T00:01:00Z"}])
    event = {"event_id": "x", "occurred_at": base["observed_at"]}
    with pytest.raises(ValidationError):
        VisibleObservations(**base, arrivals=[event, event])


def test_model_trained_after_request_time_is_rejected(trained_model):
    value = payload("ml_duration_tree", trained_model)
    value["time_s"] = datetime(2026, 8, 2, tzinfo=UTC).timestamp()
    with pytest.raises(ValueError, match="MODEL_TRAINED_AFTER_REQUEST"):
        RUNTIME.rank(value, RUNTIME.describe()["source_hash"])


def test_duration_warmup_uses_only_observed_estimates():
    value = payload("duration_greedy")
    value["candidates"] = value["candidates"][:2]
    value["spaces"] = value["spaces"][:2]
    value["duration_s"] = 600
    value["params"] = {"warmup": 1}
    source_hash = RUNTIME.describe()["source_hash"]
    assert RUNTIME.rank(value, source_hash)[0] == "B"  # current sample is its own median
    value["params"] = {"warmup": 10}
    assert RUNTIME.rank(value, source_hash)[0] == "A"  # default threshold until warmup
    for event in value["observations"]["arrivals"]:
        event.update(duration_s=100, estimate_source="user_estimate")
    assert RUNTIME.rank(value, source_hash)[0] == "B"  # real prior estimates now meet warmup
