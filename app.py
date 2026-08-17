"""智能停车场优化系统 — 多页面导航版"""

import sys, hashlib, json, math, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from auth import login as auth_login, register as auth_register, validate_session
from auth import logout as auth_logout, list_users as auth_list_users
from auth import update_user_role as auth_update_role, delete_user as auth_delete_user
from auth import change_password as auth_change_pw, reset_user_password as auth_reset_pw
from auth import export_users as auth_export_users, import_users as auth_import_users
from auth import set_session_token, get_session_token, clear_session_token, restore_session
from auth import get_preference as auth_get_pref, set_preference as auth_set_pref
from auth import check_supabase_health

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from parking_opt.domain.spot import RoadNetwork, RoadNode, NodeType, Spot, SpotType
from parking_opt.routing.path_engine import PathEngine
from parking_opt.simulation.parking_lot import ParkingLot
from parking_opt.simulation.engine import SimulationEngine
from parking_opt.simulation.arrival import generate_demand
from parking_opt.strategies import StrategyRegistry
from parking_opt.evaluation.metrics import compute_metrics
from parking_opt.optimization.cpsat_baseline import CPSatBaseline
from viz import draw_parking_layout

# ═══════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════
# 策略显示名：从注册表动态生成（新算法在 strategies/__init__.py 登记后自动出现）
STRATEGY_LABELS = {name: cls.label for name, cls in StrategyRegistry.all().items()}
STRATEGY_LABELS["compare_all"] = "全部对比"

# 算法评估指标：显示名 -> (指标字段, 方向, 说明)
# 方向: "max"=越大越好, "min"=越小越好
PRIORITY_METRICS = {
    "满足率": ("satisfaction_rate", "max", "尽可能多的车辆被分配到位"),
    "利用率": ("spatial_utilization", "max", "提高车位时空利用率"),
    "平均等待": ("avg_wait_time_s", "min", "减少车辆排队等待时间"),
    "移位次数": ("shift_count", "min", "减少纵深移位的次数"),
    "移位距离": ("shift_distance_m", "min", "减少移位产生的额外行驶成本"),
    "行驶距离": ("total_drive_distance_m", "min", "降低车辆整体行驶成本"),
    "运行耗时": ("runtime_s", "min", "保证算法实时可用"),
}
# 默认优先级顺序（从高到低）
DEFAULT_PRIORITY = ["满足率", "利用率", "平均等待", "移位次数", "移位距离", "行驶距离", "运行耗时"]

# 各策略的算法说明（仿真设置页按当前选择的策略动态展示）
STRATEGY_DESC = {
    "duration_greedy": "**时长感知贪心（主方法）**\n\n"
                       "独立车位优先；纵深车位按**预估停车时长**分内外层——短停（<2小时）优先放外层、"
                       "长停优先放里层，让外层车先走、里层车后走，从而减少移位。同类车位中选距离最近、"
                       "阻挡风险最小的。",
    "greedy": "**贪心（基线）**\n\n"
              "按固定优先级选车位：独立车位 → 纵深外层 → 纵深里层，同类车位中选距离入口最近的。"
              "不利用停车时长信息。",
    "fcfs": "**先到先服务**\n\n"
            "按车位出现的顺序，选第一个可用的空闲车位。",
    "nearest": "**最近路径**\n\n"
               "选距离入口最近的空闲车位，不考虑纵深阻挡风险。",
    "departure_greedy": "**离场贪心**\n\n"
                        "选距离最近的空闲车位，忽略纵深阻挡风险（基线对照用）。",
    "random": "**随机分配**\n\n"
              "从当前空闲车位中随机选一个（基线对照用）。",
    "compare_all": "**全部对比**\n\n"
                   "同时运行以上所有策略（默认参数），按你设定的优先级排序并推荐最优策略。",
    "peak_offpeak_fusion": "**高峰贪心+低谷最近（融合示例）**\n\n"
                           "按当前占用率判断高峰/低谷：占用率高于阈值用高峰算法（默认时长感知贪心），"
                           "否则用低谷算法（默认最近路径）。阈值即「融合比例」，可在下方参数区调节。",
}

ADMIN_USER = "wuhaoyang127"
ROLES = {
    "admin": {"can_configure": True, "can_manage_users": True, "can_run_simulation": True,
              "can_export": True, "can_debug": True, "label": "管理员"},
    "operator": {"can_configure": True, "can_manage_users": False, "can_run_simulation": True,
                 "can_export": True, "can_debug": True, "label": "操作员"},
    "viewer": {"can_configure": False, "can_manage_users": False, "can_run_simulation": True,
               "can_export": False, "can_debug": False, "label": "访客"},
}
LAYOUT_BUILDERS = {}
LAYOUTS = {"linear": "线形", "rectangle": "矩形", "lshape": "L形", "triangle": "三角形", "circle": "环形"}

# 自定义布局 JSON 的最简示例（供「导入布局」页下载参考）
EXAMPLE_LAYOUT = {
    "name": "我的停车场",
    "nodes": [
        {"id": "ENTRY", "type": "entry", "x": 0, "y": 0},
        {"id": "R1", "type": "road", "x": 5, "y": 0},
        {"id": "S01", "type": "spot", "x": 8, "y": 3, "spot_type": "standalone"},
        {"id": "T1-1", "type": "spot", "x": 8, "y": -3, "spot_type": "tandem", "group": "T1", "depth": 1},
        {"id": "T1-2", "type": "spot", "x": 11, "y": -3, "spot_type": "tandem", "group": "T1", "depth": 2},
    ],
    "edges": [
        {"from": "ENTRY", "to": "R1", "distance": 5},
        {"from": "R1", "to": "S01", "distance": 3},
        {"from": "S01", "to": "R1", "distance": 3},
        {"from": "R1", "to": "T1-1", "distance": 3},
        {"from": "T1-1", "to": "T1-2", "distance": 3},
        {"from": "T1-2", "to": "T1-1", "distance": 3},
        {"from": "T1-1", "to": "R1", "distance": 3},
        {"from": "R1", "to": "ENTRY", "distance": 5},
    ],
}

GLOBAL_CSS = """
<style>
:root { --primary: #1a2332; --accent: #3b82f6; --bg: #f1f5f9; --card: #fff; --text: #1e293b;
    --muted: #64748b; --border: #e2e8f0; --radius: 10px; --shadow: 0 1px 3px rgba(0,0,0,.06); }
.stApp { background: var(--bg); }
h1 { font-size: 1.5rem!important; font-weight: 700!important; color: var(--primary)!important; }
h2 { font-size: 1.15rem!important; font-weight: 600!important; color: var(--primary)!important; }
.metric-card { background: var(--card); border-radius: var(--radius); padding: .6rem .7rem;
    box-shadow: var(--shadow); text-align: center; border-top: 3px solid var(--accent); }
.metric-card .val { font-size: 1.3rem; font-weight: 700; color: var(--primary); }
.metric-card .lbl { font-size: .68rem; color: var(--muted); }
.metric-card.warn { border-top-color: #f59e0b; } .metric-card.bad { border-top-color: #ef4444; }
.metric-card.good { border-top-color: #22c55e; }
section[data-testid="stSidebar"] { background: linear-gradient(180deg, #0f172a, #1e3a5f); }
/* 全侧边栏文字亮色 + 放大 */
section[data-testid="stSidebar"] * { color: #f1f5f9!important; font-size: 1.05rem!important; }
section[data-testid="stSidebar"] .stRadio label {
    font-size: 1.7rem!important; padding: .9rem 1.1rem!important; border-radius: 10px!important;
    margin-bottom: 6px!important; transition: all 0.15s!important; }
/* 悬停 */
section[data-testid="stSidebar"] .stRadio div[role="radiogroup"] label:hover {
    background: rgba(255,255,255,.12)!important; }
/* 选中 - 只加光圈，无填充 */
section[data-testid="stSidebar"] .stRadio div[role="radiogroup"] label[data-selected="true"] {
    background: transparent!important; color: #22d3ee!important;
    font-weight: 700!important; font-size: 1.8rem!important;
    border: 2px solid #22d3ee!important;
    box-shadow: 0 0 12px rgba(34,211,238,.35), inset 0 0 6px rgba(34,211,238,.1)!important; }
section[data-testid="stSidebar"] .stRadio div[role="radiogroup"] label[data-selected="true"] * {
    color: #22d3ee!important; background: transparent!important; }
/* 按钮 */
section[data-testid="stSidebar"] .stButton>button { background: rgba(255,255,255,.08)!important;
    border: 1px solid rgba(255,255,255,.15)!important; border-radius: 9px!important;
    font-size: 1.1rem!important; padding: .6rem 1.1rem!important; }
section[data-testid="stSidebar"] .stButton>button:hover { background: rgba(255,255,255,.18)!important;
    border-color: rgba(34,211,238,.5)!important; }
.stButton>button[kind="primary"] { background: linear-gradient(135deg, #3b82f6, #2563eb)!important;
    border: none!important; border-radius: 8px!important; font-weight: 600!important; color: white!important; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: var(--radius);
    padding: .7rem; margin-bottom: .4rem; box-shadow: var(--shadow); }
hr { margin: .4rem 0; border-color: var(--border); }
</style>
"""

# ═══════════════════════════════════════════════════════════
# 停车场布局构建器
# ═══════════════════════════════════════════════════════════
def _an(net, nid, nt, x, y, st=None, sg=None, dp=None):
    net.add_node(RoadNode(nid, nt, x, y, st, sg, dp))

def build_linear(n_spots, tandem_ratio):
    net = RoadNetwork(); _an(net,"ENTRY",NodeType.ENTRY,0,0); _an(net,"N0",NodeType.ROAD_NODE,5,0)
    net.add_edge("ENTRY","N0",5); spots=[]; nt=int(n_spots*tandem_ratio/2); ns=n_spots-nt*2
    for i in range(ns):
        sid=f"A{i+1:02d}"; _an(net,sid,NodeType.PARKING_SPOT,8+i*5,3,SpotType.STANDALONE,sid,1)
        net.add_edge("N0",sid,3+i*5); net.add_edge(sid,"N0",3+i*5); spots.append(Spot(sid,SpotType.STANDALONE,sid,sid,1))
    for g in range(nt):
        gid=f"G{g+1}"; prev="N0"
        for d in range(1,3):
            sid=f"{gid}-{d}"; _an(net,sid,NodeType.PARKING_SPOT,30+g*8+d*4,3,SpotType.TANDEM,gid,d)
            net.add_edge(prev,sid,4); net.add_edge(sid,prev,4); prev=sid; spots.append(Spot(sid,SpotType.TANDEM,sid,gid,d))
    return net,spots

def build_rectangle(n_spots,tandem_ratio):
    net=RoadNetwork();_an(net,"ENTRY",NodeType.ENTRY,0,0)
    _an(net,"M",NodeType.ROAD_NODE,8,0);_an(net,"U",NodeType.ROAD_NODE,8,6);_an(net,"D",NodeType.ROAD_NODE,8,-6)
    for a,b,d in[("ENTRY","M",8),("M","U",6),("M","D",6),("U","M",6),("D","M",6)]:net.add_edge(a,b,d)
    spots=[];half=n_spots//2;nt=int(half*tandem_ratio/2);ns=half-nt*2
    for row,rd,ys in[("U","U",1),("D","D",-1)]:
        for i in range(ns):
            sid=f"{row}{i+1:02d}";x=12+i*4.5;y=ys*9
            _an(net,sid,NodeType.PARKING_SPOT,x,y,SpotType.STANDALONE,sid,1)
            net.add_edge(rd,sid,3);net.add_edge(sid,rd,3);spots.append(Spot(sid,SpotType.STANDALONE,sid,sid,1))
        for g in range(nt):
            gid=f"{row}G{g+1}";prev=rd;bx=12+ns*4.5+g*7;by=ys*9
            for d in range(1,3):
                sid=f"{gid}-{d}";_an(net,sid,NodeType.PARKING_SPOT,bx+d*3.5,by,SpotType.TANDEM,gid,d)
                net.add_edge(prev,sid,3.5);net.add_edge(sid,prev,3.5);prev=sid;spots.append(Spot(sid,SpotType.TANDEM,sid,gid,d))
    return net,spots

def build_lshape(n_spots,tandem_ratio):
    net=RoadNetwork();_an(net,"ENTRY",NodeType.ENTRY,0,0);_an(net,"C",NodeType.ROAD_NODE,30,0)
    _an(net,"V",NodeType.ROAD_NODE,30,20)
    for a,b,d in[("ENTRY","C",30),("C","V",20),("V","C",20),("C","ENTRY",30)]:net.add_edge(a,b,d)
    spots=[];nt=int(n_spots*tandem_ratio/2);ns=n_spots-nt*2;hh=ns//2;vh=ns-hh
    for i in range(hh):
        sid=f"H{i+1:02d}";_an(net,sid,NodeType.PARKING_SPOT,5+i*5,4,SpotType.STANDALONE,sid,1)
        net.add_edge("ENTRY",sid,i*5+5);net.add_edge(sid,"ENTRY",i*5+5);spots.append(Spot(sid,SpotType.STANDALONE,sid,sid,1))
    for i in range(vh):
        sid=f"V{i+1:02d}";_an(net,sid,NodeType.PARKING_SPOT,34,5+i*5,SpotType.STANDALONE,sid,1)
        net.add_edge("V",sid,i*5+5);net.add_edge(sid,"V",i*5+5);spots.append(Spot(sid,SpotType.STANDALONE,sid,sid,1))
    for g in range(nt):
        gid=f"TG{g+1}";prev="C";bx=34+g*7
        for d in range(1,3):
            sid=f"{gid}-{d}";_an(net,sid,NodeType.PARKING_SPOT,bx+d*3.5,24,SpotType.TANDEM,gid,d)
            net.add_edge(prev,sid,3.5);net.add_edge(sid,prev,3.5);prev=sid;spots.append(Spot(sid,SpotType.TANDEM,sid,gid,d))
    return net,spots

def build_triangle(n_spots,tandem_ratio):
    import math as _m;R=25
    net=RoadNetwork();vs=[("V0",0,0),("V1",R,0),("V2",R*0.5,R*0.866)]
    for vid,vx,vy in vs:_an(net,vid,NodeType.ROAD_NODE if vid!="V0" else NodeType.ENTRY,vx,vy)
    for a,b in[(0,1),(1,2),(2,0)]:va,vb=vs[a],vs[b];net.add_edge(va[0],vb[0],R);net.add_edge(vb[0],va[0],R)
    spots=[];nt=int(n_spots*tandem_ratio/2);ns=n_spots-nt*2
    per_side=ns//3;rem=ns%3;counts=[per_side+(1 if i<rem else 0) for i in range(3)]
    for si,(a,b) in enumerate([(0,1),(1,2),(2,0)]):
        va,vb=vs[a],vs[b];count=counts[si]
        for i in range(count):
            tv=(i+1)/(count+1);cx=va[1]+(vb[1]-va[1])*tv;cy=va[2]+(vb[2]-va[2])*tv
            nx=-(vb[2]-va[2]);ny=vb[1]-va[1];nl=_m.hypot(nx,ny)or 1
            ox=cx+nx/nl*3;oy=cy+ny/nl*3
            sid=f"S{si}{i:02d}";_an(net,sid,NodeType.PARKING_SPOT,ox,oy,SpotType.STANDALONE,sid,1)
            net.add_edge(va[0],sid,3);net.add_edge(sid,va[0],3);spots.append(Spot(sid,SpotType.STANDALONE,sid,sid,1))
    for g in range(nt):
        gid=f"TG{g+1}";a,b=[(0,1),(1,2),(2,0)][g%3];va,vb=vs[a],vs[b]
        tv=0.3+g*0.15;cx=va[1]+(vb[1]-va[1])*tv;cy=va[2]+(vb[2]-va[2])*tv
        nx=-(vb[2]-va[2]);ny=vb[1]-va[1];nl=_m.hypot(nx,ny)or 1;prev=va[0]
        for d in range(1,3):
            sid=f"{gid}-{d}";ox=cx+nx/nl*(3+d*3.5);oy=cy+ny/nl*(3+d*3.5)
            _an(net,sid,NodeType.PARKING_SPOT,ox,oy,SpotType.TANDEM,gid,d)
            net.add_edge(prev,sid,3.5);net.add_edge(sid,prev,3.5);prev=sid;spots.append(Spot(sid,SpotType.TANDEM,sid,gid,d))
    return net,spots

def build_circle(n_spots,tandem_ratio):
    import math as _m;R=22
    net=RoadNetwork();_an(net,"ENTRY",NodeType.ENTRY,0,0);rns=[]
    for a in range(8):
        ang=a*_m.pi*2/8;nid=f"R{a}";_an(net,nid,NodeType.ROAD_NODE,R*_m.cos(ang),R*_m.sin(ang));rns.append(nid)
    net.add_edge("ENTRY",rns[0],R)
    for i in range(8):j=(i+1)%8;net.add_edge(rns[i],rns[j],R*_m.pi/4);net.add_edge(rns[j],rns[i],R*_m.pi/4)
    spots=[];nt=int(n_spots*tandem_ratio/2);ns=n_spots-nt*2
    for i in range(ns):
        ang=(i+0.5)*_m.pi*2/max(ns,1);sid=f"C{i:02d}";ox=(R+4)*_m.cos(ang);oy=(R+4)*_m.sin(ang)
        _an(net,sid,NodeType.PARKING_SPOT,ox,oy,SpotType.STANDALONE,sid,1)
        net.add_edge(rns[i%8],sid,4);net.add_edge(sid,rns[i%8],4);spots.append(Spot(sid,SpotType.STANDALONE,sid,sid,1))
    for g in range(nt):
        gid=f"CG{g+1}";ang=g*_m.pi*2/max(nt,1)+0.2;rn=rns[g%8]
        bx=(R+4)*_m.cos(ang);by=(R+4)*_m.sin(ang);prev=rn
        for d in range(1,3):
            sid=f"{gid}-{d}";ox=bx+d*3.5*_m.cos(ang);oy=by+d*3.5*_m.sin(ang)
            _an(net,sid,NodeType.PARKING_SPOT,ox,oy,SpotType.TANDEM,gid,d)
            net.add_edge(prev,sid,3.5);net.add_edge(sid,prev,3.5);prev=sid;spots.append(Spot(sid,SpotType.TANDEM,sid,gid,d))
    return net,spots

LAYOUT_BUILDERS.update({"linear":build_linear,"rectangle":build_rectangle,"lshape":build_lshape,
                         "triangle":build_triangle,"circle":build_circle})

# ═══════════════════════════════════════════════════════════
# 仿真 & 时间轴工具函数
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
    m = compute_metrics(events, len(spots)); m["runtime_s"] = round(time.time()-t0, 3)
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
    for m in all_m:
        nm = STRATEGY_LABELS.get(m["strategy"], m["strategy"])
        vals = [norm[d[0]][i] for i, d in enumerate(dims)]
        fig.add_trace(go.Scatterpolar(r=vals + [vals[0]], theta=labels + [labels[0]],
                                      name=nm, fill="toself", opacity=0.45))
    fig.update_layout(height=420, margin=dict(l=50, r=50, t=50, b=50),
                      legend=dict(orientation="h", yanchor="bottom", y=-0.15),
                      polar=dict(radialaxis=dict(range=[0, 1], showticklabels=False)))
    return fig


def build_timeline(events, net, pe):
    vehicles_tl = {}; events_by_time = {}
    for e in events:
        events_by_time.setdefault(e.time, []).append(e)
        vid = e.vehicle_id
        if not vid: continue
        if vid not in vehicles_tl:
            vehicles_tl[vid] = {"arrival_time": None, "assigned_time": None, "spot_entry_time": None,
                "departure_start": None, "departure_end": None, "spot_id": None,
                "path_nodes": None, "rejected": False, "shifts": []}
        tl = vehicles_tl[vid]; et = e.event_type.value
        if et == "vehicle_arrival": tl["arrival_time"] = e.time
        elif et == "parking_assigned":
            tl["assigned_time"] = e.time; tl["spot_id"] = e.spot_id
            try: tl["path_nodes"] = pe.shortest_path(pe.entry_id, e.spot_id)
            except: tl["path_nodes"] = [pe.entry_id, e.spot_id]
        elif et == "spot_entry": tl["spot_entry_time"] = e.time
        elif et == "departure":
            tl["departure_start"] = e.time
            if not e.metadata.get("had_blocking"): tl["departure_end"] = e.time
        elif et == "shift_start":
            tl["shifts"].append({"from": e.metadata.get("from_spot"), "to": e.metadata.get("to_spot"),
                                "start": e.time, "end": None})
            if tl["departure_start"] is None: tl["departure_start"] = e.time
        elif et == "shift_end":
            if tl["shifts"]: tl["shifts"][-1]["end"] = e.time
            tl["departure_end"] = e.time
        elif et == "rejected": tl["rejected"] = True
    all_times = sorted(set(e.time for e in events))
    if all_times and all_times[0] > 0: all_times.insert(0, 0.0)
    return {"all_times": all_times, "max_time": all_times[-1] if all_times else 0,
            "vehicles": vehicles_tl, "events_by_time": events_by_time}

def replay_state(events_raw, t, spots, net):
    ss = {s.spot_id: {"occ": False, "by": "", "blocked": False} for s in spots}
    dv = []; v_spot = {}; v_entered = {}; v_departing = {}
    for e in events_raw:
        if e["time"] > t: break
        vid = str(e.get("vehicle_id", ""))
        if not vid: continue
        et = e["type"]
        if et == "vehicle_arrival": v_spot[vid] = None; v_entered[vid] = False; v_departing[vid] = False
        elif et == "parking_assigned": v_spot[vid] = e.get("spot_id", "")
        elif et == "spot_entry": v_entered[vid] = True
        elif et in ("departure", "shift_start", "shift_end"): v_departing[vid] = True
        elif et == "rejected": v_spot.pop(vid, None); v_entered.pop(vid, None); v_departing.pop(vid, None)
    for vid, spot_id in v_spot.items():
        if spot_id and v_entered.get(vid) and not v_departing.get(vid):
            if spot_id in ss: ss[spot_id]["occ"] = True; ss[spot_id]["by"] = vid
    for vid, spot_id in v_spot.items():
        if spot_id and not v_entered.get(vid) and not v_departing.get(vid):
            nx, ny = 0.0, 0.0
            if spot_id in net.nodes: nd = net.nodes[spot_id]; nx, ny = nd.x, nd.y
            dv.append({"vid": vid, "x": nx, "y": ny, "st": "驶入", "target": spot_id})
    sg = {}
    for s in spots: sg.setdefault(s.stack_group_id, []).append(s)
    for g, grp in sg.items():
        grp.sort(key=lambda s: s.depth)
        for i, inner in enumerate(grp):
            for j in range(i):
                if ss[grp[j].spot_id]["occ"] and ss[inner.spot_id]["occ"]:
                    ss[inner.spot_id]["blocked"] = True
    return {"ss": ss, "dv": dv}

def interp_vehicle_pos(net, events_raw, vid, t):
    """计算车辆 vid 在时刻 t 的平滑插值位置 (x, y)"""
    veh_ev = []
    for e in events_raw:
        ev_vid = e.get("vehicle_id", "")
        # 宽松匹配：支持 int/str 混合
        if str(ev_vid) == str(vid) or ev_vid == vid:
            veh_ev.append(e)
    veh_ev.sort(key=lambda e: e["time"])

    assigned_t, spot_id, entry_t = None, None, None
    for e in veh_ev:
        et = e["type"]
        sid = e.get("spot_id", "")
        # 查找任何分配/进入事件
        if et in ("parking_assigned", "spot_entry") and assigned_t is None:
            assigned_t = e["time"]
            if sid: spot_id = sid
        elif et == "spot_entry" and assigned_t is not None:
            entry_t = e["time"]
            break
        elif et == "departure" and assigned_t is not None:
            break  # 后面不再需要

    # 如果还是没找到分配事件，尝试从任意有 spot_id 的事件推断
    if assigned_t is None:
        for e in veh_ev:
            sid = e.get("spot_id", "")
            if sid:
                assigned_t = e["time"]; spot_id = sid; break

    en = next((n for n in net.nodes.values() if n.node_type == NodeType.ENTRY), None)
    ep = (en.x, en.y) if en else (0.0, 0.0)

    # 没找到任何分配 → 入口位置
    if assigned_t is None or not spot_id:
        return ep

    # 还没到分配时间 → 入口
    if t < assigned_t:
        return ep

    # 获取路径
    path = None
    if "sim_pe" in st.session_state:
        try:
            pe = st.session_state.sim_pe
            path = pe.shortest_path(pe.entry_id, spot_id)
        except Exception:
            path = None
    if not path:
        path = ["ENTRY", spot_id]

    # 计算到达时间（如果没找到确切 entry 事件，估算）
    if entry_t is None or entry_t <= assigned_t:
        # 按路径长度估算：每单位距离 0.5 秒
        total_dist = 0.0
        for i in range(len(path) - 1):
            fn = net.nodes.get(path[i]); tn = net.nodes.get(path[i + 1])
            if fn and tn:
                total_dist += math.hypot(tn.x - fn.x, tn.y - fn.y)
        entry_t = assigned_t + max(total_dist * 0.5, 2.0)

    # 行驶阶段
    if t < entry_t and path and len(path) >= 2:
        dur = max(entry_t - assigned_t, 0.5)
        prog = min(max((t - assigned_t) / dur, 0.0), 1.0)
        return _interp_path(net, path, prog)

    # 已停入 → 返回车位位置
    nd = net.nodes.get(spot_id)
    return (nd.x, nd.y) if nd else ep

def _interp_path(net, nodes, prog):
    segs, total = [], 0.0
    for i in range(len(nodes)-1):
        fn = net.nodes.get(nodes[i]); tn = net.nodes.get(nodes[i+1])
        if fn and tn:
            sl = max(math.hypot(tn.x-fn.x, tn.y-fn.y), 0.01)
            segs.append((fn, tn, sl)); total += sl
    if total == 0: return (0.0, 0.0)
    target = prog * total; acc = 0.0
    for fn, tn, sl in segs:
        if acc + sl >= target:
            sp = (target-acc)/sl
            return (fn.x+(tn.x-fn.x)*sp, fn.y+(tn.y-fn.y)*sp)
        acc += sl
    l = segs[-1]; return (l[1].x, l[1].y)

def build_layout_from_json(data):
    """从 JSON 数据构建 RoadNetwork + spots 列表"""
    net = RoadNetwork()
    spots = []
    node_map = {}
    for nd in data["nodes"]:
        nid = nd["id"]
        ntype = {"entry": NodeType.ENTRY, "road": NodeType.ROAD_NODE, "spot": NodeType.PARKING_SPOT}[nd["type"]]
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
# 认证 & 登录
# ═══════════════════════════════════════════════════════════
def _load_priority_preference():
    """登录/恢复会话后，从 Supabase 加载用户的算法优先级设置"""
    token = st.session_state.get("token")
    if not token:
        return
    try:
        val = auth_get_pref(token, "algorithm_priority")
        if val:
            order = json.loads(val)
            order = [n for n in order if n in PRIORITY_METRICS]
            # 补充缺失的指标（按默认顺序追加），兼容旧版本保存的配置
            for n in DEFAULT_PRIORITY:
                if n not in order:
                    order.append(n)
            if order:
                st.session_state.priority_order = order
    except Exception:
        pass


def check_login():
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False; st.session_state.username = None
        st.session_state.role = None; st.session_state.token = None
    if not st.session_state.logged_in and not st.session_state.token:
        restored = restore_session()
        if restored:
            st.session_state.logged_in = True
            st.session_state.username = restored["username"]
            st.session_state.role = restored["role"]
            st.session_state.token = restored["token"]
            _load_priority_preference()
    if "login_fails" not in st.session_state:
        st.session_state.login_fails = 0
        st.session_state.login_blocked_until = 0.0
    if not st.session_state.logged_in:
        st.markdown('<div style="text-align:center;padding:3rem 0 1rem"><div style="font-size:3rem">🚗</div>'
            '<h1 style="border:none;font-size:1.6rem!important">智能停车场优化系统</h1>'
            '<p style="color:#64748b">车位分配 · 纵深移位 · 仿真对比</p></div>', unsafe_allow_html=True)
        c1, c2, c3 = st.columns([1, 2.5, 1])
        with c2:
            if time.time() < st.session_state.login_blocked_until:
                wait = int(st.session_state.login_blocked_until - time.time()) + 1
                st.error(f"⏳ 尝试次数过多，请 {wait} 秒后再试")
                st.stop()
            tab_login, tab_register = st.tabs(["登录", "注册"])
            with tab_login:
                username = st.text_input("用户名", key="login_user").strip()
                password = st.text_input("密码", type="password", key="login_pw").strip()
                if st.button("登录", type="primary", use_container_width=True):
                    res = auth_login(username, password)
                    if res.get("success"):
                        st.session_state.logged_in = True
                        st.session_state.username = res["username"]
                        st.session_state.role = res["role"]
                        st.session_state.token = res["token"]
                        st.session_state.login_fails = 0
                        set_session_token(res["token"])
                        _load_priority_preference()
                        st.rerun()
                    else:
                        st.session_state.login_fails += 1
                        if st.session_state.login_fails >= 3:
                            st.session_state.login_blocked_until = time.time() + 30
                        st.error(res.get("error", "用户名或密码错误"))
            with tab_register:
                reg_user = st.text_input("新用户名", key="reg_user").strip()
                reg_pw = st.text_input("密码", type="password", key="reg_pw").strip()
                reg_pw2 = st.text_input("确认密码", type="password", key="reg_pw2").strip()
                if st.button("注册", use_container_width=True):
                    if not reg_user or not reg_pw: st.error("请填写用户名和密码")
                    elif reg_pw != reg_pw2: st.error("两次密码不一致")
                    else:
                        res = auth_register(reg_user, reg_pw)
                        if res.get("success"): st.success("注册成功！请切换到登录标签页")
                        else: st.error(res.get("error", "注册失败"))
        st.stop()

# ═══════════════════════════════════════════════════════════
# 页面渲染函数
# ═══════════════════════════════════════════════════════════
# 环境参数（引擎 + 需求生成）声明：与策略参数一样，网页渲染为可调控件
ENV_PARAM_SPECS = [
    {"key": "car_speed", "label": "车速(m/s)", "type": "float",
     "min": 0.5, "max": 5.0, "step": 0.1, "default": 1.39,
     "help": "车辆行驶速度，影响行驶/移位时间"},
    {"key": "max_wait_time", "label": "排队等待上限(秒)", "type": "int",
     "min": 60, "max": 7200, "step": 60, "default": 1800,
     "help": "车位满时车辆排队等待的最长时间"},
    {"key": "sim_duration", "label": "仿真时长(秒)", "type": "int",
     "min": 3600, "max": 86400, "step": 600, "default": 21600,
     "help": "仿真总时长（默认6小时）"},
    {"key": "duration_min", "label": "停车时长下限(秒)", "type": "int",
     "min": 60, "max": 7200, "step": 60, "default": 600,
     "help": "车辆停车时长范围下限"},
    {"key": "duration_max", "label": "停车时长上限(秒)", "type": "int",
     "min": 600, "max": 14400, "step": 300, "default": 7200,
     "help": "车辆停车时长范围上限"},
    {"key": "peak_ratio", "label": "高峰车辆占比", "type": "float",
     "min": 0.0, "max": 1.0, "step": 0.05, "default": 0.7,
     "help": "高峰时段到达的车辆占比"},
    {"key": "error_ratio", "label": "时长预估误差(±)", "type": "float",
     "min": 0.0, "max": 0.9, "step": 0.05, "default": 0.3,
     "help": "预估停车时长相较真实时长的误差比例"},
]


def _render_param_widget(p, prefix, disabled):
    """按单个参数声明渲染控件，返回参数值。prefix 用于生成唯一 widget key。"""
    key = p["key"]
    label = p.get("label", key)
    help_text = p.get("help")
    ptype = p.get("type", "float")
    default = p.get("default")
    wkey = f"{prefix}_{key}"
    if ptype == "int":
        return st.slider(label, int(p.get("min", 0)), int(p.get("max", 100)),
                         int(default if default is not None else p.get("min", 0)),
                         int(p.get("step", 1)), key=wkey, disabled=disabled, help=help_text)
    if ptype == "float":
        return st.slider(label, float(p.get("min", 0.0)), float(p.get("max", 1.0)),
                         float(default if default is not None else p.get("min", 0.0)),
                         float(p.get("step", 0.1)), key=wkey, disabled=disabled, help=help_text)
    if ptype == "choice":
        options = p.get("options", [])
        opts = [o[0] for o in options] if options else []
        fmt = {o[0]: o[1] for o in options} if options else {}
        idx = opts.index(default) if default in opts else 0
        return st.selectbox(label, opts, index=idx, format_func=lambda v: fmt.get(v, v),
                            key=wkey, disabled=disabled, help=help_text)
    if ptype == "bool":
        return st.checkbox(label, bool(default), key=wkey, disabled=disabled, help=help_text)
    if ptype == "strategy":
        names = list(StrategyRegistry.all().keys())
        fmt = {n: StrategyRegistry.get(n).label for n in names}
        idx = names.index(default) if default in names else 0
        return st.selectbox(label, names, index=idx, format_func=lambda v: fmt.get(v, v),
                            key=wkey, disabled=disabled, help=help_text)
    return None


def render_strategy_params(strategy_name, disabled=False):
    """渲染某策略的全部参数控件，返回 {key: value}。"""
    params = {}
    for p in StrategyRegistry.specs(strategy_name):
        params[p["key"]] = _render_param_widget(p, f"sp_{strategy_name}", disabled)
    return params


def render_env_params(disabled=False):
    """渲染环境参数（引擎 + 需求）控件，返回 {key: value}。"""
    params = {}
    for p in ENV_PARAM_SPECS:
        params[p["key"]] = _render_param_widget(p, "env", disabled)
    return params


def render_settings(role):
    """页面1: 仿真设置"""
    st.subheader("⚙️ 仿真参数配置")
    disabled = not role["can_configure"]
    if disabled: st.caption("⚠️ 当前角色仅可查看，不可修改参数")

    c1, c2 = st.columns(2)
    with c1:
        layout_keys = list(LAYOUTS.keys()) + list(LAYOUT_BUILDERS.keys() - set(LAYOUTS.keys()))
        layout_labels = {**LAYOUTS, **{k: k for k in LAYOUT_BUILDERS if k not in LAYOUTS}}
        layout = st.selectbox("停车场布局", layout_keys,
                              format_func=lambda x: layout_labels.get(x, x),
                              disabled=disabled)
        n_spots = st.slider("车位数", 5, 50, 15, disabled=disabled)
        tandem_ratio = st.slider("纵深比例", 0.0, 1.0, 0.5, 0.1, disabled=disabled)
    with c2:
        n_vehicles = st.slider("车辆数", 10, 200, 60, disabled=disabled)
        seed = st.number_input("随机种子", 0, 999, 42, disabled=disabled)
        n_runs = st.slider("仿真次数（多种子取平均）", 1, 10, 3, disabled=disabled,
                           help="随机系统单次结果波动大，多种子取平均更稳定；次数越多越准但越慢")
        wait_policy = st.selectbox("等待调度策略", ["fifo", "shortest"],
                                   format_func=lambda x: "先到先服务（FIFO）" if x == "fifo" else "短停车优先",
                                   help="FIFO 保留各策略差异（对比更明显）；短停车优先能减少等待但策略差异会被抹平")
        strategy_name = st.selectbox("策略", list(STRATEGY_LABELS.keys()),
                                     format_func=lambda x: STRATEGY_LABELS[x])

    with st.expander("📖 算法说明（分配逻辑与拒绝规则）"):
        st.markdown(STRATEGY_DESC.get(strategy_name, "**该算法暂无详细说明**"))
        st.markdown("""
**等待与拒绝规则**

当停车场**所有车位均被占用**时，到达车辆不会立即被拒，而是**排队等待**；若等待超过下方「排队等待上限」仍无空闲车位，才判定为拒绝（计入「拒绝数」指标，等待时长计入「平均等待时间」）。
""")

    # 策略可调参数（按 PARAMS 声明动态渲染）
    if strategy_name != "compare_all" and StrategyRegistry.specs(strategy_name):
        st.markdown("#### 🎛️ 算法参数（可调）")
        strat_params = render_strategy_params(strategy_name, disabled)
    else:
        strat_params = {}

    # 环境参数（引擎 + 需求，可调）
    with st.expander("🌐 环境参数（车速/等待/需求，可调）"):
        env_params = render_env_params(disabled)

    # 停车时长上下限校验：下限不应大于上限
    if env_params["duration_min"] > env_params["duration_max"]:
        st.warning("⚠️ 停车时长下限大于上限，已自动交换")
        env_params["duration_min"], env_params["duration_max"] = \
            env_params["duration_max"], env_params["duration_min"]

    # 算法评估优先级（可自主调整，字典序排序）
    st.markdown("#### 🎯 算法评估优先级")
    st.caption("勾选顺序即优先级（从上到下 = 从高到低）；取消勾选后按新顺序重新勾选即可调整")
    priority_order = st.multiselect(
        "评估指标排序",
        options=list(PRIORITY_METRICS.keys()),
        default=st.session_state.get("priority_order", DEFAULT_PRIORITY),
        key="priority_order_sel",
        format_func=lambda n: f"{n} {'↑越大越好' if PRIORITY_METRICS[n][1]=='max' else '↓越小越好'}",
        disabled=disabled,
    )
    if not priority_order:
        priority_order = DEFAULT_PRIORITY
        st.warning("至少保留一个指标，已恢复默认顺序")
    st.session_state.priority_order = priority_order

    # 优先级变化时保存到 Supabase（登录用户，跨会话持久）
    if st.session_state.get("priority_order_saved") != priority_order:
        token = st.session_state.get("token")
        if token:
            try:
                auth_set_pref(token, "algorithm_priority", json.dumps(priority_order))
                st.session_state.priority_order_saved = priority_order
            except Exception:
                pass

    if st.button("▶️ 运行仿真", type="primary", use_container_width=True,
                 disabled=not role["can_run_simulation"]):
        with st.spinner("仿真运行中..."):
            net, spots = LAYOUT_BUILDERS[layout](n_spots, tandem_ratio)
            pe = PathEngine(net)

            # 需求生成 / 引擎公共参数
            demand_kwargs = dict(total_vehicles=n_vehicles,
                                 sim_duration=env_params["sim_duration"],
                                 duration_min=env_params["duration_min"],
                                 duration_max=env_params["duration_max"],
                                 peak_ratio=env_params["peak_ratio"],
                                 error_ratio=env_params["error_ratio"])
            eng_kwargs = dict(car_speed=env_params["car_speed"],
                              max_wait_time=env_params["max_wait_time"])

            if strategy_name == "compare_all":
                all_m = []
                main_events_raw = None
                for nm, cls in StrategyRegistry.all().items():
                    seed_metrics = []
                    for r in range(n_runs):
                        s = seed + r
                        vehs = generate_demand(seed=s, **demand_kwargs)
                        m, ev, _ = run_single(net, spots, vehs, cls(), s, wait_policy, **eng_kwargs)
                        seed_metrics.append(m)
                        # 主方法事件日志（取第一个种子），供「车辆动态路径」页展示
                        if nm == "duration_greedy" and r == 0:
                            main_events_raw = [{"time": e.time, "type": e.event_type.value,
                                                "vehicle_id": e.vehicle_id or "", "spot_id": e.spot_id or "",
                                                "metadata": dict(e.metadata)} for e in ev]
                    all_m.append(_avg_metrics(seed_metrics))
                st.session_state.sim_all_metrics = all_m
                st.session_state.sim_metrics = next((m for m in all_m if m.get("strategy") == "duration_greedy"), None)
                st.session_state.sim_events_raw = main_events_raw
            else:
                seed_metrics = []
                events_raw = None
                for r in range(n_runs):
                    s = seed + r
                    vehs = generate_demand(seed=s, **demand_kwargs)
                    # 每次新建策略实例（避免有状态策略跨 run 污染）
                    strategy = StrategyRegistry.create(strategy_name, **strat_params)
                    m, ev, _ = run_single(net, spots, vehs, strategy, s, wait_policy, **eng_kwargs)
                    seed_metrics.append(m)
                    if r == 0:
                        events_raw = [{"time": e.time, "type": e.event_type.value,
                                       "vehicle_id": e.vehicle_id or "", "spot_id": e.spot_id or "",
                                       "metadata": dict(e.metadata)} for e in ev]
                avg_m = _avg_metrics(seed_metrics)
                st.session_state.sim_metrics = avg_m
                st.session_state.sim_events_raw = events_raw
                st.session_state.sim_all_metrics = None

                # 记录运行历史（每策略最多保留 5 条，超出删除最旧）
                history = st.session_state.setdefault("run_history", {})
                rec = {
                    "params": strat_params,
                    "env": env_params,
                    "metrics": avg_m,
                    "time": time.strftime("%H:%M:%S"),
                }
                history.setdefault(strategy_name, []).append(rec)
                if len(history[strategy_name]) > 5:
                    history[strategy_name] = history[strategy_name][-5:]
                st.session_state.run_history = history

            st.session_state.sim_net = net
            st.session_state.sim_spots = spots
            st.session_state.sim_pe = pe
            st.session_state.sim_n_spots = n_spots
            st.session_state.sim_n_vehicles = n_vehicles
            st.session_state.sim_seed = seed
            st.session_state.sim_n_runs = n_runs
            st.session_state.sim_strategy_name = strategy_name
            st.session_state.sim_layout = layout

            # 计算理论最优（CP-SAT 离线全信息上界）
            cpsat_rate = None
            try:
                cps_vehs = generate_demand(seed=seed, **demand_kwargs)
                cps_lot = ParkingLot(spots)
                cps_res = CPSatBaseline(cps_lot, pe).solve(cps_vehs)
                if cps_res is not None:
                    cpsat_rate = len(cps_res) / len(cps_vehs)
            except Exception:
                cpsat_rate = None
            st.session_state.sim_cpsat_rate = cpsat_rate

            st.session_state.sim_has_run = True
            # 重置回放状态
            st.session_state.replay_time = 0.0
            st.session_state.replay_playing = False
            st.session_state.selected_vehicle = None
            # 跳到指标分析页面（调参后直接看结果）
            st.session_state.page = "📊 指标分析"
        st.rerun()


def render_system(role):
    """页面2: 系统设置（用户管理 / 数据备份 / 导入布局）"""
    st.subheader("🔧 系统设置")
    tab1, tab2, tab3 = st.tabs(["👥 用户管理", "💾 数据备份", "📐 导入布局"])

    # ── 用户管理 ──
    with tab1:
        if not role["can_manage_users"]:
            st.info("仅管理员可管理用户")
        else:
            users = auth_list_users(st.session_state.token)
            if len(users) <= 1: st.caption("暂无其他注册用户")
            for u_info in users:
                u = u_info.get("username", "")
                ur = u_info.get("role", "viewer")
                if u == ADMIN_USER: continue
                c1, c2, c3, c4 = st.columns([2, 2, 1.5, 1.5])
                c1.write(f"**{u}**")
                new_role = c2.selectbox("角色", ["viewer", "operator"],
                    index=0 if ur == "viewer" else 1, key=f"role_{u}", label_visibility="collapsed")
                if new_role != ur: auth_update_role(st.session_state.token, u, new_role); st.rerun()
                if c3.button("🔑", key=f"rst_{u}", help="重置密码"):
                    st.session_state[f"rst_open_{u}"] = True
                if c4.button("🗑", key=f"del_{u}"):
                    auth_delete_user(st.session_state.token, u); st.rerun()
                if st.session_state.get(f"rst_open_{u}"):
                    rp = st.text_input("新密码", type="password", key=f"rst_pw_{u}")
                    if st.button("确认重置", key=f"rst_ok_{u}"):
                        if rp:
                            auth_reset_pw(st.session_state.token, u, rp)
                            st.session_state[f"rst_open_{u}"] = False; st.success(f"{u} 密码已重置！"); st.rerun()
            st.divider()
            st.caption(f"👑 **{ADMIN_USER}** — 管理员（不可删除/不可降级）")

    # ── 数据备份 ──
    with tab2:
        c_dl, c_up = st.columns(2)
        with c_dl:
            export_data = auth_export_users(st.session_state.token)
            st.download_button("📥 导出用户数据",
                json.dumps(export_data, indent=2, ensure_ascii=False),
                "users_backup.json", "application/json", use_container_width=True)
        with c_up:
            _render_import_users()

    # ── 导入布局 ──
    with tab3:
        _render_import_layout()


def _render_import_users():
    """导入用户数据（三态）"""
    if "import_usr_state" not in st.session_state:
        st.session_state.import_usr_state = "idle"; st.session_state.import_usr_data = None
        st.session_state.import_usr_result = None

    state = st.session_state.import_usr_state
    if state == "idle":
        uploaded = st.file_uploader("📤 导入用户数据", type=["json"], key="restore_users",
                                     label_visibility="collapsed")
        if uploaded is not None:
            try:
                raw = json.loads(uploaded.read().decode("utf-8"))
                if isinstance(raw, dict):
                    normalized = []
                    for uname, info in raw.items():
                        normalized.append({
                            "username": uname,
                            "password_hash": info.get("password_hash", info.get("password", "")),
                            "role": info.get("role", "viewer")
                        })
                elif isinstance(raw, list):
                    normalized = raw
                else:
                    st.error("不支持的数据格式"); st.stop()
                if not normalized: st.error("无用户数据"); st.stop()
                st.session_state.import_usr_data = normalized
                st.session_state.import_usr_state = "preview"
                st.rerun()
            except json.JSONDecodeError: st.error("不是有效的 JSON 文件")
            except Exception as e: st.error(f"解析失败: {e}")

    elif state == "preview":
        data = st.session_state.import_usr_data
        st.info(f"📋 检测到 **{len(data)}** 个用户")
        df_preview = pd.DataFrame(data)
        show_cols = [c for c in ["username", "role"] if c in df_preview.columns]
        st.dataframe(df_preview[show_cols], use_container_width=True, hide_index=True)
        c1, c2 = st.columns(2)
        if c1.button("✅ 确认导入", use_container_width=True, type="primary"):
            res = auth_import_users(st.session_state.token, data)
            st.session_state.import_usr_result = res
            st.session_state.import_usr_state = "done"
            st.rerun()
        if c2.button("❌ 取消", use_container_width=True):
            st.session_state.import_usr_state = "idle"; st.rerun()

    elif state == "done":
        res = st.session_state.import_usr_result
        if res and res.get("success"):
            st.success(f"✅ 成功导入 {res.get('count', 0)} 个用户")
        else:
            st.error(f"导入失败: {res.get('error', '未知错误') if res else '无响应'}")
        if st.button("完成", use_container_width=True):
            st.session_state.import_usr_state = "idle"; st.rerun()


def _load_layout_doc() -> str:
    """读取布局导入格式说明文档内容（网页内嵌展示，避免相对链接打不开）"""
    doc_path = Path(__file__).parent / "docs" / "布局导入格式说明.md"
    try:
        return doc_path.read_text(encoding="utf-8")
    except Exception:
        return "说明文档加载失败，请查看 `docs/布局导入格式说明.md`"


def _render_import_layout():
    """导入自定义停车场布局"""
    if "custom_layouts" not in st.session_state:
        st.session_state.custom_layouts = {}

    with st.expander("📖 布局导入格式说明", expanded=False):
        st.markdown(_load_layout_doc())
        st.download_button("📥 下载示例布局 JSON",
                           json.dumps(EXAMPLE_LAYOUT, indent=2, ensure_ascii=False),
                           "example_layout.json", "application/json")

    uploaded = st.file_uploader("📤 上传布局 JSON", type=["json"], key="import_layout")
    if uploaded is not None:
        try:
            data = json.loads(uploaded.read().decode("utf-8"))
            if "name" not in data or "nodes" not in data or "edges" not in data:
                st.error("JSON 格式不正确，需包含 name/nodes/edges 字段")
                st.stop()
            # 校验
            node_ids = {nd["id"] for nd in data["nodes"]}
            if "ENTRY" not in node_ids:
                st.error("节点中必须包含 id='ENTRY' 的入口节点")
                st.stop()
            for ed in data["edges"]:
                if ed["from"] not in node_ids or ed["to"] not in node_ids:
                    st.error(f"边 {ed['from']}→{ed['to']} 引用了不存在的节点")
                    st.stop()
            # 测试构建
            net, spots = build_layout_from_json(data)
            name = data["name"]
            layout_id = name.lower().replace(" ", "_")

            st.success(f"✅ 布局 `{name}` 校验通过！")
            st.caption(f"节点: {len(data['nodes'])} | 边: {len(data['edges'])} | 车位: {len(spots)}")

            # 预览图
            fig = draw_parking_layout(net, spots, height=280)
            st.plotly_chart(fig, use_container_width=True)

            if st.button("✅ 添加到布局列表", type="primary"):
                st.session_state.custom_layouts[layout_id] = {
                    "name": name, "data": data,
                    "net": net, "spots": spots
                }
                LAYOUT_BUILDERS[layout_id] = lambda ns=len(spots), tr=0.0, d=data: _build_custom(d)
                LAYOUTS[layout_id] = name
                st.success(f"✅ `{name}` 已添加！在仿真设置中可选")
                # 清除 uploader
                st.rerun()
        except json.JSONDecodeError:
            st.error("不是有效的 JSON 文件")
        except Exception as e:
            st.error(f"校验失败: {e}")

    # 已导入的布局列表
    if st.session_state.custom_layouts:
        st.divider()
        st.caption("**已导入的布局：**")
        for lid, linfo in st.session_state.custom_layouts.items():
            c1, c2 = st.columns([4, 1])
            c1.write(f"📐 **{linfo['name']}** ({len(linfo['spots'])}车位)")
            if c2.button("删除", key=f"del_layout_{lid}"):
                del st.session_state.custom_layouts[lid]
                LAYOUT_BUILDERS.pop(lid, None)
                LAYOUTS.pop(lid, None)
                st.rerun()


def _build_custom(data):
    """lambda 包装：从预存 data 构建自定义布局"""
    net, spots = build_layout_from_json(data)
    return net, spots


def render_layout_page():
    """页面3: 停车场布局图（静态）"""
    st.subheader("🅿️ 停车场布局图")
    if not st.session_state.get("sim_has_run"):
        st.info("👈 请先在 **仿真设置** 中运行仿真")
        return

    net = st.session_state.sim_net
    spots = st.session_state.sim_spots

    has_custom = bool(st.session_state.get("custom_layouts"))
    mode = st.radio("视图模式", ["仿真布局", "真实布局"],
                    horizontal=True,
                    disabled=not has_custom,
                    help="真实布局仅在有导入自定义布局后可用" if not has_custom else None)

    if mode == "真实布局" and not has_custom:
        st.info("暂无导入的自定义布局")
        return

    if mode == "仿真布局":
        sa = sum(1 for s in spots if s.spot_type == SpotType.STANDALONE)
        ta = sum(1 for s in spots if s.spot_type == SpotType.TANDEM)
        st.caption(f"{len(spots)} 车位 — {sa} 独立 + {ta} 纵深")

    if "layout_zoom" not in st.session_state: st.session_state.layout_zoom = 1.0
    c_zoom, _ = st.columns([1, 5])
    with c_zoom:
        zoom = st.slider("🔍 缩放", 0.5, 3.0, st.session_state.layout_zoom, 0.1, key="layout_zoom_slider")
    st.session_state.layout_zoom = zoom
    adaptive = 520 / 400
    scale = adaptive * zoom

    fig = draw_parking_layout(net, spots, height=520, scale=scale)
    st.plotly_chart(fig, use_container_width=True, config={"scrollZoom": True})


def render_path_page():
    """页面4: 车辆动态路径 — 20帧快照回放"""
    st.subheader("🚗 车辆动态路径")
    if not st.session_state.get("sim_has_run"):
        st.info("👈 请先在 **仿真设置** 中运行仿真")
        return

    net = st.session_state.sim_net
    spots = st.session_state.sim_spots
    events = st.session_state.sim_events_raw
    max_time = max(e["time"] for e in events) if events else 30

    if "replay_time" not in st.session_state: st.session_state.replay_time = 0.0
    if "frame_index" not in st.session_state: st.session_state.frame_index = 0
    if "frame_playing" not in st.session_state: st.session_state.frame_playing = False
    if "selected_vehicle" not in st.session_state: st.session_state.selected_vehicle = None

    all_vehs = sorted(set(
        str(e.get("vehicle_id", "")) for e in events
        if str(e.get("vehicle_id", "")) and e.get("type") in ("vehicle_arrival", "parking_assigned", "spot_entry")
    ), key=lambda v: int(v.split("_")[-1]) if "_" in v else v)

    st.selectbox("选择车辆", [""] + all_vehs, key="selected_vehicle",
                 format_func=lambda v: f"🚙 {v}" if v else "— 选择车辆 —")

    hl_veh = st.session_state.selected_vehicle
    if not hl_veh:
        st.info("请选择一辆车")
        return

    veh_ev = sorted([e for e in events if str(e.get("vehicle_id","")) == hl_veh], key=lambda e: e["time"])
    t_start, t_end, spot_id = None, None, None
    for e in veh_ev:
        if e["type"] == "parking_assigned" and t_start is None:
            t_start = e["time"]; spot_id = e.get("spot_id","")
        elif e["type"] == "spot_entry" and t_start is not None and t_end is None:
            t_end = e["time"]

    if t_start is None:
        # 该车辆未分配到车位：展示拒绝理由
        rej = [e for e in veh_ev if e.get("type") == "rejected"]
        if rej:
            reason = (rej[0].get("metadata", {}) or {}).get("reason", "停车场无空闲车位")
            st.error(f"🚫 该车辆被拒绝：{reason}")
        else:
            st.warning("该车辆尚未被分配车位")
        return

    if t_end is None or t_end <= t_start:
        path = None
        if "sim_pe" in st.session_state and spot_id:
            try: path = st.session_state.sim_pe.shortest_path(st.session_state.sim_pe.entry_id, spot_id)
            except: pass
        if path:
            total = 0.0
            for i in range(len(path)-1):
                fn = net.nodes.get(path[i]); tn = net.nodes.get(path[i+1])
                if fn and tn: total += math.hypot(tn.x-fn.x, tn.y-fn.y)
            t_end = t_start + max(total * 0.5, 3.0)
        else:
            t_end = t_start + 3.0

    N = 20
    frames = [t_start + (t_end - t_start) * i / (N - 1) for i in range(N)]

    st.caption(f"🅿️ 车位: **{spot_id}** | 行驶: {t_start:.1f}s → {t_end:.1f}s ({(t_end-t_start):.1f}s)")

    # 展示该车辆的拒绝/调整理由（因客观原因无法停最优车位、或需移位/离场）
    notes = []
    for e in veh_ev:
        et = e.get("type", "")
        meta = e.get("metadata", {}) or {}
        reason = meta.get("reason", "")
        if et == "rejected":
            notes.append(f"🚫 **拒绝**：{reason or '停车场无空闲车位'}")
        elif et == "departure" and meta.get("had_blocking"):
            notes.append(f"🔄 **离场需移位**：{reason or '被外侧车辆阻挡'}")
        elif et == "shift_start":
            notes.append(f"🔄 **被临时移位**：{reason or '为让行内层车辆离场'}")
    for n in notes:
        st.warning(n)

    c0, c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1, 1, 3])
    with c0:
        if st.button("⏮", help="第1帧(起点)", use_container_width=True):
            st.session_state.frame_index = 0; st.session_state.replay_time = frames[0]
            st.session_state.frame_playing = False; st.rerun()
    with c1:
        if st.button("◀", help="上一帧", use_container_width=True):
            st.session_state.frame_index = max(0, st.session_state.frame_index - 1)
            st.session_state.replay_time = frames[st.session_state.frame_index]
            st.session_state.frame_playing = False; st.rerun()
    with c2:
        ply = "⏸" if st.session_state.frame_playing else "▶"
        if st.button(ply, help="自动播放/暂停", use_container_width=True,
                     type="primary" if st.session_state.frame_playing else "secondary"):
            st.session_state.frame_playing = not st.session_state.frame_playing
            if st.session_state.frame_playing and st.session_state.frame_index >= N - 1:
                st.session_state.frame_index = 0
            st.session_state.replay_time = frames[st.session_state.frame_index]
            st.rerun()
    with c3:
        if st.button("▶▶", help="下一帧", use_container_width=True):
            st.session_state.frame_index = min(N - 1, st.session_state.frame_index + 1)
            st.session_state.replay_time = frames[st.session_state.frame_index]
            st.session_state.frame_playing = False; st.rerun()
    with c4:
        if st.button("⏭", help="第20帧(终点)", use_container_width=True):
            st.session_state.frame_index = N - 1; st.session_state.replay_time = frames[-1]
            st.session_state.frame_playing = False; st.rerun()
    with c5:
        st.progress((st.session_state.frame_index + 1) / N,
                     f"帧 {st.session_state.frame_index+1}/{N} | t={frames[st.session_state.frame_index]:.1f}s")

    # 时间轴拖拽（拖动后跳帧并暂停播放）
    # 在渲染滑杆之前同步到当前帧；不能在 widget 实例化后再修改其 key，否则会抛 StreamlitAPIException
    st.session_state.replay_timeline = float(frames[st.session_state.frame_index])
    step = max((t_end - t_start) / 200.0, 0.001)
    t_val = st.slider(
        "拖拽时间轴",
        min_value=float(t_start),
        max_value=float(t_end),
        value=float(frames[st.session_state.frame_index]),
        step=step,
        key="replay_timeline",
        format="%.1f s",
    )
    new_idx = min(range(N), key=lambda i: abs(frames[i] - t_val))
    if new_idx != st.session_state.frame_index:
        st.session_state.frame_index = new_idx
        st.session_state.replay_time = frames[new_idx]
        st.session_state.frame_playing = False

    if st.session_state.frame_index < len(frames):
        st.session_state.replay_time = frames[st.session_state.frame_index]

    _draw_charts(net, spots, events, max_time)

    # 自动轮播（放在图表之后，确保先渲染再切帧）
    if st.session_state.frame_playing:
        if st.session_state.frame_index < N - 1:
            time.sleep(0.4)
            st.session_state.frame_index += 1
            st.rerun()
        else:
            st.session_state.frame_playing = False
            st.rerun()


def _draw_charts(net, spots, events, max_time):
    """绘制停车场图表（被静态和播放模式共用）"""
    state = replay_state(events, st.session_state.replay_time, spots, net)
    hl_path, hl_center, hl_veh = None, None, st.session_state.selected_vehicle

    if hl_veh:
        veh_ev = sorted([e for e in events if str(e.get("vehicle_id","")) == hl_veh], key=lambda e: e["time"])
        pn = []
        for e in veh_ev:
            if e["type"] == "parking_assigned":
                sid = e.get("spot_id","")
                try: pn = st.session_state.sim_pe.shortest_path(st.session_state.sim_pe.entry_id, sid)
                except: pn = [st.session_state.sim_pe.entry_id, sid]
                break
        if pn: hl_path = pn

        ipos = interp_vehicle_pos(net, events, hl_veh, st.session_state.replay_time)
        hl_center = ipos
        found = False
        for dv in state["dv"]:
            if str(dv.get("vid","")) == hl_veh: dv["x"],dv["y"]=ipos[0],ipos[1]; found=True; break
        if not found:
            state["dv"].append({"vid":hl_veh,"x":ipos[0],"y":ipos[1],"st":"行驶中","target":hl_path[-1] if hl_path else "?"})

    for dv in state["dv"]:
        vid = str(dv.get("vid",""))
        if vid and vid != hl_veh:
            ipos = interp_vehicle_pos(net, events, vid, st.session_state.replay_time)
            dv["x"],dv["y"] = ipos[0],ipos[1]

    if "path_zoom" not in st.session_state: st.session_state.path_zoom = 1.0
    zoom = st.slider("🔍 图缩放", 0.5, 3.0, st.session_state.path_zoom, 0.1, key="path_zoom_slider",
                     label_visibility="collapsed")
    st.session_state.path_zoom = zoom

    if hl_veh:
        sc = (480/400)*zoom
        c1,c2 = st.columns(2)
        with c1:
            st.caption("🌍 全局视图")
            fig = draw_parking_layout(net, spots, state, highlight_vehicle=hl_veh,
                                       highlight_path=hl_path, height=480, scale=sc)
            st.plotly_chart(fig, use_container_width=True, config={"scrollZoom": True})
        with c2:
            st.caption(f"🔍 {hl_veh} 周边")
            if hl_center:
                fig = draw_parking_layout(net, spots, state, highlight_vehicle=hl_veh,
                                           highlight_path=hl_path,
                                           view_center=hl_center, view_radius=18, height=480, scale=sc)
                st.plotly_chart(fig, use_container_width=True, config={"scrollZoom": True})
            else:
                st.info("车辆尚未出现在画面中")
    else:
        sc = (520/400)*zoom
        st.caption("🌍 全局视图 — 选择一辆车查看双窗口回放")
        fig = draw_parking_layout(net, spots, state, height=520, scale=sc)
        st.plotly_chart(fig, use_container_width=True, config={"scrollZoom": True})


def render_metrics_page():
    """页面5: 指标分析"""
    st.subheader("📊 指标分析")
    if not st.session_state.get("sim_has_run"):
        st.info("👈 请先在 **仿真设置** 中运行仿真")
        return

    # 算法筛选优先级说明（动态，跟随用户在仿真设置页的调整）
    st.markdown("### 🎯 算法筛选优先级")
    st.caption("当前排序规则（字典序：先比第一项，相同再比下一项）")
    priority_order = st.session_state.get("priority_order", DEFAULT_PRIORITY)
    prio = pd.DataFrame([
        [i + 1, name,
         "越高越好" if PRIORITY_METRICS[name][1] == "max" else "越低越好",
         PRIORITY_METRICS[name][2]]
        for i, name in enumerate(priority_order)
    ], columns=["优先级", "评估指标", "方向", "说明"])
    st.dataframe(prio, use_container_width=True, hide_index=True)
    st.markdown("---")

    # 多策略对比
    if st.session_state.get("sim_all_metrics"):
        st.markdown("### 🏆 多策略对比")
        n_runs = st.session_state.get("sim_n_runs", 1)
        st.caption(f"基于 {n_runs} 次不同随机种子的平均值（降低随机波动）")
        all_m = st.session_state.sim_all_metrics
        # 按用户定义的优先级做字典序排序
        priority_order = st.session_state.get("priority_order", DEFAULT_PRIORITY)
        def sort_key(m):
            key = []
            for name in priority_order:
                if name not in PRIORITY_METRICS:
                    continue
                field, direction, _ = PRIORITY_METRICS[name]
                val = m.get(field, 0)
                key.append(-val if direction == "max" else val)
            return tuple(key)
        sorted_m = sorted(all_m, key=sort_key)
        best = sorted_m[0]
        df = pd.DataFrame(sorted_m)[["strategy","satisfaction_rate","spatial_utilization","avg_wait_time_s",
                                     "shift_count","shift_distance_m","total_drive_distance_m",
                                     "rejected_count","runtime_s"]]
        df.columns = ["策略","满足率","利用率","平均等待(s)","移位次数","移位距离(m)","行驶距离(m)","拒绝数","耗时(s)"]
        st.markdown(f'> 🏆 推荐: **{STRATEGY_LABELS.get(best["strategy"],best["strategy"])}** 满足率 {best["satisfaction_rate"]:.1%}')
        cpsat_rate = st.session_state.get("sim_cpsat_rate")
        if cpsat_rate is not None:
            gap = best["satisfaction_rate"] - cpsat_rate
            st.markdown(f'> 🎯 理论最优（CP-SAT 离线全信息）满足率 **{cpsat_rate:.1%}**，最佳策略距最优 {gap:.1%}')

        def _highlight_best(row):
            # 第一行（按优先级排序后的最优策略）标绿
            return ['background-color: #d4edda' if row.name == 0 else '' for _ in row]

        styled = (df.style
                  .format({"满足率":"{:.1%}","利用率":"{:.1%}","平均等待(s)":"{:.1f}",
                           "移位距离(m)":"{:.1f}","行驶距离(m)":"{:.1f}","耗时(s)":"{:.3f}"})
                  .apply(_highlight_best, axis=1))
        st.dataframe(styled, use_container_width=True, hide_index=True)
        c1, c2 = st.columns(2)
        with c1: st.bar_chart(df.set_index("策略")["满足率"], height=200)
        with c2: st.bar_chart(df.set_index("策略")["移位次数"], height=200)
        st.markdown("#### 📡 多维指标雷达图（外圈=更好）")
        st.plotly_chart(_plot_radar(all_m), use_container_width=True)
        st.download_button("📥 下载 CSV", df.to_csv(index=False).encode('utf-8'),
                           "parking_comparison.csv", "text/csv")
    else:
        # 单策略详情
        m = st.session_state.get("sim_metrics")
        if m:
            st.markdown(f"### 📈 策略: {STRATEGY_LABELS.get(m['strategy'], m['strategy'])}")
            c1, c2, c3, c4 = st.columns(4)
            with c1: _metric("满足率", f"{m['satisfaction_rate']:.1%}", "good" if m['satisfaction_rate']>0.5 else "bad")
            with c2: _metric("空间利用率", f"{m['spatial_utilization']:.1%}")
            with c3: _metric("移位次数", str(m['shift_count']), "warn" if m['shift_count']>0 else "")
            with c4: _metric("拒绝数", str(m['rejected_count']), "bad" if m['rejected_count']>0 else "")
            c5, c6, c7, c8 = st.columns(4)
            with c5: _metric("行驶距离", f"{m['total_drive_distance_m']:.0f}m")
            with c6: _metric("移位距离", f"{m['shift_distance_m']:.0f}m")
            with c7: _metric("平均等待", f"{m['avg_wait_time_s']:.1f}s")
            with c8: _metric("运行耗时", f"{m['runtime_s']:.3f}s")
            cpsat_rate = st.session_state.get("sim_cpsat_rate")
            if cpsat_rate is not None:
                gap = m["satisfaction_rate"] - cpsat_rate
                st.markdown(f'> 🎯 理论最优（CP-SAT）满足率 **{cpsat_rate:.1%}**，当前策略距最优 {gap:.1%}')
            buffers = m.get('buffer_failed_count', 0)
            rejs = m.get('rejected_count', 0)
            if buffers or rejs:
                st.warning(f"⚠️ 降级: {buffers} 缓冲失败, {rejs} 拒绝")
            st.download_button("📥 下载指标", pd.DataFrame([m]).to_csv(index=False).encode('utf-8'),
                               f"parking_{m.get('strategy','result')}.csv", "text/csv")

    # ── 参数调优历史（每策略最近 5 次）──
    history = st.session_state.get("run_history", {})
    if history:
        st.markdown("---")
        st.markdown("### 🧪 参数调优历史（每策略最近5次）")
        strat_names = list(history.keys())
        sel = st.selectbox("选择策略查看调参历史", strat_names,
                           format_func=lambda n: STRATEGY_LABELS.get(n, n))
        records = history.get(sel, [])
        if records:
            rows = []
            for i, rec in enumerate(records):
                m = rec.get("metrics", {})
                params_str = ", ".join(f"{k}={v}" for k, v in rec.get("params", {}).items()) or "默认"
                rows.append({
                    "序号": f"#{i + 1}",
                    "时间": rec.get("time", ""),
                    "参数": params_str,
                    "满足率": m.get("satisfaction_rate"),
                    "利用率": m.get("spatial_utilization"),
                    "移位次数": m.get("shift_count"),
                    "移位距离(m)": m.get("shift_distance_m"),
                    "平均等待(s)": m.get("avg_wait_time_s"),
                    "拒绝数": m.get("rejected_count"),
                })
            hdf = pd.DataFrame(rows)
            st.dataframe(hdf.style.format({
                "满足率": "{:.1%}", "利用率": "{:.1%}",
                "移位距离(m)": "{:.1f}", "平均等待(s)": "{:.1f}",
            }), use_container_width=True, hide_index=True)
            if len(records) > 1:
                st.bar_chart(hdf.set_index("序号")["满足率"], height=200)
        else:
            st.info("该策略暂无运行历史")
        if st.button("🗑 清空全部历史", key="clear_history"):
            st.session_state.run_history = {}
            st.rerun()


def _metric(label, value, variant=""):
    cls = f"metric-card {variant}" if variant else "metric-card"
    st.markdown(f'<div class="{cls}"><div class="val">{value}</div><div class="lbl">{label}</div></div>',
                unsafe_allow_html=True)


def render_status_page():
    """页面: 系统状态与预警 —— 主动探测 Supabase 后端可用性"""
    st.subheader("🚨 系统状态与预警")
    st.caption("主动探测 Supabase 后端是否在线、API key 是否有效")

    if "health_check" not in st.session_state:
        st.session_state.health_check = None

    if st.button("🔄 立即重新探测"):
        st.session_state.health_check = None
        st.rerun()

    if st.session_state.health_check is None:
        with st.spinner("探测中..."):
            st.session_state.health_check = check_supabase_health()

    h = st.session_state.health_check
    status = h.get("status", "error")
    if status == "ok":
        st.success(f"✅ {h.get('message')}")
    elif status == "warn":
        st.warning(f"⚠️ {h.get('message')}")
    else:
        st.error(f"🚫 {h.get('message')}")

    c1, c2, c3 = st.columns(3)
    with c1:
        _metric("后端在线", "✅ 是" if h.get("online") else "❌ 否",
                "good" if h.get("online") else "bad")
    with c2:
        _metric("API key 有效", "✅ 是" if h.get("api_key_valid") else "❌ 否",
                "good" if h.get("api_key_valid") else "bad")
    with c3:
        lat = h.get("latency_ms")
        _metric("响应耗时", f"{lat}ms" if lat is not None else "—")

    st.caption(f"探测时间：{h.get('checked_at')}")

    st.markdown("""
**说明**
- 本页主动探测 `auth.py` 中配置的 Supabase 后端（URL 与 anon key）是否可用。
- 后端在线但 API key 失效 → key 已过期或权限变更，需到 Supabase 控制台检查。
- 无法连接 → 项目可能已暂停（免费项目 7 天无活动会自动暂停）或已过期。
""")


def render_algo_import_page():
    """页面: 新算法接入 —— 上传算法描述文件，供 AI 后台接入"""
    st.subheader("🧩 新算法接入")
    st.markdown("""
上传你的算法描述文件（**文字说明 / 代码示例 / 伪代码**，支持 `.md` / `.txt` / `.py` / `.json`），
文件会保存到仓库 `pending_algorithms/` 目录。

> 上传后，请回到 **Deep Code 对话** 中说一句「接入算法」，AI 会读取文件、编写代码、复检并接入，
> 最后跑仿真比较，选出最优算法。
""")

    pending_dir = Path(__file__).parent / "pending_algorithms"
    pending_dir.mkdir(parents=True, exist_ok=True)

    uploaded = st.file_uploader("📤 上传算法文件", type=["md", "txt", "py", "json"],
                                key="algo_upload")
    if uploaded is not None:
        try:
            content = uploaded.read().decode("utf-8", errors="replace")
            target = pending_dir / uploaded.name
            target.write_text(content, encoding="utf-8")
            st.success(f"✅ 已保存 `{uploaded.name}` 到 pending_algorithms/")
            st.info("请回到 Deep Code 对话，说「接入算法」，AI 会读取并接入。")
        except Exception as e:
            st.error(f"保存失败: {e}")

    files = sorted(p for p in pending_dir.glob("*") if p.is_file()) if pending_dir.exists() else []
    if files:
        st.divider()
        st.caption("**已上传的算法文件：**")
        for f in files:
            st.write(f"📄 `{f.name}`（{f.stat().st_size} 字节）")
    else:
        st.caption("暂无已上传的算法文件")


# ═══════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════
st.set_page_config(page_title="智能停车场优化", page_icon="🚗", layout="wide")
st.markdown(GLOBAL_CSS, unsafe_allow_html=True)
check_login()
role = ROLES[st.session_state.role]

# ── Sidebar ──
with st.sidebar:
    st.markdown(f'<div style="display:flex;align-items:center;gap:8px;padding:0.3rem 0 0.8rem 0;">'
        f'<div style="width:32px;height:32px;border-radius:50%;background:rgba(255,255,255,0.2);'
        f'display:flex;align-items:center;justify-content:center;font-size:1rem">🚗</div>'
        f'<div><div style="font-weight:700;font-size:0.9rem;color:white;">{st.session_state.username}</div>'
        f'<div style="font-size:0.7rem;color:rgba(255,255,255,0.7);">{role["label"]}</div></div></div>',
        unsafe_allow_html=True)

    if st.button("🚪 退出", use_container_width=True):
        auth_logout(st.session_state.token)
        clear_session_token()
        st.session_state.logged_in = False; st.session_state.token = None
        st.rerun()

    with st.expander("🔑 修改密码"):
        old_pw = st.text_input("当前密码", type="password", key="chg_old")
        new_pw = st.text_input("新密码", type="password", key="chg_new")
        new_pw2 = st.text_input("确认新密码", type="password", key="chg_new2")
        if st.button("确认修改", use_container_width=True, key="do_chg_pw"):
            if not old_pw or not new_pw: st.error("请填写完整")
            elif new_pw != new_pw2: st.error("两次密码不一致")
            else:
                res = auth_change_pw(st.session_state.token, old_pw, new_pw)
                if res.get("success"): st.success("密码已修改！")
                else: st.error(res.get("error", "修改失败"))

    st.divider()
    # ── 页面导航 ──
    pages = [
        "⚙️ 仿真设置",
        "🔧 系统设置",
        "🅿️ 停车场布局图",
        "🚗 动态路径",
        "📊 指标分析",
        "🧩 新算法接入",
        "🚨 系统状态",
    ]
    if "page" not in st.session_state:
        st.session_state.page = pages[0]

    selected = st.radio("导航", pages, index=pages.index(st.session_state.page) if st.session_state.page in pages else 0,
                        label_visibility="collapsed")
    if selected != st.session_state.page:
        st.session_state.page = selected
        st.rerun()

# ── 主区域 ──
page = st.session_state.page
if page == pages[0]:
    render_settings(role)
elif page == pages[1]:
    render_system(role)
elif page == pages[2]:
    render_layout_page()
elif page == pages[3]:
    render_path_page()
elif page == pages[4]:
    render_metrics_page()
elif page == pages[5]:
    render_algo_import_page()
elif page == pages[6]:
    render_status_page()
