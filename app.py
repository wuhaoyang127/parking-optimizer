"""智能停车场优化 — Dashboard (Streamlit) + 权限管理 + 时间轴回放"""

import sys, hashlib, json, base64, math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

import streamlit as st
import pandas as pd
import time
import plotly.graph_objects as go

from parking_opt.domain.spot import RoadNetwork, RoadNode, NodeType, Spot, SpotType
from parking_opt.routing.path_engine import PathEngine
from parking_opt.simulation.parking_lot import ParkingLot
from parking_opt.simulation.engine import SimulationEngine
from parking_opt.simulation.arrival import generate_demand
from parking_opt.strategies.baselines import FCFS, NearestPath, RandomAssign
from parking_opt.strategies.greedy import GreedyStrategy, DepartureOrderGreedy
from parking_opt.evaluation.metrics import compute_metrics

# ==================== 常量 ====================
STRATEGY_LABELS = {
    "greedy": "贪心（主方法）", "fcfs": "先到先服务",
    "nearest": "最近路径", "random": "随机分配",
    "departure_greedy": "离场贪心", "compare_all": "全部对比",
}

GLOBAL_CSS = """
<style>
:root { --primary: #1E3A5F; --accent: #2196F3; --bg: #F0F4F8; --card-bg: #FFFFFF;
    --text: #263238; --text-secondary: #607D8B; --border: #E0E6ED; --radius-sm: 8px; --radius-md: 12px;
    --shadow-sm: 0 1px 3px rgba(0,0,0,0.06); --shadow-md: 0 4px 12px rgba(0,0,0,0.08); }
.stApp { background: var(--bg); } .main .block-container { padding-top: 1rem; }
h1 { font-size: 1.8rem !important; font-weight: 700 !important; color: var(--primary) !important;
     padding-bottom: 0.3rem; border-bottom: 3px solid var(--accent); }
h2 { font-size: 1.2rem !important; font-weight: 600 !important; color: var(--primary) !important; }
.metric-card { background: var(--card-bg); border-radius: var(--radius-md); padding: 0.7rem 0.8rem;
    box-shadow: var(--shadow-sm); border-top: 3px solid var(--accent); text-align: center; }
.metric-card .metric-value { font-size: 1.4rem; font-weight: 700; color: var(--primary); }
.metric-card .metric-label { font-size: 0.7rem; color: var(--text-secondary); }
.metric-card.warning { border-top-color: #FF9800; } .metric-card.danger { border-top-color: #EF5350; }
.metric-card.success { border-top-color: #4CAF50; }
section[data-testid="stSidebar"] { background: linear-gradient(180deg, #1E3A5F, #2B5A8C); }
section[data-testid="stSidebar"] h1, section[data-testid="stSidebar"] h2, section[data-testid="stSidebar"] h3,
section[data-testid="stSidebar"] label, section[data-testid="stSidebar"] .stCaption { color: rgba(255,255,255,0.9) !important; }
section[data-testid="stSidebar"] .stButton>button { background: rgba(255,255,255,0.15) !important; color: white !important;
    border: 1px solid rgba(255,255,255,0.25) !important; border-radius: var(--radius-sm) !important; }
.stButton>button[data-testid="baseButton-primary"] { background: linear-gradient(135deg, #2196F3, #1976D2) !important;
    border: none !important; border-radius: var(--radius-sm) !important; font-weight: 600 !important; }
.stDataFrame { border-radius: var(--radius-sm) !important; box-shadow: var(--shadow-sm); }
.stAlert { border-radius: var(--radius-sm) !important; }
hr { margin: 0.5rem 0; border-color: var(--border); }
.card { background: var(--card-bg); border: 1px solid var(--border); border-radius: var(--radius-md);
    padding: 0.6rem 0.9rem; margin-bottom: 0.5rem; box-shadow: var(--shadow-sm); }
</style>
"""

# ==================== 权限系统 ====================
ADMIN_USER = "wuhaoyang127"
ADMIN_PW = "Sa1248jkl@why050212"
USER_FILE = "/tmp/parking_users.json"

ROLES = {
    "admin": {"can_configure": True, "can_manage_users": True, "can_run_simulation": True,
              "can_export": True, "can_debug": True, "label": "管理员"},
    "viewer": {"can_configure": False, "can_manage_users": False, "can_run_simulation": True,
               "can_export": False, "can_debug": False, "label": "访客"},
}
EXTRA_PERMS = {"can_configure": "调整参数", "can_export": "下载结果", "can_debug": "调试参数"}

def hash_pw(pw): return hashlib.sha256(pw.encode()).hexdigest()

def load_users():
    if "all_users" not in st.session_state: st.session_state.all_users = {}
    try:
        if Path(USER_FILE).exists():
            st.session_state.all_users.update(json.loads(Path(USER_FILE).read_text(encoding="utf-8")))
    except: pass
    return st.session_state.all_users

def save_users(users):
    st.session_state.all_users = users
    try: Path(USER_FILE).write_text(json.dumps(users, indent=2, ensure_ascii=False), encoding="utf-8")
    except: pass

def check_login():
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False; st.session_state.username = None
        st.session_state.role = None; st.session_state.user_perms = {}
    if not st.session_state.logged_in:
        token = st.query_params.get("t", None)
        if token:
            try:
                uname, role_str = base64.b64decode(token).decode().split("|", 1)
                st.session_state.logged_in = True; st.session_state.username = uname
                st.session_state.role = role_str
                st.session_state.user_perms = load_users().get(uname, {}).get("perms", {}) if role_str != "admin" else {}
            except: st.query_params.clear()
    if not st.session_state.logged_in:
        st.markdown('<div style="text-align:center;padding:2rem 0 0.5rem"><div style="font-size:3rem">🚗</div>'
            '<h1 style="border:none;font-size:1.4rem!important">智能停车场优化系统</h1>'
            '<p style="color:#607D8B">车位分配 · 纵深移位 · 仿真对比</p></div>', unsafe_allow_html=True)
        c1, c2, c3 = st.columns([1, 2.5, 1])
        with c2:
            tab_login, tab_register = st.tabs(["登录", "注册"])
            with tab_login:
                username = st.text_input("用户名", key="login_user").strip()
                password = st.text_input("密码", type="password", key="login_pw").strip()
                if st.button("登录", type="primary", use_container_width=True):
                    ok = False
                    if username == ADMIN_USER and password == ADMIN_PW:
                        st.session_state.logged_in = True; st.session_state.username = ADMIN_USER
                        st.session_state.role = "admin"; st.session_state.user_perms = {}; ok = True
                    if not ok:
                        users = load_users()
                        if username in users and users[username]["password"] == hash_pw(password):
                            st.session_state.logged_in = True; st.session_state.username = username
                            st.session_state.role = users[username]["role"]
                            st.session_state.user_perms = users[username].get("perms", {}); ok = True
                    if ok:
                        st.query_params["t"] = base64.b64encode(
                            f"{st.session_state.username}|{st.session_state.role}".encode()).decode()
                        st.rerun()
                    else: st.error("用户名或密码错误")
            with tab_register:
                reg_user = st.text_input("新用户名", key="reg_user").strip()
                reg_pw = st.text_input("密码", type="password", key="reg_pw").strip()
                reg_pw2 = st.text_input("确认密码", type="password", key="reg_pw2").strip()
                if st.button("注册", use_container_width=True):
                    if not reg_user or not reg_pw: st.error("请填写用户名和密码")
                    elif reg_pw != reg_pw2: st.error("两次密码不一致")
                    elif reg_user == ADMIN_USER or reg_user in load_users(): st.error("用户名已存在")
                    else:
                        users = load_users()
                        users[reg_user] = {"password": hash_pw(reg_pw), "role": "viewer", "perms": {}}
                        save_users(users)
                        if reg_user in load_users(): st.success("注册成功！切换到登录标签页")
                        else: st.error("存储失败，请重试")
        st.stop()

# ==================== 停车场布局 ====================
def build_network(n_spots, tandem_ratio):
    net = RoadNetwork()
    net.add_node(RoadNode("ENTRY", NodeType.ENTRY, 0, 0))
    net.add_node(RoadNode("N0", NodeType.ROAD_NODE, 5, 0)); net.add_edge("ENTRY", "N0", 5)
    spots = []; n_tandem = int(n_spots*tandem_ratio/2); n_std = n_spots - n_tandem*2
    for i in range(n_std):
        sid = f"A{i+1:02d}"
        net.add_node(RoadNode(sid, NodeType.PARKING_SPOT, 8+i*5, 3, SpotType.STANDALONE, sid, 1))
        d = 3+i*5; net.add_edge("N0", sid, d); net.add_edge(sid, "N0", d)
        spots.append(Spot(sid, SpotType.STANDALONE, sid, sid, 1))
    for g in range(n_tandem):
        gid = f"G{g+1}"; prev = "N0"
        for d in range(1, 3):
            sid = f"{gid}-{d}"
            net.add_node(RoadNode(sid, NodeType.PARKING_SPOT, 30+g*8+d*4, 3, SpotType.TANDEM, gid, d))
            net.add_edge(prev, sid, 4); net.add_edge(sid, prev, 4); prev = sid
            spots.append(Spot(sid, SpotType.TANDEM, sid, gid, d))
    return net, spots

def run_single(net, spots, vehicles, strategy, seed):
    pe = PathEngine(net); lot = ParkingLot(spots)
    engine = SimulationEngine(lot, pe, vehicles, strategy, seed=seed)
    t0 = time.time(); events = engine.run()
    m = compute_metrics(events, len(spots)); m["runtime_s"] = round(time.time()-t0, 3)
    m["strategy"] = strategy.name; return m, events, lot

def metric_card(label, value, variant="default"):
    cls = f"metric-card {variant}" if variant != "default" else "metric-card"
    st.markdown(f'<div class="{cls}"><div class="metric-value">{value}</div><div class="metric-label">{label}</div></div>',
                unsafe_allow_html=True)

# ==================== 时间轴系统 ====================
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

def _interp(path_nodes, progress, net):
    if not path_nodes or len(path_nodes) < 2: return None
    segs = []; total = 0.0
    for i in range(len(path_nodes)-1):
        fn = net.nodes.get(path_nodes[i]); tn = net.nodes.get(path_nodes[i+1])
        if fn and tn:
            sl = max(math.hypot(tn.x-fn.x, tn.y-fn.y), 1.0); segs.append((fn, tn, sl)); total += sl
    if total == 0: return None
    target = progress*total; acc = 0.0
    for fn, tn, sl in segs:
        if acc+sl >= target:
            sp = (target-acc)/sl
            return (fn.x+(tn.x-fn.x)*sp, fn.y+(tn.y-fn.y)*sp)
        acc += sl
    l = segs[-1]; return (l[1].x, l[1].y)

def get_state_at_time(t, timeline, net, spots):
    vl = timeline["vehicles"]
    ss = {s.spot_id: {"occ": False, "by": None, "blocked": False} for s in spots}
    dv = []
    for vid, tl in vl.items():
        arr = tl["arrival_time"]; asg = tl["assigned_time"]; ent = tl["spot_entry_time"]
        ds = tl["departure_start"]; de = tl["departure_end"]
        if arr is None or t < arr or tl["rejected"] or asg is None: continue
        if ent is not None and asg <= t < ent:
            p = (t-asg)/max(ent-asg, 0.1); pos = _interp(tl["path_nodes"], p, net)
            if pos: dv.append({"vid": vid, "x": pos[0], "y": pos[1], "st": "驶入", "target": tl["spot_id"]})
            continue
        if ent is not None and (ds is None or t < ds):
            sid = tl["spot_id"]
            if sid and sid in ss: ss[sid]["occ"] = True; ss[sid]["by"] = vid
            continue
        if ds is not None and (de is None or t < de):
            for sh in tl["shifts"]:
                if sh["start"] <= t < (sh["end"] or float('inf')):
                    sp = (t-sh["start"])/max((sh["end"]or t+1)-sh["start"],0.1)
                    if sh["from"] in net.nodes and sh["to"] in net.nodes:
                        fn=net.nodes[sh["from"]]; tn=net.nodes[sh["to"]]
                        dv.append({"vid":vid,"x":fn.x+(tn.x-fn.x)*min(sp,1),"y":fn.y+(tn.y-fn.y)*min(sp,1),
                                   "st":"移位","target":sh["to"]})
                    break
            else:
                sid=tl["spot_id"]
                if sid in net.nodes:
                    sn=net.nodes[sid]; ex=next((n for n in net.nodes.values() if n.node_type==NodeType.ENTRY),None)
                    if ex:
                        p=(t-ds)/max((de or t+1)-ds,0.1)
                        dv.append({"vid":vid,"x":sn.x+(ex.x-sn.x)*min(p,1),"y":sn.y+(ex.y-sn.y)*min(p,1),
                                   "st":"驶离","target":"出口"})
    sg={};[sg.setdefault(s.stack_group_id,[]).append(s) for s in spots]
    for g,grp in sg.items():
        grp.sort(key=lambda s:s.depth)
        for i,inner in enumerate(grp):
            for j in range(i):
                if ss[grp[j].spot_id]["occ"] and ss[inner.spot_id]["occ"]: ss[inner.spot_id]["blocked"]=True
    return {"ss":ss, "dv":dv}

# ==================== 主入口 ====================
st.set_page_config(page_title="智能停车场优化", page_icon="🚗", layout="wide")
st.markdown(GLOBAL_CSS, unsafe_allow_html=True)
check_login()
role = ROLES[st.session_state.role]

if "replay_time" not in st.session_state: st.session_state.replay_time = 0.0
if "replay_playing" not in st.session_state: st.session_state.replay_playing = False
if "replay_speed" not in st.session_state: st.session_state.replay_speed = 1.0

with st.sidebar:
    st.markdown(f'<div style="display:flex;align-items:center;gap:8px;padding:0.3rem 0 0.8rem 0;">'
        f'<div style="width:32px;height:32px;border-radius:50%;background:rgba(255,255,255,0.2);'
        f'display:flex;align-items:center;justify-content:center;font-size:1rem">🚗</div>'
        f'<div><div style="font-weight:700;font-size:0.9rem;color:white;">{st.session_state.username}</div>'
        f'<div style="font-size:0.7rem;color:rgba(255,255,255,0.7);">{role["label"]}</div></div></div>', unsafe_allow_html=True)
    if st.button("🚪 退出", use_container_width=True):
        st.session_state.logged_in = False; st.query_params.clear()
        st.markdown('<script>history.replaceState(null,"",location.pathname)</script>', unsafe_allow_html=True); st.stop()
    st.markdown("<hr style='border-color:rgba(255,255,255,0.15);margin:0.3rem 0;'>", unsafe_allow_html=True)
    if role["can_manage_users"]:
        with st.expander("🔧 用户管理", expanded=False):
            users = load_users()
            if not users: st.caption("暂无注册用户")
            for u, info in users.items():
                rl = ROLES.get(info["role"], {}).get("label", info["role"])
                ca, cb = st.columns([2.5, 1.5]); ca.write(f"**{u}** — {rl}")
                if cb.button("🗑", key=f"del_{u}"): del users[u]; save_users(users); st.rerun()
            st.divider(); st.caption("**授权额外权限：**")
            for uname, info in users.items():
                with st.expander(f"⚙ {uname}", expanded=False):
                    for pk, plabel in EXTRA_PERMS.items():
                        nv = st.checkbox(plabel, value=info.get("perms", {}).get(pk, False), key=f"perm_{uname}_{pk}")
                        if nv != info.get("perms", {}).get(pk, False):
                            users[uname].setdefault("perms", {})[pk] = nv; save_users(users); st.rerun()
        st.markdown("<hr style='border-color:rgba(255,255,255,0.15);margin:0.3rem 0;'>", unsafe_allow_html=True)
    st.markdown("### ⚙️ 仿真配置")
    perms = st.session_state.user_perms; disabled = not (role["can_configure"] or perms.get("can_configure"))
    n_spots = st.slider("车位数", 5, 50, 15, disabled=disabled)
    tandem_ratio = st.slider("纵深比例", 0.0, 1.0, 0.5, 0.1, disabled=disabled)
    n_vehicles = st.slider("车辆数", 10, 200, 60, disabled=disabled)
    seed = st.number_input("随机种子", 0, 999, 42, disabled=disabled)
    if disabled: st.caption("⚠️ 只读")
    strategy_name = st.selectbox("策略", list(STRATEGY_LABELS.keys()), format_func=lambda x: STRATEGY_LABELS[x])
    run = st.button("▶️ 运行仿真", type="primary", use_container_width=True, disabled=not role["can_run_simulation"])

st.title("🚗 智能停车场车位分配优化系统")

if run or st.session_state.get("sim_has_run"):
    if run:
        net, spots = build_network(n_spots, tandem_ratio); pe = PathEngine(net)
        st.session_state.sim_net = net; st.session_state.sim_spots = spots; st.session_state.sim_pe = pe
        st.session_state.sim_n_spots = n_spots; st.session_state.sim_n_vehicles = n_vehicles
        st.session_state.sim_seed = seed; st.session_state.sim_strategy_name = strategy_name
        st.session_state.sim_has_run = True
    else:
        net = st.session_state.sim_net; spots = st.session_state.sim_spots; pe = st.session_state.sim_pe
        n_spots = st.session_state.sim_n_spots; n_vehicles = st.session_state.sim_n_vehicles
        seed = st.session_state.sim_seed; strategy_name = st.session_state.sim_strategy_name
    sa = sum(1 for s in spots if s.spot_type == SpotType.STANDALONE)
    ta = sum(1 for s in spots if s.spot_type == SpotType.TANDEM)
    st.markdown(f'<div class="card">路网: <b>{len(spots)}</b> 车位 (<b>{sa}</b>独立+<b>{ta}</b>纵深) | <b>{n_vehicles}</b>辆车 | 种子: <b>{seed}</b></div>', unsafe_allow_html=True)

    if strategy_name == "compare_all" and run:
        strats = {"greedy": GreedyStrategy(), "fcfs": FCFS(), "nearest": NearestPath(),
                  "random": RandomAssign(), "departure_greedy": DepartureOrderGreedy()}
        all_m = []; pbar = st.progress(0)
        for i, (nm, stg) in enumerate(strats.items()):
            vehs = generate_demand(total_vehicles=n_vehicles, seed=seed)
            m, _, _ = run_single(net, spots, vehs, stg, seed); all_m.append(m)
            pbar.progress((i+1)/len(strats))
        pbar.empty()
        df = pd.DataFrame(all_m)[["strategy","satisfaction_rate","spatial_utilization","shift_count",
                                    "shift_distance_m","total_drive_distance_m","rejected_count","runtime_s"]]
        df.columns = ["策略","满足率","利用率","移位次数","移位距离(m)","行驶距离(m)","拒绝数","耗时(s)"]
        best = max(all_m, key=lambda m: m["satisfaction_rate"])
        st.markdown(f'<div class="card" style="border-left:4px solid #4CAF50">🏆 推荐: <b>{STRATEGY_LABELS.get(best["strategy"],best["strategy"])}</b> 满足率 {best["satisfaction_rate"]:.1%}</div>', unsafe_allow_html=True)
        styled = df.style.format({"满足率":"{:.1%}","利用率":"{:.1%}","移位距离(m)":"{:.1f}","行驶距离(m)":"{:.1f}","耗时(s)":"{:.3f}"})
        st.dataframe(styled, use_container_width=True, hide_index=True)
        c1, c2 = st.columns(2)
        with c1: st.bar_chart(df.set_index("策略")["满足率"], height=220)
        with c2: st.bar_chart(df.set_index("策略")["移位次数"], height=220)
        st.download_button("📥 下载 CSV", df.to_csv(index=False).encode('utf-8'), "parking_comparison.csv", "text/csv")

    elif run:
        smap = {"greedy": GreedyStrategy(), "fcfs": FCFS(), "nearest": NearestPath(),
                "random": RandomAssign(), "departure_greedy": DepartureOrderGreedy()}
        vehs = generate_demand(total_vehicles=n_vehicles, seed=seed)
        metrics, events, lot = run_single(net, spots, vehs, smap[strategy_name], seed)
        events_raw = [{"time": e.time, "type": e.event_type.value, "vehicle_id": e.vehicle_id or "",
                       "spot_id": e.spot_id or "", "metadata": dict(e.metadata)} for e in events]
        st.session_state.sim_events_raw = events_raw; st.session_state.sim_metrics = metrics
        timeline = build_timeline(events, net, pe)
        timeline["events_by_time"] = {t: [{"time": e.time, "type": e.event_type.value,
            "vehicle_id": e.vehicle_id or "", "spot_id": e.spot_id or "", "metadata": dict(e.metadata)}
            for e in evts] for t, evts in timeline["events_by_time"].items()}
        st.session_state.sim_timeline = timeline; st.rerun()
    else:
        events = st.session_state.sim_events_raw; metrics = st.session_state.sim_metrics
        timeline = st.session_state.sim_timeline; max_time = timeline["max_time"]

        st.subheader("📊 关键指标")
        c1,c2,c3,c4=st.columns(4)
        with c1: metric_card("满足率",f"{metrics['satisfaction_rate']:.1%}","success" if metrics['satisfaction_rate']>0.5 else "danger")
        with c2: metric_card("利用率",f"{metrics['spatial_utilization']:.1%}")
        with c3: metric_card("移位次数",str(metrics["shift_count"]),"warning" if metrics["shift_count"]>0 else "default")
        with c4: metric_card("拒绝数",str(metrics["rejected_count"]),"danger" if metrics["rejected_count"]>0 else "default")
        c5,c6,c7,c8=st.columns(4)
        with c5: metric_card("行驶距离",f"{metrics['total_drive_distance_m']:.0f}m")
        with c6: metric_card("移位距离",f"{metrics['shift_distance_m']:.0f}m")
        with c7: metric_card("平均等待",f"{metrics['avg_wait_time_s']:.1f}s")
        with c8: metric_card("运行耗时",f"{metrics['runtime_s']:.3f}s")

        buf=sum(1 for e in events if e["type"]=="buffer_failed")
        rj=sum(1 for e in events if e["type"]=="rejected")
        if buf or rj: st.warning(f"降级: {buf} 缓冲失败, {rj} 拒绝")

        # ——— 时间轴回放 ———
        all_times = timeline["all_times"]
        st.markdown("---"); st.subheader("⏱️ 仿真时间轴")

        ctl1, ctl2, ctl3, ctl4, ctl5 = st.columns([1, 1, 5, 1, 1])
        with ctl1:
            if st.button("⏮", help="起点", use_container_width=True): st.session_state.replay_time = 0.0
        with ctl2:
            if st.button("◀", help="后退", use_container_width=True):
                prev_t = 0.0
                for t_val in all_times:
                    if t_val < st.session_state.replay_time - 0.001: prev_t = t_val
                st.session_state.replay_time = prev_t
        with ctl3:
            rt = float(st.session_state.replay_time)
            new_time = st.slider("时间", 0.0, max_time, value=rt, step=0.5, key="time_slider")
            if abs(new_time - rt) > 0.001: st.session_state.replay_time = new_time
        with ctl4:
            if st.button("▶", help="前进", use_container_width=True):
                next_t = max_time
                for t_val in all_times:
                    if t_val > st.session_state.replay_time + 0.001: next_t = t_val; break
                st.session_state.replay_time = next_t
        with ctl5:
            if st.button("⏭", help="终点", use_container_width=True): st.session_state.replay_time = max_time

        st.caption(f"⏰ {st.session_state.replay_time:.1f}s / {max_time:.0f}s")

        # 动态渲染
        t_now = st.session_state.replay_time
        state = get_state_at_time(t_now, timeline, net, spots)

        st.subheader(f"🅿️ 停车场布局 (t={t_now:.1f}s)")
        st.caption("🟢空闲 🔴占用 🟠被挡")
        cols = st.columns(min(len(spots), 8))
        for idx, s in enumerate(spots):
            c = cols[idx % 8]; sd = state["ss"].get(s.spot_id, {})
            if sd.get("occ") and sd.get("blocked"): bg = "#ffa500"; icon = "🚗"
            elif sd.get("occ"): bg = "#ff6b6b"; icon = "🚗"
            else: bg = "#51cf66"; icon = "⬜"
            c.markdown(f"<div style='background:{bg};padding:3px;margin:1px;border-radius:4px;text-align:center;font-size:9px;color:white'>{s.spot_id}<br>{icon}</div>", True)

        # 路网图
        st.subheader("🛣️ 路网与车辆路径")
        fig = go.Figure()
        for edge in net.edges:
            fn = net.nodes[edge.from_node]; tn = net.nodes[edge.to_node]
            is_se = fn.node_type == NodeType.PARKING_SPOT or tn.node_type == NodeType.PARKING_SPOT
            fig.add_trace(go.Scatter(x=[fn.x, tn.x], y=[fn.y, tn.y], mode='lines',
                line=dict(color='#90A4AE', width=2, dash='dot' if is_se else 'solid'), showlegend=False, hoverinfo='none'))
        en = next((n for n in net.nodes.values() if n.node_type == NodeType.ENTRY), None)
        if en: fig.add_trace(go.Scatter(x=[en.x], y=[en.y], mode='markers',
            marker=dict(color='#2E7D32', size=14, symbol='triangle-up'), showlegend=False))
        for s in spots:
            if s.spot_id not in net.nodes: continue
            node = net.nodes[s.spot_id]; sd = state["ss"].get(s.spot_id, {})
            if sd.get("occ") and sd.get("blocked"): color = '#FF9800'
            elif sd.get("occ"): color = '#EF5350'
            else: color = '#66BB6A'
            fig.add_trace(go.Scatter(x=[node.x], y=[node.y], mode='markers',
                marker=dict(color=color, size=11, symbol='square'), showlegend=False, hoverinfo='skip'))
        for dv in state["dv"]:
            fig.add_trace(go.Scatter(x=[dv["x"]], y=[dv["y"]], mode='markers+text',
                marker=dict(color='#2196F3', size=14, symbol='circle'), text=dv["vid"],
                textposition="top center", textfont=dict(size=8), showlegend=False, hoverinfo='skip'))
            if dv.get("from_node") and dv["from_node"] in net.nodes:
                fn = net.nodes[dv["from_node"]]
                fig.add_trace(go.Scatter(x=[fn.x, dv["x"]], y=[fn.y, dv["y"]], mode='lines',
                    line=dict(color='#64B5F6', width=2, dash='dash'), showlegend=False, hoverinfo='none'))
        fig.update_layout(xaxis_title="X (m)", yaxis_title="Y (m)", height=400,
            margin=dict(l=20, r=20, t=20, b=20), plot_bgcolor='#FAFBFC')
        st.plotly_chart(fig, use_container_width=True)

        occ = sum(1 for sd in state["ss"].values() if sd["occ"])
        c1,c2,c3=st.columns(3)
        c1.metric("占用",f"{occ}/{len(spots)}");c2.metric("行驶中",str(len(state["dv"])));c3.metric("时间",f"{t_now:.1f}s")

        st.download_button("📥 下载指标", pd.DataFrame([metrics]).to_csv(index=False).encode('utf-8'),
                           f"parking_{strategy_name}.csv", "text/csv")

        with st.expander("📋 事件日志", expanded=False):
            ev = [{"时间":f"{e['time']:.0f}s","类型":e["type"],"车辆":e["vehicle_id"] or "-","车位":e["spot_id"] or "-",**e["metadata"]} for e in events[:200]]
            st.dataframe(pd.DataFrame(ev), use_container_width=True, hide_index=True)
else:
    st.markdown('<div style="text-align:center;padding:2rem">🚗<h2>车位分配 · 纵深移位 · 仿真对比</h2><p style="color:#607D8B">👈 左侧配置参数，点击「运行仿真」开始</p></div>', unsafe_allow_html=True)
