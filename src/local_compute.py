"""本地计算纯函数模块（不依赖 Streamlit/Pandas/Plotly）。

本模块供 local_worker.py（本机计算 worker）与 ui/common.py 共用：
worker 只需核心算法库（networkx/simpy/ortools/supabase），
不必安装界面库即可在本机跑仿真。
"""

import time

from parking_opt.domain.spot import (RoadNetwork, RoadNode, NodeType,
                                     Spot, SpotType)
from parking_opt.routing.path_engine import PathEngine
from parking_opt.simulation.parking_lot import ParkingLot
from parking_opt.simulation.engine import SimulationEngine
from parking_opt.evaluation.metrics import compute_metrics

# ═══════════════════════════════════════════════════════════
# 停车场布局构建器
# ═══════════════════════════════════════════════════════════
LAYOUT_BUILDERS = {}
LAYOUTS = {"linear": "线形", "rectangle": "矩形", "lshape": "L形",
           "triangle": "三角形", "circle": "环形"}
# 内置示意布局的 key（其余出现在 LAYOUT_BUILDERS 中的为导入的真实布局）
BUILTIN_LAYOUT_KEYS = ["linear", "rectangle", "lshape", "triangle", "circle"]


def _an(net, nid, nt, x, y, st=None, sg=None, dp=None):
    net.add_node(RoadNode(nid, nt, x, y, st, sg, dp))


def build_linear(n_spots, tandem_ratio):
    net = RoadNetwork(); _an(net, "ENTRY", NodeType.ENTRY, 0, 0); _an(net, "N0", NodeType.ROAD_NODE, 5, 0)
    net.add_edge("ENTRY", "N0", 5); spots = []; nt = int(n_spots * tandem_ratio / 2); ns = n_spots - nt * 2
    for i in range(ns):
        sid = f"A{i+1:02d}"; _an(net, sid, NodeType.PARKING_SPOT, 8 + i * 5, 3, SpotType.STANDALONE, sid, 1)
        net.add_edge("N0", sid, 3 + i * 5); net.add_edge(sid, "N0", 3 + i * 5); spots.append(Spot(sid, SpotType.STANDALONE, sid, sid, 1))
    for g in range(nt):
        gid = f"G{g+1}"; prev = "N0"
        for d in range(1, 3):
            sid = f"{gid}-{d}"; _an(net, sid, NodeType.PARKING_SPOT, 30 + g * 8 + d * 4, 3, SpotType.TANDEM, gid, d)
            net.add_edge(prev, sid, 4); net.add_edge(sid, prev, 4); prev = sid; spots.append(Spot(sid, SpotType.TANDEM, sid, gid, d))
    return net, spots


def build_rectangle(n_spots, tandem_ratio):
    net = RoadNetwork(); _an(net, "ENTRY", NodeType.ENTRY, 0, 0)
    _an(net, "M", NodeType.ROAD_NODE, 8, 0); _an(net, "U", NodeType.ROAD_NODE, 8, 6); _an(net, "D", NodeType.ROAD_NODE, 8, -6)
    for a, b, d in [("ENTRY", "M", 8), ("M", "U", 6), ("M", "D", 6), ("U", "M", 6), ("D", "M", 6)]:
        net.add_edge(a, b, d)
    spots = []; half = n_spots // 2; nt = int(half * tandem_ratio / 2); ns = half - nt * 2
    for row, rd, ys in [("U", "U", 1), ("D", "D", -1)]:
        for i in range(ns):
            sid = f"{row}{i+1:02d}"; x = 12 + i * 4.5; y = ys * 9
            _an(net, sid, NodeType.PARKING_SPOT, x, y, SpotType.STANDALONE, sid, 1)
            net.add_edge(rd, sid, 3); net.add_edge(sid, rd, 3); spots.append(Spot(sid, SpotType.STANDALONE, sid, sid, 1))
        for g in range(nt):
            gid = f"{row}G{g+1}"; prev = rd; bx = 12 + ns * 4.5 + g * 7; by = ys * 9
            for d in range(1, 3):
                sid = f"{gid}-{d}"; _an(net, sid, NodeType.PARKING_SPOT, bx + d * 3.5, by, SpotType.TANDEM, gid, d)
                net.add_edge(prev, sid, 3.5); net.add_edge(sid, prev, 3.5); prev = sid; spots.append(Spot(sid, SpotType.TANDEM, sid, gid, d))
    return net, spots


def build_lshape(n_spots, tandem_ratio):
    net = RoadNetwork(); _an(net, "ENTRY", NodeType.ENTRY, 0, 0); _an(net, "C", NodeType.ROAD_NODE, 30, 0)
    _an(net, "V", NodeType.ROAD_NODE, 30, 20)
    for a, b, d in [("ENTRY", "C", 30), ("C", "V", 20), ("V", "C", 20), ("C", "ENTRY", 30)]:
        net.add_edge(a, b, d)
    spots = []; nt = int(n_spots * tandem_ratio / 2); ns = n_spots - nt * 2; hh = ns // 2; vh = ns - hh
    for i in range(hh):
        sid = f"H{i+1:02d}"; _an(net, sid, NodeType.PARKING_SPOT, 5 + i * 5, 4, SpotType.STANDALONE, sid, 1)
        net.add_edge("ENTRY", sid, i * 5 + 5); net.add_edge(sid, "ENTRY", i * 5 + 5); spots.append(Spot(sid, SpotType.STANDALONE, sid, sid, 1))
    for i in range(vh):
        sid = f"V{i+1:02d}"; _an(net, sid, NodeType.PARKING_SPOT, 34, 5 + i * 5, SpotType.STANDALONE, sid, 1)
        net.add_edge("V", sid, i * 5 + 5); net.add_edge(sid, "V", i * 5 + 5); spots.append(Spot(sid, SpotType.STANDALONE, sid, sid, 1))
    for g in range(nt):
        gid = f"TG{g+1}"; prev = "C"; bx = 34 + g * 7
        for d in range(1, 3):
            sid = f"{gid}-{d}"; _an(net, sid, NodeType.PARKING_SPOT, bx + d * 3.5, 24, SpotType.TANDEM, gid, d)
            net.add_edge(prev, sid, 3.5); net.add_edge(sid, prev, 3.5); prev = sid; spots.append(Spot(sid, SpotType.TANDEM, sid, gid, d))
    return net, spots


def build_triangle(n_spots, tandem_ratio):
    import math as _m
    R = 25
    net = RoadNetwork(); vs = [("V0", 0, 0), ("V1", R, 0), ("V2", R * 0.5, R * 0.866)]
    for vid, vx, vy in vs:
        _an(net, vid, NodeType.ROAD_NODE if vid != "V0" else NodeType.ENTRY, vx, vy)
    for a, b in [(0, 1), (1, 2), (2, 0)]:
        va, vb = vs[a], vs[b]; net.add_edge(va[0], vb[0], R); net.add_edge(vb[0], va[0], R)
    spots = []; nt = int(n_spots * tandem_ratio / 2); ns = n_spots - nt * 2
    per_side = ns // 3; rem = ns % 3; counts = [per_side + (1 if i < rem else 0) for i in range(3)]
    for si, (a, b) in enumerate([(0, 1), (1, 2), (2, 0)]):
        va, vb = vs[a], vs[b]; count = counts[si]
        for i in range(count):
            tv = (i + 1) / (count + 1); cx = va[1] + (vb[1] - va[1]) * tv; cy = va[2] + (vb[2] - va[2]) * tv
            nx = -(vb[2] - va[2]); ny = vb[1] - va[1]; nl = _m.hypot(nx, ny) or 1
            ox = cx + nx / nl * 3; oy = cy + ny / nl * 3
            sid = f"S{si}{i:02d}"; _an(net, sid, NodeType.PARKING_SPOT, ox, oy, SpotType.STANDALONE, sid, 1)
            net.add_edge(va[0], sid, 3); net.add_edge(sid, va[0], 3); spots.append(Spot(sid, SpotType.STANDALONE, sid, sid, 1))
    for g in range(nt):
        gid = f"TG{g+1}"; a, b = [(0, 1), (1, 2), (2, 0)][g % 3]; va, vb = vs[a], vs[b]
        tv = 0.3 + g * 0.15; cx = va[1] + (vb[1] - va[1]) * tv; cy = va[2] + (vb[2] - va[2]) * tv
        nx = -(vb[2] - va[2]); ny = vb[1] - va[1]; nl = _m.hypot(nx, ny) or 1; prev = va[0]
        for d in range(1, 3):
            sid = f"{gid}-{d}"; ox = cx + nx / nl * (3 + d * 3.5); oy = cy + ny / nl * (3 + d * 3.5)
            _an(net, sid, NodeType.PARKING_SPOT, ox, oy, SpotType.TANDEM, gid, d)
            net.add_edge(prev, sid, 3.5); net.add_edge(sid, prev, 3.5); prev = sid; spots.append(Spot(sid, SpotType.TANDEM, sid, gid, d))
    return net, spots


def build_circle(n_spots, tandem_ratio):
    import math as _m
    R = 22
    net = RoadNetwork(); _an(net, "ENTRY", NodeType.ENTRY, 0, 0); rns = []
    for a in range(8):
        ang = a * _m.pi * 2 / 8; nid = f"R{a}"; _an(net, nid, NodeType.ROAD_NODE, R * _m.cos(ang), R * _m.sin(ang)); rns.append(nid)
    net.add_edge("ENTRY", rns[0], R)
    for i in range(8):
        j = (i + 1) % 8; net.add_edge(rns[i], rns[j], R * _m.pi / 4); net.add_edge(rns[j], rns[i], R * _m.pi / 4)
    spots = []; nt = int(n_spots * tandem_ratio / 2); ns = n_spots - nt * 2
    for i in range(ns):
        ang = (i + 0.5) * _m.pi * 2 / max(ns, 1); sid = f"C{i:02d}"; ox = (R + 4) * _m.cos(ang); oy = (R + 4) * _m.sin(ang)
        _an(net, sid, NodeType.PARKING_SPOT, ox, oy, SpotType.STANDALONE, sid, 1)
        net.add_edge(rns[i % 8], sid, 4); net.add_edge(sid, rns[i % 8], 4); spots.append(Spot(sid, SpotType.STANDALONE, sid, sid, 1))
    for g in range(nt):
        gid = f"CG{g+1}"; ang = g * _m.pi * 2 / max(nt, 1) + 0.2; rn = rns[g % 8]
        bx = (R + 4) * _m.cos(ang); by = (R + 4) * _m.sin(ang); prev = rn
        for d in range(1, 3):
            sid = f"{gid}-{d}"; ox = bx + d * 3.5 * _m.cos(ang); oy = by + d * 3.5 * _m.sin(ang)
            _an(net, sid, NodeType.PARKING_SPOT, ox, oy, SpotType.TANDEM, gid, d)
            net.add_edge(prev, sid, 3.5); net.add_edge(sid, prev, 3.5); prev = sid; spots.append(Spot(sid, SpotType.TANDEM, sid, gid, d))
    return net, spots


LAYOUT_BUILDERS.update({"linear": build_linear, "rectangle": build_rectangle,
                         "lshape": build_lshape, "triangle": build_triangle,
                         "circle": build_circle})


def build_layout_from_json(data):
    """从 JSON 数据构建 RoadNetwork + spots 列表"""
    net = RoadNetwork()
    spots = []
    node_map = {}
    for nd in data["nodes"]:
        nid = nd["id"]
        ntype = {"entry": NodeType.ENTRY, "exit": NodeType.EXIT,
                 "road": NodeType.ROAD_NODE, "spot": NodeType.PARKING_SPOT}[nd["type"]]
        stype = None; sgroup = None; sdepth = None
        if nd["type"] == "spot":
            stype = SpotType.STANDALONE if nd.get("spot_type") == "standalone" else SpotType.TANDEM
            sgroup = nd.get("group", nid)
            sdepth = int(nd.get("depth", 1))
        net.add_node(RoadNode(nid, ntype, nd["x"], nd["y"], stype, sgroup, sdepth))
        node_map[nid] = nd
        if nd["type"] == "spot":
            spots.append(Spot(nid, stype, nid, sgroup or nid, sdepth or 1))
    for ed in data["edges"]:
        net.add_edge(ed["from"], ed["to"], ed["distance"])
    return net, spots


# ═══════════════════════════════════════════════════════════
# 仿真运行（本机 worker 与云端 UI 共用）
# ═══════════════════════════════════════════════════════════
def run_single(net, spots, vehicles, strategy, seed, wait_policy="fifo",
               car_speed=1.39, max_wait_time=1800):
    # 重置车位状态，避免多次运行时复用污染（compare_all 循环会复用 spots）
    for s in spots:
        s.is_occupied = False
        s.occupied_by = None
    pe = PathEngine(net); lot = ParkingLot(spots)
    engine = SimulationEngine(lot, pe, vehicles, strategy, seed=seed, wait_policy=wait_policy,
                              car_speed=car_speed, max_wait_time=max_wait_time)
    t0 = time.time(); events = engine.run()
    m = compute_metrics(events, len(spots)); m["runtime_s"] = round(time.time() - t0, 3)
    m["strategy"] = strategy.name; return m, events, lot


# 计数类指标（次数）：多种子取平均后四舍五入为整数，避免显示成小数
COUNT_FIELDS = {"shift_count", "rejected_count", "buffer_failed_count"}


def _avg_metrics(metrics_list):
    """对多个 metrics dict 取平均：数值字段求均值，非数值字段保留第一个（用于多 seed 统计）。
    计数类字段（移位/拒绝/缓冲失败次数）取平均后四舍五入为整数。"""
    if not metrics_list:
        return None
    first = metrics_list[0]
    avg = dict(first)
    for k, v in first.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            vals = [m[k] for m in metrics_list if isinstance(m.get(k), (int, float))]
            if vals:
                mean = sum(vals) / len(vals)
                avg[k] = int(mean + 0.5) if k in COUNT_FIELDS else round(mean, 4)
    return avg


def _vehicle_to_dict(v) -> dict:
    """Vehicle → 可 JSON 序列化的 dict（本地计算任务回传用）。"""
    return {
        "vehicle_id": v.vehicle_id,
        "arrival_time": float(getattr(v, "arrival_time", 0.0) or 0.0),
        "parking_duration": float(getattr(v, "parking_duration", 0.0) or 0.0),
        "estimated_duration": float(getattr(v, "estimated_duration", 0.0) or 0.0),
        "assigned_spot": getattr(v, "assigned_spot", None),
        "rejected": bool(getattr(v, "rejected", False)),
        "wait_start": getattr(v, "wait_start", None),
        "wait_end": getattr(v, "wait_end", None),
        "entry_id": getattr(v, "entry_id", None),
        "exit_id": getattr(v, "exit_id", None),
    }
