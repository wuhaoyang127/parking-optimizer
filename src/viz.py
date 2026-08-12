"""停车场可视化 — Plotly 绘图模块"""

import math
import plotly.graph_objects as go
from parking_opt.domain.spot import RoadNetwork, NodeType, Spot, SpotType


# ─── 颜色方案 ───
ROAD_COLOR_MAIN = "#78909C"      # 主路
ROAD_COLOR_SPUR = "#B0BEC5"      # 支路（车位连接线）
ENTRY_COLOR = "#2E7D32"          # 入口
SPOT_FREE = "#66BB6A"            # 空闲车位
SPOT_OCCUPIED = "#EF5350"        # 占用车位
SPOT_BLOCKED = "#FF9800"         # 被挡车位
VEHICLE_COLOR = "#2196F3"        # 行驶中的车辆
PATH_COLOR = "#FF5722"           # 行驶路径
HIGHLIGHT_VEHICLE = "#E91E63"    # 选中车辆
HIGHLIGHT_PATH = "#FFEB3B"       # 选中车辆路径
BG_COLOR = "#FAFBFC"             # 图背景


def draw_parking_layout(
    net: RoadNetwork,
    spots: list,
    state: dict | None = None,
    highlight_vehicle: str | None = None,
    highlight_path: list | None = None,
    view_center: tuple | None = None,
    view_radius: float | None = None,
    height: int = 420,
) -> go.Figure:
    """
    绘制停车场布局图。

    Args:
        net: 路网对象
        spots: 车位列表
        state: 状态 dict，含 'ss' (spot状态) 和 'dv' (行驶车辆)
        highlight_vehicle: 高亮的车辆 ID
        highlight_path: 高亮的路径节点列表
        view_center: 局部视图中心 (x, y)
        view_radius: 局部视图半径
        height: 图高度
    """
    fig = go.Figure()
    ss = state.get("ss", {}) if state else {}
    dv = state.get("dv", []) if state else []

    # ─── 1. 绘制道路网络 ───
    for edge in net.edges:
        fn = net.nodes.get(edge.from_node)
        tn = net.nodes.get(edge.to_node)
        if not fn or not tn:
            continue
        # 判断是主路还是支路
        is_spur = (
            fn.node_type == NodeType.PARKING_SPOT
            or tn.node_type == NodeType.PARKING_SPOT
        )
        color = ROAD_COLOR_SPUR if is_spur else ROAD_COLOR_MAIN
        dash = "dot" if is_spur else "solid"
        width = 1.5 if is_spur else 3
        fig.add_trace(go.Scatter(
            x=[fn.x, tn.x], y=[fn.y, tn.y],
            mode="lines",
            line=dict(color=color, width=width, dash=dash),
            showlegend=False, hoverinfo="none",
        ))

    # ─── 2. 绘制车位 ───
    spot_x, spot_y, spot_c, spot_txt, spot_hover = [], [], [], [], []
    for s in spots:
        if s.spot_id not in net.nodes:
            continue
        node = net.nodes[s.spot_id]
        sd = ss.get(s.spot_id, {})
        # 颜色
        if sd.get("occ") and sd.get("blocked"):
            c = SPOT_BLOCKED
        elif sd.get("occ"):
            c = SPOT_OCCUPIED
        else:
            c = SPOT_FREE
        # 大小
        size = 9 if s.spot_type == SpotType.TANDEM else 11
        spot_x.append(node.x)
        spot_y.append(node.y)
        spot_c.append(c)
        spot_txt.append(s.spot_id)
        spot_hover.append(
            f"{s.spot_id} | {'纵深' if s.spot_type == SpotType.TANDEM else '独立'}"
            f" | {'占用' if sd.get('occ') else '空闲'}"
            f"{' [被挡]' if sd.get('blocked') else ''}"
        )

    fig.add_trace(go.Scatter(
        x=spot_x, y=spot_y,
        mode="markers+text",
        marker=dict(color=spot_c, size=size, symbol="square", line=dict(width=0.5, color="#fff")),
        text=spot_txt,
        textposition="middle center",
        textfont=dict(size=7, color="white"),
        hovertext=spot_hover,
        hoverinfo="text",
        showlegend=False,
    ))

    # ─── 3. 绘制入口 ───
    entry_node = None
    for n in net.nodes.values():
        if n.node_type == NodeType.ENTRY:
            entry_node = n
            break
    if entry_node:
        fig.add_trace(go.Scatter(
            x=[entry_node.x], y=[entry_node.y],
            mode="markers+text",
            marker=dict(color=ENTRY_COLOR, size=16, symbol="triangle-up"),
            text=["入口"],
            textposition="bottom center",
            textfont=dict(size=9, color=ENTRY_COLOR),
            hoverinfo="text",
            hovertext="停车场入口",
            showlegend=False,
        ))

    # ─── 4. 绘制行驶中的车辆 ───
    for v in dv:
        vid = str(v.get("vid", ""))
        is_hl = vid == highlight_vehicle
        fig.add_trace(go.Scatter(
            x=[v["x"]], y=[v["y"]],
            mode="markers+text",
            marker=dict(
                color=HIGHLIGHT_VEHICLE if is_hl else VEHICLE_COLOR,
                size=16 if is_hl else 11,
                symbol="circle",
                line=dict(width=2, color="white") if is_hl else None,
            ),
            text=[vid] if not is_hl else [f"▶ {vid}"],
            textposition="top center",
            textfont=dict(size=8, color=HIGHLIGHT_VEHICLE if is_hl else "#333"),
            hoverinfo="text",
            hovertext=f"车辆 {vid} | {v.get('st', '行驶中')} | → {v.get('target', '?')}",
            showlegend=False,
        ))

    # ─── 5. 绘制高亮路径 ───
    if highlight_path:
        px, py = [], []
        for nid in highlight_path:
            if nid in net.nodes:
                px.append(net.nodes[nid].x)
                py.append(net.nodes[nid].y)
        fig.add_trace(go.Scatter(
            x=px, y=py,
            mode="lines+markers",
            line=dict(color=HIGHLIGHT_PATH, width=4, dash="dot"),
            marker=dict(color=HIGHLIGHT_PATH, size=6, symbol="circle"),
            showlegend=False,
            hoverinfo="skip",
            name="行驶路径",
        ))

    # ─── 6. 路网节点标签（道路节点，非车位）───
    rn_x, rn_y, rn_txt = [], [], []
    for n in net.nodes.values():
        if n.node_type == NodeType.ROAD_NODE:
            rn_x.append(n.x)
            rn_y.append(n.y)
            rn_txt.append(n.node_id)
    if rn_x:
        fig.add_trace(go.Scatter(
            x=rn_x, y=rn_y,
            mode="markers+text",
            marker=dict(color=ROAD_COLOR_MAIN, size=5, symbol="diamond"),
            text=rn_txt,
            textposition="top center",
            textfont=dict(size=7, color="#546E7A"),
            hoverinfo="skip",
            showlegend=False,
        ))

    # ─── 7. 布局设置 ───
    fig.update_layout(
        height=height,
        margin=dict(l=30, r=30, t=30, b=30),
        plot_bgcolor=BG_COLOR,
        paper_bgcolor=BG_COLOR,
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False, title=None),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False, title=None,
                   scaleanchor="x", scaleratio=1),
        showlegend=False,
    )

    # ─── 8. 局部视图裁剪 ───
    if view_center and view_radius:
        cx, cy = view_center
        r = view_radius
        fig.update_xaxes(range=[cx - r, cx + r])
        fig.update_yaxes(range=[cy - r, cy + r])

    return fig


def draw_dual_view(
    net: RoadNetwork,
    spots: list,
    state: dict,
    highlight_vehicle: str,
    highlight_path: list,
    local_center: tuple,
    local_radius: float = 20,
) -> tuple:
    """
    绘制全局+局部双视图。

    Returns:
        (global_fig, local_fig)
    """
    fig_global = draw_parking_layout(
        net, spots, state,
        highlight_vehicle=highlight_vehicle,
        highlight_path=highlight_path,
        height=350,
    )

    fig_local = draw_parking_layout(
        net, spots, state,
        highlight_vehicle=highlight_vehicle,
        highlight_path=highlight_path,
        view_center=local_center,
        view_radius=local_radius,
        height=350,
    )

    return fig_global, fig_local
