"""排名展示工具：雷达图、加权排名表、无区分度指标提示。"""
from ui.common._imports import *
from ui.common.constants import PRIORITY_METRICS, STRATEGY_LABELS


def _plot_radar(all_m):
    """多维指标雷达图：每个指标归一化到 [0,1]，外圈=更好（min 指标反转）"""
    dims = [("满足率", "satisfaction_rate", "max"), ("利用率", "spatial_utilization", "max"),
            ("平均等待", "avg_wait_time_s", "min"), ("移位次数", "shift_count", "min"),
            ("行驶距离", "total_drive_distance_m", "min")]
    labels = [d[0] for d in dims]
    norm = {}
    for name, field, direction in dims:
        vals = [m.get(field, 0) for m in all_m]
        lo, hi = min(vals), max(vals)
        norm[name] = [(0.5 if hi == lo else
                       (1 - (v - lo) / (hi - lo) if direction == "min" else (v - lo) / (hi - lo)))
                      for v in vals]
    fig = go.Figure()
    for idx, m in enumerate(all_m):
        nm = STRATEGY_LABELS.get(m["strategy"], m["strategy"])
        vals = [norm[d[0]][idx] for d in dims]
        fig.add_trace(go.Scatterpolar(r=vals + [vals[0]], theta=labels + [labels[0]],
                                      name=nm, fill="toself", opacity=0.45))
    fig.update_layout(height=420, margin=dict(l=50, r=50, t=50, b=50),
                      legend=dict(orientation="h", yanchor="bottom", y=-0.15),
                      polar=dict(radialaxis=dict(range=[0, 1], showticklabels=False)))
    return fig


def weighted_rank_df(all_m, weights_by_label):
    """按中文指标名权重对多策略指标做加权评分，返回 (DataFrame, 排序后的带分列表)。"""
    weights = {}
    for label, w in weights_by_label.items():
        if label in PRIORITY_METRICS:
            weights[PRIORITY_METRICS[label][0]] = w
    ranked = weighted_rank(all_m, weights)
    df = pd.DataFrame(ranked)[["rank", "strategy", "weighted_score",
                               "satisfaction_rate", "spatial_utilization",
                               "avg_wait_time_s", "shift_count", "shift_distance_m",
                               "total_drive_distance_m", "rejected_count", "runtime_s"]]
    df.columns = ["排名", "策略", "综合得分", "满足率", "利用率", "平均等待(s)",
                  "移位次数", "移位距离(m)", "行驶距离(m)", "拒绝数", "耗时(s)"]
    return df, ranked


def neutralized_metric_labels(metrics_list) -> list[str]:
    """返回被「实际意义阈值」判定为无区分度的指标中文名列表（供页面提示）。"""
    fields = below_significance_fields(metrics_list)
    labels = []
    for label, (field, _direction, _desc) in PRIORITY_METRICS.items():
        if field in fields:
            labels.append(label)
    return labels
