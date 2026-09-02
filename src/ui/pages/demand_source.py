"""仿真设置页：需求数据源选择（自动生成 / 导入 JSON / 真实道闸流水）。"""
from ui.common import *


def _render_demand_source(disabled, role):
    """需求数据源：自动生成 / 导入 JSON / 导入真实道闸流水。返回四元组。"""
    st.markdown("#### 📦 需求数据源")
    demand_source = st.radio(
        "车辆到达/离场需求来源",
        ["自动生成（随机种子）", "导入需求序列 JSON", "导入真实道闸流水 CSV（演示）"],
        horizontal=True,
        disabled=disabled,
        help="导入后所有策略共用同一批车辆需求（保证对比公平），相同种子/相同序列可复现结果",
    )
    import_mode = demand_source.startswith("导入")
    gate_mode = demand_source.startswith("导入真实")
    imported_vehicles = None
    imported_meta = None
    if import_mode:
        if gate_mode:
            sample_path = PROJECT_ROOT / "data" / "samples" / "道闸流水示例.csv"
            if sample_path.exists():
                st.download_button(
                    "📥 下载道闸流水示例 CSV",
                    sample_path.read_bytes(),
                    "道闸流水示例.csv", "text/csv",
                    disabled=not role["can_export"],
                    help="按这个格式准备数据即可导入",
                )
            with st.expander("📖 道闸流水 CSV 填写说明（给停车场运营方）", expanded=False):
                st.markdown("""
**每一行 = 一辆车的一次完整进出记录**，需包含以下列（中英文列名均可）：

| 列 | 必填 | 中文列名 | 英文列名 | 说明 |
|---|---|---|---|---|
| 车牌 | ✅ | `车牌` / `车牌号` | `plate` | 系统默认脱敏，原始车牌不落库 |
| 入场时间 | ✅ | `入场时间` | `entry_time` | `2026-08-30 08:00:00` 或时间戳 |
| 出场时间 | ✅ | `出场时间` | `exit_time` | 必须晚于入场时间 |
| 入口编号 | ⭕ | `入口` | `entry_id` | 可不填 |
| 出口编号 | ⭕ | `出口` | `exit_id` | 可不填 |

**示例**：

```csv
车牌,入场时间,出场时间,入口,出口
京A12345,2026-08-30 08:00:00,2026-08-30 09:30:00,entry_1,exit_1
京B67890,2026-08-30 08:05:00,2026-08-30 08:35:00,entry_1,exit_1
```

**常见错误**：出场早于入场 / 缺列 / 空车牌 / 还在场没离场的车 / Excel 存成了 xlsx。
详细说明见项目文档 `docs/道闸流水CSV填写说明.md`。
""")
            up = st.file_uploader(
                "上传道闸流水 CSV（.csv）", type=["csv"],
                disabled=disabled,
                help="列名支持 车牌/入场时间/出场时间（中英文），可选入口/出口编号；"
                     "系统默认对车牌脱敏后转换为需求序列",
            )
            if up is not None:
                try:
                    from parking_opt.io.realtime_io import gate_csv_to_demand_json
                    demand_text = gate_csv_to_demand_json(up.getvalue().decode("utf-8"))
                    imported_vehicles, imported_meta = parse_demand_json(demand_text)
                    st.session_state.imported_vehicles = imported_vehicles
                    st.session_state.imported_meta = imported_meta
                    st.success(f"✅ 已解析道闸流水 {imported_meta.get('vehicle_count')} 辆车"
                               f"（车牌已脱敏）。运行仿真将以该真实时序为准。")
                except ValueError as exc:
                    st.error(f"❌ 道闸流水解析失败：{exc}")
            if (role["can_export"]
                    and (st.session_state.get("imported_meta") or {}).get("source") == "real_gate"
                    and st.session_state.get("imported_vehicles")):
                st.download_button(
                    "📄 下载转换后的需求序列 JSON",
                    export_demand_json(
                        st.session_state.imported_vehicles,
                        source="real_gate",
                    ).encode("utf-8"),
                    "demand_from_gate_records.json", "application/json",
                    help="把真实道闸流水转换后的需求序列下载保存，便于复现",
                )
        else:
            up = st.file_uploader("上传需求序列 JSON（.json）", type=["json"],
                                  disabled=disabled,
                                  help="文件来自「指标分析页 → 需求时序分布 → 下载/保存需求序列 JSON」")
            if up is not None:
                try:
                    imported_vehicles, imported_meta = parse_demand_json(up.getvalue().decode("utf-8"))
                    st.session_state.imported_vehicles = imported_vehicles
                    st.session_state.imported_meta = imported_meta
                    first = imported_meta.get("generated_at", "未知")
                    seed_of_file = imported_meta.get("seed", "未知")
                    st.success(f"✅ 已解析 {imported_meta.get('vehicle_count')} 辆车（生成时间 {first}，种子 {seed_of_file}）。"
                               f"运行仿真将以该序列为准，忽略「车辆数」设置。")
                except ValueError as exc:
                    st.error(f"❌ 导入失败：{exc}")
            else:
                local_files = list_demand_files()
                if local_files:
                    labels = [disp for _, disp in local_files]
                    sel = st.selectbox(
                        "或从项目文件夹选择（data/demand_exports/）",
                        ["（不选择）"] + labels, key="local_demand_sel",
                        disabled=disabled,
                        help="选择后立即解析该文件作为本次需求序列；文件由「指标分析页 → 保存到项目文件夹」生成",
                    )
                    if sel != "（不选择）":
                        path = local_files[labels.index(sel)][0]
                        try:
                            imported_vehicles, imported_meta = parse_demand_json(
                                path.read_text(encoding="utf-8"))
                            st.session_state.imported_vehicles = imported_vehicles
                            st.session_state.imported_meta = imported_meta
                            st.success(f"✅ 已从项目文件夹加载 {imported_meta.get('vehicle_count')} 辆车：{path.name}")
                        except ValueError as exc:
                            st.error(f"❌ 导入失败：{exc}")
                elif st.session_state.get("imported_vehicles"):
                    imported_vehicles = st.session_state.imported_vehicles
                    imported_meta = st.session_state.get("imported_meta") or {}
                    st.info(f"沿用本会话已导入的需求序列（{len(imported_vehicles)} 辆车）。"
                            f"重新上传文件可替换。")
            if role["can_export"]:
                st.download_button(
                    "📄 下载需求序列 JSON 示例",
                    export_demand_json(
                        generate_demand(total_vehicles=20, seed=42),
                        seed=42,
                        generator_params={"total_vehicles": 20, "sim_duration": 21600},
                    ).encode("utf-8"),
                    "demand_example.json", "application/json",
                    help="示例仅 20 辆车，演示文件格式；导入前可先用它试运行",
                )
    else:
        st.session_state.imported_vehicles = None
        st.session_state.imported_meta = None

    if import_mode:
        st.caption("已导入需求序列：灰色参数不再影响本次仿真（车辆数、需求生成环境参数），其余参数照常生效。")
    return import_mode, gate_mode, imported_vehicles, imported_meta
