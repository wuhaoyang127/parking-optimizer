"""Reviewed classes loaded in a private process, without UI or offline prepare."""
from pathlib import Path
import sys
import types
from catalog import validate_params


def bootstrap(root):
    for name in ("parking_opt", "parking_opt.domain", "parking_opt.simulation", "parking_opt.strategies"):
        module = types.ModuleType(name)
        module.__path__ = [str(root / "src" / Path(*name.split(".")))]
        sys.modules[name] = module
    from parking_opt.strategies.baselines import FCFS, NearestPath, RandomAssign
    from parking_opt.strategies.greedy import GreedyStrategy, DepartureOrderGreedy, DurationAwareGreedy
    from parking_opt.strategies.risk_scoring import RiskScoringStrategy
    from parking_opt.strategies.fusion import PeakOffPeakFusion
    from parking_opt.strategies.rho import RhoRollingStrategy
    from parking_opt.strategies.registry import StrategyRegistry
    for cls in (FCFS, NearestPath, RandomAssign, GreedyStrategy, DepartureOrderGreedy,
                DurationAwareGreedy, RiskScoringStrategy, PeakOffPeakFusion, RhoRollingStrategy):
        StrategyRegistry.register(cls)
    return StrategyRegistry


def instantiate(registry, algorithm, params, model=None):
    validate_params(algorithm, params)
    if algorithm == "ml_duration_tree":
        if not model:
            raise ValueError("ML_TRAINED_MODEL_REQUIRED")
        from parking_opt.strategies.ml_duration import MlDurationTreeStrategy
        from parking_opt.strategies._cart import CartRegressor, _TreeNode
        def node(data):
            item = _TreeNode()
            item.value = data["value"]
            if "feature" in data:
                item.feature, item.threshold = data["feature"], data["threshold"]
                item.left, item.right = node(data["left"]), node(data["right"])
            return item
        strategy = MlDurationTreeStrategy(**{**params, "use_entry": model["use_entry"]})
        strategy._tree = CartRegressor()
        strategy._tree.root = node(model["tree"])
        strategy._threshold, strategy._fallback = model["threshold_s"], model["fallback_s"]
        strategy._degenerate, strategy._entries = model["degenerate"], model["entries"]
        return strategy
    return registry.create(algorithm, **params)


def input_requirements(strategy, vehicle, lot):
    name = strategy.name
    candidates = lot.get_available_spots()
    if not candidates:
        return
    if name == "peak_offpeak_fusion":
        if lot.unknown_status:
            raise ValueError("OCCUPANCY_UNKNOWN_FOR_FUSION")
        ratio = sum(s.is_occupied for s in lot.spots.values()) / len(lot.spots)
        child = strategy._peak if ratio >= strategy.peak_threshold else strategy._offpeak
        return input_requirements(child, vehicle, lot)
    if name == "rho_rolling":
        child = strategy._fallback if strategy._mode == "fallback" else (
            (strategy._high if strategy._last_diff > 0 else strategy._low)
            if strategy._mode == "adjust" else strategy._plan)
        return input_requirements(child, vehicle, lot)
    standalone = any(s.spot_type.value == "STANDALONE" for s in candidates)
    duration_needed = name == "duration_greedy" and not standalone
    risk_needed = name == "risk_scoring" and strategy.w_risk > 0
    if duration_needed and vehicle.estimated_duration is None:
        raise ValueError("USER_DEPARTURE_ESTIMATE_REQUIRED")
    if risk_needed and vehicle.estimated_duration is None:
        if any(s.is_occupied for c in candidates for s in lot.get_group_spots(c)):
            raise ValueError("USER_DEPARTURE_ESTIMATE_REQUIRED")
    if duration_needed or risk_needed:
        for c in candidates:
            for s in lot.get_group_spots(c):
                if s.is_occupied:
                    observed = lot.vehicles.get(s.occupied_by)
                    if observed is None or observed.estimated_duration is None:
                        raise ValueError("OCCUPANT_DEPARTURE_ESTIMATE_REQUIRED")
    if name == "ml_duration_tree" and not standalone:
        for c in candidates:
            for s in lot.get_outer_spots(c):
                if s.is_occupied and s.occupied_by not in lot.vehicles:
                    raise ValueError("OCCUPANT_ARRIVAL_FEATURES_REQUIRED")


def seed_duration_history(strategy, events):
    """Adapter v2 uses prior observed request estimates for duration warmup."""
    if strategy.name == "duration_greedy":
        strategy._seen_durations = [e["duration_s"] for e in events
            if e.get("duration_s") is not None and e.get("estimate_source") in ("user_estimate", "prediction")]
    elif strategy.name == "peak_offpeak_fusion":
        seed_duration_history(strategy._peak, events)
        seed_duration_history(strategy._offpeak, events)
    elif strategy.name == "rho_rolling":
        for child in (strategy._plan, strategy._high, strategy._low, strategy._fallback):
            seed_duration_history(child, events)
