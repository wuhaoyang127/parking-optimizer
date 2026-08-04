"""运行仿真对比所有策略"""
import sys, json, time
sys.path.insert(0, 'src')

from parking_opt.cli.main import build_test_network, spots_from_network
from parking_opt.routing.path_engine import PathEngine
from parking_opt.simulation.parking_lot import ParkingLot
from parking_opt.simulation.engine import SimulationEngine
from parking_opt.simulation.arrival import generate_demand
from parking_opt.strategies.baselines import FCFS, NearestPath, RandomAssign
from parking_opt.strategies.greedy import GreedyStrategy, DepartureOrderGreedy
from parking_opt.evaluation.metrics import compute_metrics

strategies = {
    "greedy": GreedyStrategy(),
    "fcfs": FCFS(),
    "nearest": NearestPath(),
    "random": RandomAssign(),
    "departure_greedy": DepartureOrderGreedy(),
}

results = []
for name, strategy in strategies.items():
    network = build_test_network(n_spots=20, tandem_ratio=0.3)
    spots = spots_from_network(network)
    pe = PathEngine(network)
    lot = ParkingLot(spots)
    vehicles = generate_demand(total_vehicles=30, seed=42)
    
    t0 = time.time()
    engine = SimulationEngine(lot, pe, vehicles, strategy, seed=42)
    events = engine.run()
    elapsed = time.time() - t0
    
    metrics = compute_metrics(events, len(spots))
    metrics["strategy"] = name
    metrics["runtime_s"] = round(elapsed, 3)
    results.append(metrics)

# Output
header = f"{'Strategy':<18} {'Satisfy':>8} {'Util':>8} {'Shifts':>7} {'ShiftDist':>9} {'Drive':>9} {'Reject':>7} {'Time':>7}"
print(header)
print("-" * len(header))
for r in results:
    print(f"{r['strategy']:<18} {r['satisfaction_rate']:>8.3f} {r['spatial_utilization']:>8.3f} {r['shift_count']:>7} {r['shift_distance_m']:>9.1f} {r['total_drive_distance_m']:>9.1f} {r['rejected_count']:>7} {r['runtime_s']:>7.3f}")

import os
os.makedirs("outputs", exist_ok=True)
with open("outputs/comparison.json", "w") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print("\nSaved to outputs/comparison.json")
