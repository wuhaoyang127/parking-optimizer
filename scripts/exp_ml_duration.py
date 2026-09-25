"""第一版实验：ML 时长预测树 vs 经典策略（计算速度 + 加权评分）。

- 场景 A：默认需求模型（停车时长与到达时段无关）——诚实展示 ML 无信息可学时的表现；
- 场景 B：时段相关需求（真实感：早/晚高峰长停、午间短停）——展示 ML 学到时段规律后的增益；
- 同一 seed 下所有策略喂相同需求序列；每个策略运行前克隆车辆，避免状态污染；
- 评分标准与网页一致：src/parking_opt/evaluation/ranking.py 加权评分
  （满足率30/利用率25/等待15/移位10/移位距离10/行驶5/耗时5），同时报告 runtime_s。

用法：
    py scripts/exp_ml_duration.py
产出：
    outputs/exp_ml_duration_summary.md
"""

import os
import random
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.exp_risk_scoring_lib import build_layout, run_once  # noqa: E402
from src.parking_opt.domain.spot import Vehicle  # noqa: E402
from src.parking_opt.evaluation.ranking import DEFAULT_WEIGHTS, weighted_rank  # noqa: E402
from src.parking_opt.simulation.arrival import generate_demand  # noqa: E402
from src.parking_opt.strategies.baselines import NearestPath  # noqa: E402
from src.parking_opt.strategies.greedy import DurationAwareGreedy, GreedyStrategy  # noqa: E402
from src.parking_opt.strategies.ml_duration import MlDurationTreeStrategy  # noqa: E402

# 计数类指标（多种子取平均后取整）
COUNT_FIELDS = {"shift_count", "rejected_count", "buffer_failed_count",
                "secondary_shift_count"}

STRATS = ["nearest", "greedy", "duration_greedy", "ml_duration_tree"]
LABELS = {
    "nearest": "最近路径",
    "greedy": "贪心（基线）",
    "duration_greedy": "时长感知贪心（主方法）",
    "ml_duration_tree": "ML 时长预测树",
}


def factories():
    return {
        "nearest": lambda: NearestPath(),
        "greedy": lambda: GreedyStrategy(),
        "duration_greedy": lambda: DurationAwareGreedy(),
        "ml_duration_tree": lambda: MlDurationTreeStrategy(),
    }


def clone_vehicles(vehicles):
    """深拷贝需求序列：引擎会改写车辆状态，每个策略必须用全新副本。"""
    return [Vehicle(vehicle_id=v.vehicle_id, arrival_time=v.arrival_time,
                    parking_duration=v.parking_duration,
                    estimated_duration=v.estimated_duration,
                    entry_id=v.entry_id, exit_id=v.exit_id)
            for v in vehicles]


def make_time_correlated(vehicles, seed, error_ratio=0.15):
    """按到达时段重设停车时长（真实感）：早高峰/晚高峰长停、午间短停。

    estimated_duration 保持与经典口径一致：真实时长 × (1 ± error_ratio)。
    """
    rng = random.Random(seed + 777)
    out = []
    for v in vehicles:
        t = v.arrival_time
        if t < 9000:        # 早高峰（0~2.5h）长停 1.5~2.5h
            real = rng.uniform(5400, 9000)
        elif t < 16200:     # 午间（2.5~4.5h）短停 10~40min
            real = rng.uniform(600, 2400)
        else:               # 晚高峰（4.5~6h）长停 1.5~2.5h
            real = rng.uniform(5400, 9000)
        v.parking_duration = real
        v.estimated_duration = real * (1 + rng.uniform(-error_ratio, error_ratio))
        out.append(v)
    return out


def avg(rows, key):
    vals = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
    mean = sum(vals) / len(vals)
    return int(mean + 0.5) if key in COUNT_FIELDS else round(mean, 4)


def fmt_table(scene_rows):
    """scene_rows: {strategy: metrics}（未排名）"""
    header = ("| 策略 | 满足率 | 利用率 | 等待(s) | 移位 | 移位距离(m) | "
              "行驶距离(m) | 耗时(s) |")
    sep = "|---|---|---|---|---|---|---|---|"
    lines = [header, sep]
    for strat in STRATS:
        m = scene_rows[strat]
        lines.append(
            f"| {LABELS[strat]} | {m['satisfaction_rate']:.3f} | "
            f"{m['spatial_utilization']:.3f} | {m['avg_wait_time_s']:.1f} | "
            f"{m['shift_count']} | {m['shift_distance_m']:.0f} | "
            f"{m['total_drive_distance_m']:.0f} | {m['runtime_s']:.2f} |")
    return "\n".join(lines)


def rank_table(rows):
    """rows: {strategy: metrics}，用网页默认权重做加权排名。"""
    metrics_list = [{"strategy": strat, **m} for strat, m in rows.items()]
    ranked = weighted_rank(metrics_list, DEFAULT_WEIGHTS)
    header = "| 排名 | 策略 | 加权得分 |"
    sep = "|---|---|---|"
    lines = [header, sep]
    for r in ranked:
        lines.append(f"| {r['rank']} | {LABELS[r['strategy']]} | {r['weighted_score']:.4f} |")
    return "\n".join(lines)


def main():
    net, spots = build_layout()
    n_spots = len(spots)
    seeds = [42, 43, 44, 45, 46]
    nveh = 300
    scenes = {
        "A_时长与到达无关（默认需求模型）": {
            s: generate_demand(total_vehicles=nveh, seed=s) for s in seeds},
        "B_时长与到达时段相关（真实感）": {
            s: make_time_correlated(generate_demand(total_vehicles=nveh, seed=s), s)
            for s in seeds},
    }
    factories_map = factories()

    md = [f"# ML 时长预测树第一版实验汇总\n",
          f"- 车位：{n_spots}；车辆：{nveh}；seeds：{seeds}（每格取均值）；\n",
          f"- 同一 seed 下四策略喂相同需求序列（每策略运行前克隆车辆，避免状态污染）；\n",
          f"- 评分标准与网页一致（加权：满足率30/利用率25/等待15/移位10/移位距离10/"
          f"行驶5/耗时5）；耗时含 ML 离线训练与仿真全过程。\n"]
    for scene, demands in scenes.items():
        rows = {}
        for strat in STRATS:
            per_seed = []
            for s in seeds:
                t0 = time.time()
                m = run_once(net, spots, clone_vehicles(demands[s]),
                             factories_map[strat](), s)
                m["runtime_s"] = round(time.time() - t0, 4)
                per_seed.append(m)
            rows[strat] = {k: avg(per_seed, k) for k in
                           ("satisfaction_rate", "spatial_utilization",
                            "avg_wait_time_s", "shift_count", "shift_distance_m",
                            "total_drive_distance_m", "runtime_s")}
        md.append(f"\n## 场景 {scene}\n")
        md.append(fmt_table(rows))
        md.append("\n**加权排名（默认权重）**\n")
        md.append(rank_table(rows))
        print(f"\n=== 场景 {scene}（车位 {n_spots} / {nveh} 车）===")
        print(fmt_table(rows))
        print(rank_table(rows))

    os.makedirs("outputs", exist_ok=True)
    with open("outputs/exp_ml_duration_summary.md", "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    print("\n已写入 outputs/exp_ml_duration_summary.md")


if __name__ == "__main__":
    main()
