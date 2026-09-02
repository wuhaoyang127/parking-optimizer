"""viz 包：停车场布局图绘制（Plotly）。"""
from typing import Optional

import plotly.graph_objects as go

from parking_opt.domain.spot import RoadNetwork, NodeType, SpotType
from viz.colors import *


def draw_parking_layout(
    net: RoadNetwork, spots: list,
    state: Optional[dict] = None,
    highlight_vehicle: Optional[str] = None,
    highlight_path: Optional[list] = None,
    highlight_path_color: Optional[str] = None,
    extra_paths: Optional[list] = None,
    view_center: Optional[tuple] = None,
    view_radius: Optional[float] = None,
    height: int = 420,
    scale: float = 1.0,
) -> go.Figure:
    """
    绘制停车场布局图。scale > 1 放大所有 marker/文字/线宽。

    highlight_path_color: 高亮路径虚线颜色（默认黄色）；
    extra_paths: 额外虚线列表 [{"path": [node_id...], "color": "#..."}]（如移位让行轨迹）。
    """
    s = scale
    fig = go.Figure()
    ss = state.get("ss", {}) if state else {}
    dv = state.get("dv", []) if state else []

    # 1. 道路网络（主路/支路各合并成一个 trace，避免几百条边生成几百个 trace 导致卡顿）
    main_x, main_y, spur_x, spur_y = [], [], [], []
    for edge in net.edges:
        fn = net.nodes.get(edge.from_node)
        tn = net.nodes.get(edge.to_node)
        if not fn or not tn: continue
        is_spur = fn.node_type == NodeType.PARKING_SPOT or tn.node_type == NodeType.PARKING_SPOT
        xs = spur_x if is_spur else main_x
        ys = spur_y if is_spur else main_y
        xs.extend([fn.x, tn.x, None])  # None 用于断开不同边之间的连线
        ys.extend([fn.y, tn.y, None])
    if main_x:
        fig.add_trace(go.Scatter(
            x=main_x, y=main_y, mode="lines",
            line=dict(color=ROAD_COLOR_MAIN, width=_s("road_main", s)),
            showlegend=False, hoverinfo="none",
        ))
    if spur_x:
        fig.add_trace(go.Scatter(
            x=spur_x, y=spur_y, mode="lines",
            line=dict(color=ROAD_COLOR_SPUR, width=_s("road_spur", s), dash="dot"),
            showlegend=False, hoverinfo="none",
        ))

    # 2. 车位
    sx, sy, sc, st, sh, sz = [], [], [], [], [], []
    for sp in spots:
        if sp.spot_id not in net.nodes: continue
        node = net.nodes[sp.spot_id]; sd = ss.get(sp.spot_id, {})
        if sd.get("occ") and sd.get("blocked"): c = SPOT_BLOCKED
        elif sd.get("occ"): c = SPOT_OCCUPIED
        else: c = SPOT_FREE
        sz.append(_s("tandem" if sp.spot_type == SpotType.TANDEM else "spot", s))
        sx.append(node.x); sy.append(node.y); sc.append(c)
        st.append(sp.spot_id)
        sh.append(f"{sp.spot_id} | {'纵深' if sp.spot_type==SpotType.TANDEM else '独立'}"
                  f" | {'占用' if sd.get('occ') else '空闲'}{' [被挡]' if sd.get('blocked') else ''}")
    if sx:
        fig.add_trace(go.Scatter(
            x=sx, y=sy, mode="markers+text",
            marker=dict(color=sc, size=sz, symbol="square",
                        line=dict(width=max(0.5*s,0.5), color="#fff")),
            text=st, textposition="middle center",
            textfont=dict(size=max(_s("spot_text",s),5), color="white"),
            hovertext=sh, hoverinfo="text", showlegend=False,
        ))

    # 3. 入口（支持多个）与出口
    entry_nodes = [n for n in net.nodes.values() if n.node_type == NodeType.ENTRY]
    exit_nodes = [n for n in net.nodes.values() if n.node_type == NodeType.EXIT]
    if entry_nodes:
        fig.add_trace(go.Scatter(
            x=[n.x for n in entry_nodes], y=[n.y for n in entry_nodes],
            mode="markers+text",
            marker=dict(color=ENTRY_COLOR, size=_s("entry", s), symbol="triangle-up"),
            text=[f"入口 {n.node_id}" if len(entry_nodes) > 1 else "入口"
                  for n in entry_nodes],
            textposition="bottom center",
            textfont=dict(size=max(_s("entry_text", s), 6), color=ENTRY_COLOR),
            hovertext=[f"停车场入口 {n.node_id}" for n in entry_nodes],
            hoverinfo="text", showlegend=False,
        ))
    if exit_nodes:
        fig.add_trace(go.Scatter(
            x=[n.x for n in exit_nodes], y=[n.y for n in exit_nodes],
            mode="markers+text",
            marker=dict(color=EXIT_COLOR, size=_s("entry", s), symbol="triangle-down"),
            text=[f"出口 {n.node_id}" if len(exit_nodes) > 1 else "出口"
                  for n in exit_nodes],
            textposition="top center",
            textfont=dict(size=max(_s("entry_text", s), 6), color=EXIT_COLOR),
            hovertext=[f"停车场出口 {n.node_id}" for n in exit_nodes],
            hoverinfo="text", showlegend=False,
        ))

    # 4. 行驶中的车辆（普通车辆合并成一个 trace，高亮车辆单独一个 trace 保留描边）
    normal, hl = [], []
    for v in dv:
        (hl if str(v.get("vid", "")) == highlight_vehicle else normal).append(v)
    for group, is_hl in ((normal, False), (hl, True)):
        if not group:
            continue
        vx = [v["x"] for v in group]
        vy = [v["y"] for v in group]
        vtext = [f"▶ {v.get('vid','')}" if is_hl else str(v.get('vid','')) for v in group]
        vhover = [f"车辆 {v.get('vid','')} | {v.get('st','行驶中')} | → {v.get('target','?')}" for v in group]
        fig.add_trace(go.Scatter(
            x=vx, y=vy, mode="markers+text",
            marker=dict(
                color=HIGHLIGHT_VEHICLE if is_hl else VEHICLE_COLOR,
                size=_s("veh_hl" if is_hl else "veh", s),
                symbol="circle",
                line=dict(width=2*s, color="white") if is_hl else None,
            ),
            text=vtext, textposition="top center",
            textfont=dict(size=max(_s("veh_text", s), 6),
                          color=HIGHLIGHT_VEHICLE if is_hl else "#333"),
            hovertext=vhover, hoverinfo="text", showlegend=False,
        ))

    # 5. 高亮路径（可指定颜色；extra_paths 画移位让行等辅助虚线）
    path_color = highlight_path_color or HIGHLIGHT_PATH

    def _path_trace(nodes, color):
        px, py = [], []
        for nid in nodes:
            if nid in net.nodes:
                px.append(net.nodes[nid].x); py.append(net.nodes[nid].y)
        return go.Scatter(
            x=px, y=py, mode="lines+markers",
            line=dict(color=color, width=_s("path_w", s), dash="dot"),
            marker=dict(color=color, size=_s("path_marker", s), symbol="circle"),
            showlegend=False, hoverinfo="skip",
        )

    if highlight_path:
        fig.add_trace(_path_trace(highlight_path, path_color))
    for extra in (extra_paths or []):
        ep = extra.get("path")
        if ep:
            fig.add_trace(_path_trace(ep, extra.get("color", HIGHLIGHT_PATH)))

    # 6. 道路节点
    rx, ry, rt = [], [], []
    for n in net.nodes.values():
        if n.node_type == NodeType.ROAD_NODE:
            rx.append(n.x); ry.append(n.y); rt.append(n.node_id)
    if rx:
        fig.add_trace(go.Scatter(
            x=rx, y=ry, mode="markers+text",
            marker=dict(color=ROAD_COLOR_MAIN, size=_s("rnode",s), symbol="diamond"),
            text=rt, textposition="top center",
            textfont=dict(size=max(_s("rnode_text",s),5), color="#546E7A"),
            hoverinfo="skip", showlegend=False,
        ))

    # 7. 布局
    fig.update_layout(
        height=height,
        margin=dict(l=5, r=5, t=5, b=5),
        plot_bgcolor=BG_COLOR, paper_bgcolor=BG_COLOR,
        dragmode="pan",
        showlegend=False,
    )
    fig.update_xaxes(showgrid=False, zeroline=False, showticklabels=False,
                     title=None, constrain="domain")
    fig.update_yaxes(showgrid=False, zeroline=False, showticklabels=False,
                     title=None, constrain="domain",
                     scaleanchor="x", scaleratio=1)

    # 8. 局部裁剪
    if view_center and view_radius:
        cx, cy = view_center; r = view_radius
        fig.update_xaxes(range=[cx-r, cx+r])
        fig.update_yaxes(range=[cy-r, cy+r])

    return fig
