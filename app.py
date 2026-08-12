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

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from parking_opt.domain.spot import RoadNetwork, RoadNode, NodeType, Spot, SpotType
from parking_opt.routing.path_engine import PathEngine
from parking_opt.simulation.parking_lot import ParkingLot
from parking_opt.simulation.engine import SimulationEngine
from parking_opt.simulation.arrival import generate_demand
from parking_opt.strategies.baselines import FCFS, NearestPath, RandomAssign
from parking_opt.strategies.greedy import GreedyStrategy, DepartureOrderGreedy
from parking_opt.evaluation.metrics import compute_metrics
from viz import draw_parking_layout, draw_dual_view

# ═══════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════
STRATEGY_LABELS = {
    "greedy": "贪心（主方法）", "fcfs": "先到先服务",
    "nearest": "最近路径", "random": "随机分配",
    "departure_greedy": "离场贪心", "compare_all": "全部对比",
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
section[data-testid="stSidebar"] { background: linear-gradient(180deg, #1a2332, #1e3a5f); }
section[data-testid="stSidebar"] h1, section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] .stCaption { color: rgba(255,255,255,.9)!important; }
section[data-testid="stSidebar"] .stRadio label { color: rgba(255,255,255,.85)!important; }
section[data-testid="stSidebar"] .stButton>button { background: rgba(255,255,255,.12)!important;
    color: white!important; border: 1px solid rgba(255,255,255,.2)!important; border-radius: 8px!important; }
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
def run_single(net, spots, vehicles, strategy, seed):
    pe = PathEngine(net); lot = ParkingLot(spots)
    engine = SimulationEngine(lot, pe, vehicles, strategy, seed=seed)
    t0 = time.time(); events = engine.run()
    m = compute_metrics(events, len(spots)); m["runtime_s"] = round(time.time()-t0, 3)
    m["strategy"] = strategy.name; return m, events, lot

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
        strategy_name = st.selectbox("策略", list(STRATEGY_LABELS.keys()),
                                     format_func=lambda x: STRATEGY_LABELS[x])

    if st.button("▶️ 运行仿真", type="primary", use_container_width=True,
                 disabled=not role["can_run_simulation"]):
        with st.spinner("仿真运行中..."):
            net, spots = LAYOUT_BUILDERS[layout](n_spots, tandem_ratio)
            pe = PathEngine(net)

            if strategy_name == "compare_all":
                strats = {"greedy": GreedyStrategy(), "fcfs": FCFS(), "nearest": NearestPath(),
                          "random": RandomAssign(), "departure_greedy": DepartureOrderGreedy()}
                all_m = []
                for nm, stg in strats.items():
                    vehs = generate_demand(total_vehicles=n_vehicles, seed=seed)
                    m, _, _ = run_single(net, spots, vehs, stg, seed); all_m.append(m)
                st.session_state.sim_all_metrics = all_m
            else:
                smap = {"greedy": GreedyStrategy(), "fcfs": FCFS(), "nearest": NearestPath(),
                        "random": RandomAssign(), "departure_greedy": DepartureOrderGreedy()}
                vehs = generate_demand(total_vehicles=n_vehicles, seed=seed)
                metrics, events, lot = run_single(net, spots, vehs, smap[strategy_name], seed)
                events_raw = [{"time": e.time, "type": e.event_type.value,
                               "vehicle_id": e.vehicle_id or "", "spot_id": e.spot_id or "",
                               "metadata": dict(e.metadata)} for e in events]
                st.session_state.sim_metrics = metrics
                st.session_state.sim_events_raw = events_raw
                st.session_state.sim_all_metrics = None

            st.session_state.sim_net = net
            st.session_state.sim_spots = spots
            st.session_state.sim_pe = pe
            st.session_state.sim_n_spots = n_spots
            st.session_state.sim_n_vehicles = n_vehicles
            st.session_state.sim_seed = seed
            st.session_state.sim_strategy_name = strategy_name
            st.session_state.sim_layout = layout
            st.session_state.sim_has_run = True
            # 重置回放状态
            st.session_state.replay_time = 0.0
            st.session_state.replay_playing = False
            st.session_state.selected_vehicle = None
            # 跳到布局图页面
            st.session_state.page = "🅿️ 停车场布局图"
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


def _render_import_layout():
    """导入自定义停车场布局"""
    if "custom_layouts" not in st.session_state:
        st.session_state.custom_layouts = {}

    st.caption("上传 JSON 文件定义停车场布局，格式参见 [布局导入说明](docs/布局导入格式说明.md)")

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

    fig = draw_parking_layout(net, spots, height=480)
    st.plotly_chart(fig, use_container_width=True)


def render_path_page():
    """页面4: 动态路径回放"""
    st.subheader("🚗 车辆动态路径")
    if not st.session_state.get("sim_has_run"):
        st.info("👈 请先在 **仿真设置** 中运行仿真")
        return

    net = st.session_state.sim_net
    spots = st.session_state.sim_spots
    events = st.session_state.sim_events_raw
    max_time = max(e["time"] for e in events) if events else 30

    # 初始化回放状态
    if "replay_time" not in st.session_state: st.session_state.replay_time = 0.0
    if "replay_playing" not in st.session_state: st.session_state.replay_playing = False
    if "replay_speed" not in st.session_state: st.session_state.replay_speed = 1.0
    if "selected_vehicle" not in st.session_state: st.session_state.selected_vehicle = None

    # 获取所有车辆 ID
    all_vehs = sorted(set(
        str(e.get("vehicle_id", "")) for e in events
        if str(e.get("vehicle_id", "")) and e.get("type") in ("vehicle_arrival", "parking_assigned", "spot_entry")
    ), key=lambda v: int(v.split("_")[-1]) if "_" in v else v)

    # ── 控制栏 ──
    ctl = st.container()
    with ctl:
        c0, c1, c2, c3, c4, c5, c6 = st.columns([2, 0.7, 0.7, 3, 0.7, 1, 1.5])
        with c0:
            st.selectbox("选择车辆", [""] + all_vehs, key="selected_vehicle",
                         format_func=lambda v: f"🚙 {v}" if v else "— 选择车辆 —",
                         label_visibility="collapsed")
        with c1:
            if st.button("⏮", help="起点", use_container_width=True):
                st.session_state.replay_time = 0.0; st.session_state.replay_playing = False
        with c2:
            if st.button("◀", help="后退 1s", use_container_width=True):
                st.session_state.replay_time = max(0, st.session_state.replay_time - 1)
                st.session_state.replay_playing = False
        with c3:
            rt = st.slider("时间轴", 0.0, max_time, st.session_state.replay_time, 0.5,
                           key="time_slider", label_visibility="collapsed")
            if abs(rt - st.session_state.replay_time) > 0.01:
                st.session_state.replay_time = rt
                st.session_state.replay_playing = False
        with c4:
            if st.button("▶", help="前进 1s", use_container_width=True):
                st.session_state.replay_time = min(max_time, st.session_state.replay_time + 1)
                st.session_state.replay_playing = False
        with c5:
            if st.button("⏭", help="终点", use_container_width=True):
                st.session_state.replay_time = max_time; st.session_state.replay_playing = False
        with c6:
            ply_lbl = "⏸ 暂停" if st.session_state.replay_playing else "▶ 播放"
            if st.button(ply_lbl, use_container_width=True, type="primary" if st.session_state.replay_playing else "secondary"):
                st.session_state.replay_playing = not st.session_state.replay_playing

        c_speed = st.columns([1, 8])
        with c_speed[0]:
            speed = st.selectbox("速度", [0.5, 1.0, 2.0, 4.0], index=1, key="replay_speed",
                                 label_visibility="collapsed",
                                 format_func=lambda s: f"{s}x")
        with c_speed[1]:
            st.caption(f"⏰ {st.session_state.replay_time:.1f}s / {max_time:.0f}s")

    # 自动播放
    if st.session_state.replay_playing:
        st.session_state.replay_time += st.session_state.replay_speed * 0.3
        if st.session_state.replay_time >= max_time:
            st.session_state.replay_time = max_time
            st.session_state.replay_playing = False
        time.sleep(0.08)
        st.rerun()

    # ── 当前时刻状态 ──
    state = replay_state(events, st.session_state.replay_time, spots, net)

    # ── 选中车辆的路径信息 ──
    highlight_path = None
    local_center = None
    highlight_vehicle = st.session_state.selected_vehicle

    if highlight_vehicle:
        # 获取该车辆的事件
        veh_events = [e for e in events if str(e.get("vehicle_id", "")) == highlight_vehicle]
        veh_events.sort(key=lambda e: e["time"])
        # 查找 assigned 事件获取路径
        path_nodes = []
        for e in veh_events:
            if e["type"] == "parking_assigned":
                sid = e.get("spot_id", "")
                try:
                    path_nodes = st.session_state.sim_pe.shortest_path(
                        st.session_state.sim_pe.entry_id, sid)
                except:
                    path_nodes = [st.session_state.sim_pe.entry_id, sid]
                break
        if path_nodes:
            highlight_path = path_nodes

    # 计算局部视图中心（选中车辆当前位置）
    if highlight_vehicle:
        for dv in state["dv"]:
            if str(dv.get("vid", "")) == highlight_vehicle:
                local_center = (dv["x"], dv["y"])
                break
        if local_center is None and highlight_path and highlight_path[-1] in net.nodes:
            nd = net.nodes[highlight_path[-1]]
            local_center = (nd.x, nd.y)

    # ── 双窗口 ──
    if highlight_vehicle:
        col_left, col_right = st.columns(2)
        with col_left:
            st.caption("🌍 全局视图")
            fig_gl = draw_parking_layout(net, spots, state, highlight_vehicle=highlight_vehicle,
                                          highlight_path=highlight_path, height=380)
            st.plotly_chart(fig_gl, use_container_width=True)
        with col_right:
            st.caption(f"🔍 {highlight_vehicle} 周边")
            if local_center:
                fig_lc = draw_parking_layout(net, spots, state, highlight_vehicle=highlight_vehicle,
                                              highlight_path=highlight_path,
                                              view_center=local_center, view_radius=18, height=380)
                st.plotly_chart(fig_lc, use_container_width=True)
            else:
                st.info("车辆尚未出现在画面中")
    else:
        st.caption("🌍 全局视图 — 选择一辆车查看双窗口回放")
        fig = draw_parking_layout(net, spots, state, height=450)
        st.plotly_chart(fig, use_container_width=True)


def render_metrics_page():
    """页面5: 指标分析"""
    st.subheader("📊 指标分析")
    if not st.session_state.get("sim_has_run"):
        st.info("👈 请先在 **仿真设置** 中运行仿真")
        return

    # 多策略对比
    if st.session_state.get("sim_all_metrics"):
        st.markdown("### 🏆 多策略对比")
        all_m = st.session_state.sim_all_metrics
        df = pd.DataFrame(all_m)[["strategy","satisfaction_rate","spatial_utilization","shift_count",
                                   "shift_distance_m","total_drive_distance_m","rejected_count","runtime_s"]]
        df.columns = ["策略","满足率","利用率","移位次数","移位距离(m)","行驶距离(m)","拒绝数","耗时(s)"]
        best = max(all_m, key=lambda m: m["satisfaction_rate"])
        st.markdown(f'> 🏆 推荐: **{STRATEGY_LABELS.get(best["strategy"],best["strategy"])}** 满足率 {best["satisfaction_rate"]:.1%}')

        styled = df.style.format({"满足率":"{:.1%}","利用率":"{:.1%}","移位距离(m)":"{:.1f}",
                                   "行驶距离(m)":"{:.1f}","耗时(s)":"{:.3f}"})
        st.dataframe(styled, use_container_width=True, hide_index=True)
        c1, c2 = st.columns(2)
        with c1: st.bar_chart(df.set_index("策略")["满足率"], height=200)
        with c2: st.bar_chart(df.set_index("策略")["移位次数"], height=200)
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
            buffers = m.get('buffer_failed_count', 0)
            rejs = m.get('rejected_count', 0)
            if buffers or rejs:
                st.warning(f"⚠️ 降级: {buffers} 缓冲失败, {rejs} 拒绝")
            st.download_button("📥 下载指标", pd.DataFrame([m]).to_csv(index=False).encode('utf-8'),
                               f"parking_{m.get('strategy','result')}.csv", "text/csv")


def _metric(label, value, variant=""):
    cls = f"metric-card {variant}" if variant else "metric-card"
    st.markdown(f'<div class="{cls}"><div class="val">{value}</div><div class="lbl">{label}</div></div>',
                unsafe_allow_html=True)


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
