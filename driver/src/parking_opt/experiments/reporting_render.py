"""Figure generation and Markdown rendering for experiment reports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, TextIO

from parking_opt.experiments.reporting import BASELINE_ID, CANDIDATE_ID, CO_PRIMARY_METRICS


def _generate_figures(
    report_root: Path,
    *,
    paired_statistics: Mapping[str, Any],
    metrics: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    import matplotlib

    matplotlib.use("Agg")
    matplotlib.rcParams["svg.hashsalt"] = "parking-opt-c6-v1"
    from matplotlib import pyplot as plt

    figure_root = report_root / "figures"
    figure_root.mkdir(parents=True, exist_ok=True)
    generated: list[str] = []

    available = [metric for metric in CO_PRIMARY_METRICS if metric in paired_statistics]
    if available:
        differences = [
            float(paired_statistics[metric]["paired"]["descriptive"]["mean"])
            for metric in available
        ]
        fig, axis = plt.subplots(figsize=(8, 4.5))
        axis.bar(available, differences, color="#35618f")
        axis.axhline(0, color="black", linewidth=0.8)
        axis.set_ylabel("candidate - baseline")
        axis.set_title("Paired co-primary differences from saved MetricRecord rows")
        axis.tick_params(axis="x", rotation=20)
        fig.tight_layout()
        relative = "paired-co-primary-differences.svg"
        fig.savefig(figure_root / relative, format="svg", metadata={"Date": None})
        plt.close(fig)
        generated.append(f"figures/{relative}")

    delay_rows = [
        item
        for item in metrics
        if item["metric_name"] == "departure_delay_s"
        and item["record_level"] == "request_observation"
        and item["event_observed"] is True
        and item["value"] is not None
    ]
    if delay_rows:
        grouped = {
            algorithm_id: [
                float(item["value"]) for item in delay_rows if item["algorithm_id"] == algorithm_id
            ]
            for algorithm_id in (BASELINE_ID, CANDIDATE_ID)
        }
        if all(grouped.values()):
            fig, axis = plt.subplots(figsize=(8, 4.5))
            axis.boxplot(
                [grouped[BASELINE_ID], grouped[CANDIDATE_ID]],
                tick_labels=[BASELINE_ID, CANDIDATE_ID],
                showfliers=True,
            )
            axis.set_ylabel("completed-only departure delay (s)")
            axis.set_title("Departure-delay distribution from saved request records")
            fig.tight_layout()
            relative = "departure-delay-completed-only.svg"
            fig.savefig(figure_root / relative, format="svg", metadata={"Date": None})
            plt.close(fig)
            generated.append(f"figures/{relative}")
    return tuple(generated)


def _render_report(
    handle: TextIO,
    *,
    pair_count: int,
    statistics: Mapping[str, Any],
    failures: Sequence[Mapping[str, Any]],
    figures: Sequence[str],
    research_gate: Mapping[str, Any],
) -> None:
    handle.write("# C6 正式实验阶段性报告\n\n")
    handle.write(
        "本报告只由已保存的 RunManifest、MetricRecord、请求记录和失败记录再生。"
        "当前证据来自 synthetic 正式小单元, 不能外推为真实停车场收益。\n\n"
    )
    handle.write(f"- 完整配对单元数: {pair_count}\n")
    handle.write(f"- 失败/回退记录数: {len(failures)}\n")
    handle.write(f"- 滚动研究保留门: `{research_gate['status']}`\n\n")
    handle.write("## 配对结果 (滚动候选减在线基线)\n\n")
    handle.write("| 指标 | n | 均值差 | 标准差 | 中位数 | IQR | 95% bootstrap CI | 相对均值差 |\n")
    handle.write("|---|---:|---:|---:|---:|---:|---:|---:|\n")
    for metric_name, value in sorted(statistics.items()):
        paired = value["paired"]
        relative = paired["relative_difference_mean"]
        relative_text = "NA" if relative is None else f"{relative:.6f}"
        handle.write(
            f"| `{metric_name}` | {paired['descriptive']['n']} | "
            f"{paired['descriptive']['mean']:.6f} | "
            f"{paired['descriptive']['standard_deviation']:.6f} | "
            f"{paired['descriptive']['median']:.6f} | "
            f"{paired['descriptive']['iqr']:.6f} | "
            f"[{paired['ci_lower']:.6f}, {paired['ci_upper']:.6f}] | "
            f"{relative_text} |\n"
        )
    handle.write("\n")
    handle.write(
        "样本量不足完整 20-seed 核心矩阵时, 置信区间只验证统计流水线,不得用于通过研究保留门。\n\n"
    )
    handle.write("## 静态图\n\n")
    for figure in figures:
        handle.write(f"- [{figure}]({figure})\n")
    if not figures:
        handle.write("- 当前保存记录不足以生成图。\n")
    handle.write("\n## 未完成的冻结分析\n\n")
    handle.write(
        "- 0/1/2 缓冲比较、资源容量 1/2、双恢复策略、软信息、取消和预算敏感性"
        "需要剩余正式矩阵; 当前不得据此下结论。\n"
    )
    handle.write("- 所有不利场景、失败、超时、右删失与显式降级均保留在原始产物中。\n")
