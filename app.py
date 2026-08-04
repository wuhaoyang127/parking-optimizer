"""智能停车场优化 — Dashboard (Streamlit) + 权限管理"""

import sys, hashlib, json, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

import streamlit as st
import pandas as pd
import time

from parking_opt.domain.spot import RoadNetwork, RoadNode, NodeType, Spot, SpotType
from parking_opt.routing.path_engine import PathEngine
from parking_opt.simulation.parking_lot import ParkingLot
from parking_opt.simulation.engine import SimulationEngine
from parking_opt.simulation.arrival import generate_demand
from parking_opt.strategies.baselines import FCFS, NearestPath, RandomAssign
from parking_opt.strategies.greedy import GreedyStrategy, DepartureOrderGreedy
from parking_opt.evaluation.metrics import compute_metrics

# ==================== 权限系统 ====================
USERS_FILE = Path(__file__).parent / "configs" / "users.json"
USERS_FILE.parent.mkdir(exist_ok=True)

DEFAULT_USERS = {
    "admin": {"password": hashlib.sha256("admin123".encode()).hexdigest(), "role": "admin"},
    "viewer": {"password": hashlib.sha256("view123".encode()).hexdigest(), "role": "viewer"},
}

ROLES = {
    "admin": {"can_configure": True, "can_manage_users": True, "can_run_simulation": True, "can_export": True, "label": "管理员"},
    "viewer": {"can_configure": False, "can_manage_users": False, "can_run_simulation": True, "can_export": False, "label": "访客（只读）"},
}


def load_users():
    if USERS_FILE.exists():
        with open(USERS_FILE, encoding="utf-8") as f:
            return json.load(f)
    save_users(DEFAULT_USERS)
    return DEFAULT_USERS.copy()


def save_users(users):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2, ensure_ascii=False)


def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()


def check_login():
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
        st.session_state.username = None
        st.session_state.role = None

    if not st.session_state.logged_in:
        st.title("🔐 智能停车场优化系统 — 登录")
        c1, c2, c3 = st.columns([1, 2, 1])
        with c2:
            username = st.text_input("用户名")
            password = st.text_input("密码", type="password")
            if st.button("登录", type="primary", use_container_width=True):
                users = load_users()
                if username in users and users[username]["password"] == hash_pw(password):
                    st.session_state.logged_in = True
                    st.session_state.username = username
                    st.session_state.role = users[username]["role"]
                    st.rerun()
                else:
                    st.error("用户名或密码错误")
            st.caption("默认: admin/admin123 | viewer/view123")
        st.stop()


def build_network(n_spots, tandem_ratio):
    net = RoadNetwork()
    net.add_node(RoadNode("ENTRY", NodeType.ENTRY, 0, 0))
    net.add_node(RoadNode("N0", NodeType.ROAD_NODE, 5, 0))
    net.add_edge("ENTRY", "N0", 5)
    spots = []
    n_tandem = int(n_spots * tandem_ratio / 2)
    n_std = n_spots - n_tandem * 2
    for i in range(n_std):
        sid = f"A{i+1:02d}"
        net.add_node(RoadNode(sid, NodeType.PARKING_SPOT, 8+i*5, 3, SpotType.STANDALONE, sid, 1))
        d = 3 + i*5; net.add_edge("N0", sid, d); net.add_edge(sid, "N0", d)
        spots.append(Spot(sid, SpotType.STANDALONE, sid, sid, 1))
    for g in range(n_tandem):
        gid = f"G{g+1}"; prev = "N0"
        for d in range(1, 3):
            sid = f"{gid}-{d}"
            net.add_node(RoadNode(sid, NodeType.PARKING_SPOT, 30+g*8+d*4, 3, SpotType.TANDEM, gid, d))
            net.add_edge(prev, sid, 4); net.add_edge(sid, prev, 4)
            prev = sid
            spots.append(Spot(sid, SpotType.TANDEM, sid, gid, d))
    return net, spots


def run_single(net, spots, vehicles, strategy, seed):
    pe = PathEngine(net)
    lot = ParkingLot(spots)
    engine = SimulationEngine(lot, pe, vehicles, strategy, seed=seed)
    t0 = time.time()
    events = engine.run()
    m = compute_metrics(events, len(spots))
    m["runtime_s"] = round(time.time()-t0, 3)
    m["strategy"] = strategy.name
    return m, events


# ==================== 主入口 ====================
st.set_page_config(page_title="智能停车场优化", layout="wide")
check_login()

role = ROLES[st.session_state.role]
st.sidebar.title(f"👤 {st.session_state.username} ({role['label']})")
if st.sidebar.button("🚪 退出登录"):
    st.session_state.logged_in = False
    st.rerun()

# —— 用户管理（仅管理员） ——
if role["can_manage_users"]:
    with st.sidebar.expander("🔧 用户管理"):
        users = load_users()
        for u, info in users.items():
            rl = ROLES.get(info["role"], {}).get("label", info["role"])
            ca, cb = st.columns([3, 1])
            ca.write(f"**{u}** — {rl}")
            if u != "admin" and cb.button("🗑", key=f"del_{u}"):
                del users[u]; save_users(users); st.rerun()
        st.divider()
        nu = st.text_input("新用户名", key="nu")
        npw = st.text_input("密码", type="password", key="npw")
        if st.button("➕ 添加访客") and nu and npw:
            users[nu] = {"password": hash_pw(npw), "role": "viewer"}
            save_users(users); st.success(f"已创建 {nu}"); st.rerun()
    st.sidebar.divider()

# —— 仿真配置 ——
st.sidebar.header("⚙️ 仿真配置")
disabled = not role["can_configure"]
n_spots = st.sidebar.slider("车位数", 5, 50, 15, disabled=disabled)
tandem_ratio = st.sidebar.slider("纵深比例", 0.0, 1.0, 0.5, 0.1, disabled=disabled)
n_vehicles = st.sidebar.slider("车辆数", 10, 200, 60, disabled=disabled)
seed = st.sidebar.number_input("随机种子", 0, 999, 42, disabled=disabled)
if disabled:
    st.sidebar.caption("⚠️ 只读：参数由管理员预设")
strategy_name = st.sidebar.selectbox("策略", ["greedy", "fcfs", "nearest", "random", "departure_greedy", "compare_all"])
run = st.sidebar.button("▶️ 运行仿真", type="primary", use_container_width=True, disabled=not role["can_run_simulation"])

# —— 主界面 ——
st.title("🚗 智能停车场车位分配优化系统")

if run:
    net, spots = build_network(n_spots, tandem_ratio)
    sa = sum(1 for s in spots if s.spot_type == SpotType.STANDALONE)
    ta = sum(1 for s in spots if s.spot_type == SpotType.TANDEM)
    st.info(f"路网: {len(spots)} 车位 ({sa} 独立 + {ta} 纵深) | {n_vehicles} 辆车 | 种子: {seed}")

    if strategy_name == "compare_all":
        strats = {"greedy": GreedyStrategy(), "fcfs": FCFS(), "nearest": NearestPath(),
                  "random": RandomAssign(), "departure_greedy": DepartureOrderGreedy()}
        all_m = []
        pbar = st.progress(0)
        for i, (nm, stg) in enumerate(strats.items()):
            vehs = generate_demand(total_vehicles=n_vehicles, seed=seed)
            m, _ = run_single(net, spots, vehs, stg, seed)
            all_m.append(m); pbar.progress((i+1)/len(strats))
        pbar.empty()
        df = pd.DataFrame(all_m)[["strategy","satisfaction_rate","spatial_utilization","shift_count",
                                    "shift_distance_m","total_drive_distance_m","rejected_count","runtime_s"]]
        df.columns = ["策略","满足率","利用率","移位次数","移位距离(m)","行驶距离(m)","拒绝数","耗时(s)"]
        st.subheader("📊 策略对比")
        st.dataframe(df.style.format({"满足率":"{:.1%}","利用率":"{:.1%}","移位距离(m)":"{:.1f}","行驶距离(m)":"{:.1f}","耗时(s)":"{:.3f}"}),
                     use_container_width=True, hide_index=True)
        st.subheader("📈 满足率对比")
        st.bar_chart(df.set_index("策略")["满足率"])
        best = max(all_m, key=lambda m: m["satisfaction_rate"])
        st.success(f"🏆 推荐: **{best['strategy']}** (满足率 {best['satisfaction_rate']:.1%}, 拒绝 {best['rejected_count']} 辆)")
    else:
        smap = {"greedy": GreedyStrategy(), "fcfs": FCFS(), "nearest": NearestPath(),
                "random": RandomAssign(), "departure_greedy": DepartureOrderGreedy()}
        vehs = generate_demand(total_vehicles=n_vehicles, seed=seed)
        metrics, events = run_single(net, spots, vehs, smap[strategy_name], seed)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("满足率", f"{metrics['satisfaction_rate']:.1%}")
        c2.metric("利用率", f"{metrics['spatial_utilization']:.1%}")
        c3.metric("移位次数", metrics["shift_count"])
        c4.metric("拒绝数", metrics["rejected_count"])
        c5, c6, c7, c8 = st.columns(4)
        c5.metric("行驶距离", f"{metrics['total_drive_distance_m']:.0f}m")
        c6.metric("移位距离", f"{metrics['shift_distance_m']:.0f}m")
        c7.metric("等待时间", f"{metrics['avg_wait_time_s']:.1f}s")
        c8.metric("耗时", f"{metrics['runtime_s']:.3f}s")

        st.subheader("📋 事件日志")
        ev = [{"时间(s)": f"{e.time:.0f}", "类型": e.event_type.value, "车辆": e.vehicle_id or "", "车位": e.spot_id or "", **e.metadata} for e in events[:200]]
        st.dataframe(pd.DataFrame(ev), use_container_width=True, hide_index=True)
else:
    st.markdown("""
    ### 👈 左侧配置参数，点击"运行仿真"开始

    | 策略 | 说明 |
    |---|---|
    | 🥇 贪心（主方法） | 独立车位→depth=1→depth=2，动态缓冲位 |
    | 🥈 FCFS | 先到先服务 |
    | 🥉 最近路径 | 最近可用车位 |
    | 随机 | 随机分配 |
    | 离场贪心 | 最近可用+离场顺序优化 |

    **权限：** 管理员完整控制 | 访客只读
    """)
    if role["can_manage_users"]:
        st.info("🔧 你是管理员，可在左侧面板管理用户。")
