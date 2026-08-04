"""智能停车场优化 — Dashboard (Streamlit)"""

import sys
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

st.set_page_config(page_title="智能停车场优化", layout="wide")
st.title("🚗 智能停车场车位分配优化系统")

# ====== 侧边栏配置 ======
with st.sidebar:
    st.header("⚙️ 仿真配置")
    n_spots = st.slider("车位数", 5, 50, 15)
    tandem_ratio = st.slider("纵深车位比例", 0.0, 1.0, 0.5, 0.1)
    n_vehicles = st.slider("车辆数", 10, 200, 60)
    seed = st.number_input("随机种子", 0, 999, 42)
    strategy_name = st.selectbox("策略", ["greedy", "fcfs", "nearest", "random", "departure_greedy",
                                          "compare_all"])
    run = st.button("▶️ 运行仿真", type="primary", use_container_width=True)


# ====== 路网构建 ======
def build_network(n_spots: int, tandem_ratio: float) -> tuple[RoadNetwork, list[Spot]]:
    net = RoadNetwork()
    net.add_node(RoadNode("ENTRY", NodeType.ENTRY, 0, 0))
    net.add_node(RoadNode("N0", NodeType.ROAD_NODE, 5, 0))
    net.add_edge("ENTRY", "N0", 5)
    spots = []

    n_tandem_groups = int(n_spots * tandem_ratio / 2)
    n_standalone = n_spots - n_tandem_groups * 2

    # 独立车位
    for i in range(n_standalone):
        sid = f"A{i+1:02d}"
        net.add_node(RoadNode(sid, NodeType.PARKING_SPOT, 8 + i * 5, 3,
                               SpotType.STANDALONE, sid, 1))
        dist = 3 + i * 5
        net.add_edge("N0", sid, dist)
        net.add_edge(sid, "N0", dist)
        spots.append(Spot(sid, SpotType.STANDALONE, sid, sid, 1))

    # 纵深车位组
    for g in range(n_tandem_groups):
        gid = f"G{g + 1}"
        prev = "N0"
        for d in range(1, 3):
            sid = f"{gid}-{d}"
            net.add_node(RoadNode(sid, NodeType.PARKING_SPOT,
                                   30 + g * 8 + d * 4, 3,
                                   SpotType.TANDEM, gid, d))
            net.add_edge(prev, sid, 4)
            net.add_edge(sid, prev, 4)
            prev = sid
            spots.append(Spot(sid, SpotType.TANDEM, sid, gid, d))

    return net, spots


# ====== 运行单次仿真 ======
def run_single(net, spots, vehicles, strategy):
    pe = PathEngine(net)
    lot = ParkingLot(spots)
    engine = SimulationEngine(lot, pe, vehicles, strategy, seed=seed)
    t0 = time.time()
    events = engine.run()
    elapsed = time.time() - t0
    metrics = compute_metrics(events, len(spots))
    metrics["runtime_s"] = round(elapsed, 3)
    metrics["strategy"] = strategy.name
    return metrics, events


# ====== 主界面 ======
if run:
    net, spots = build_network(n_spots, tandem_ratio)

    actual_standalone = sum(1 for s in spots if s.spot_type == SpotType.STANDALONE)
    actual_tandem = sum(1 for s in spots if s.spot_type == SpotType.TANDEM)

    st.info(f"路网: {len(spots)} 车位 ({actual_standalone} 独立 + {actual_tandem} 纵深) | "
            f"负载: {n_vehicles} 辆车 | 种子: {seed}")

    if strategy_name == "compare_all":
        # 对比所有策略
        strategies = {
            "greedy": GreedyStrategy(),
            "fcfs": FCFS(),
            "nearest": NearestPath(),
            "random": RandomAssign(),
            "departure_greedy": DepartureOrderGreedy(),
        }
        all_metrics = []
        progress = st.progress(0)
        for i, (name, strat) in enumerate(strategies.items()):
            vehicles = generate_demand(total_vehicles=n_vehicles, seed=seed)
            m, _ = run_single(net, spots, vehicles, strat)
            all_metrics.append(m)
            progress.progress((i + 1) / len(strategies))
        progress.empty()

        # 对比表
        df = pd.DataFrame(all_metrics)
        cols = ["strategy", "satisfaction_rate", "spatial_utilization",
                "shift_count", "shift_distance_m", "total_drive_distance_m",
                "rejected_count", "runtime_s"]
        df = df[cols]
        df.columns = ["策略", "满足率", "利用率", "移位次数", "移位距离(m)",
                      "行驶距离(m)", "拒绝数", "耗时(s)"]

        st.subheader("📊 策略对比")
        st.dataframe(df.style.format({
            "满足率": "{:.1%}", "利用率": "{:.1%}",
            "移位距离(m)": "{:.1f}", "行驶距离(m)": "{:.1f}", "耗时(s)": "{:.3f}"
        }), use_container_width=True, hide_index=True)

        # 柱状图
        st.subheader("📈 满足率对比")
        st.bar_chart(df.set_index("策略")["满足率"])

        # 移位
        st.subheader("🔄 移位事件")
        shift_df = df[df["移位次数"] > 0]
        if not shift_df.empty:
            st.dataframe(shift_df[["策略", "移位次数", "移位距离(m)"]],
                         use_container_width=True, hide_index=True)
        else:
            st.write("无移位事件")

        # 推荐
        best = max(all_metrics, key=lambda m: m["satisfaction_rate"])
        st.success(f"🏆 推荐策略: **{best['strategy']}** "
                   f"(满足率 {best['satisfaction_rate']:.1%}, "
                   f"移位 {best['shift_count']} 次)")

    else:
        # 单策略
        strategy_map = {
            "greedy": GreedyStrategy(),
            "fcfs": FCFS(),
            "nearest": NearestPath(),
            "random": RandomAssign(),
            "departure_greedy": DepartureOrderGreedy(),
        }
        vehicles = generate_demand(total_vehicles=n_vehicles, seed=seed)
        metrics, events = run_single(net, spots, vehicles,
                                     strategy_map[strategy_name])

        # 指标卡片
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("满足率", f"{metrics['satisfaction_rate']:.1%}")
        col2.metric("利用率", f"{metrics['spatial_utilization']:.1%}")
        col3.metric("移位次数", metrics["shift_count"])
        col4.metric("拒绝数", metrics["rejected_count"])

        col5, col6, col7, col8 = st.columns(4)
        col5.metric("行驶距离", f"{metrics['total_drive_distance_m']:.0f}m")
        col6.metric("移位距离", f"{metrics['shift_distance_m']:.0f}m")
        col7.metric("等待时间", f"{metrics['avg_wait_time_s']:.1f}s")
        col8.metric("耗时", f"{metrics['runtime_s']:.3f}s")

        # 事件时间线
        st.subheader("📋 事件日志")
        event_data = []
        for e in events[:200]:
            event_data.append({
                "时间(s)": f"{e.time:.0f}",
                "类型": e.event_type.value,
                "车辆": e.vehicle_id or "",
                "车位": e.spot_id or "",
                **e.metadata,
            })
        st.dataframe(pd.DataFrame(event_data), use_container_width=True, hide_index=True)

else:
    st.markdown("""
    ### 👈 左侧配置参数，点击"运行仿真"开始

    本系统模拟智能停车场中车辆到达、车位分配、纵深阻挡和移位操作的全流程。

    **五种策略：**
    - 🥇 **贪心**（主方法）：独立车位→depth=1→depth=2，动态缓冲位
    - 🥈 FCFS：先到先服务
    - 🥉 最近路径：最近可用车位
    - 随机：随机分配
    - 离场贪心：最近可用+离场顺序优化
    """)
