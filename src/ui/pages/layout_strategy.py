"""仿真设置页：布局/车位参数、策略与随机次数、算法说明、策略/环境参数控件。"""
from ui.common import *


def _render_layout_and_strategy(disabled, import_mode):
    """布局来源/车位参数 + 策略与随机次数 + 算法说明 + 策略参数 + 环境参数。"""
    c1, c2 = st.columns(2)
    with c1:
        # 布局来源分组：内置示意布局（参数化生成）/ 导入的真实布局（JSON 定义）
        builtin_keys = [k for k in BUILTIN_LAYOUT_KEYS if k in LAYOUT_BUILDERS]
        custom_keys = [k for k in LAYOUT_BUILDERS if k not in BUILTIN_LAYOUT_KEYS]
        source_options = ["内置示意布局"]
        if custom_keys:
            source_options.append("导入的真实布局")
        if st.session_state.get("layout_source") not in source_options:
            st.session_state.layout_source = source_options[0]
        layout_source = st.radio(
            "布局来源", source_options, horizontal=True,
            key="layout_source", disabled=disabled,
            help="内置示意布局按「车位数/纵深比例」参数化生成；导入的真实布局按上传的 JSON 定义")
        if layout_source == "导入的真实布局":
            layout = st.selectbox("真实布局", custom_keys,
                                  format_func=lambda x: LAYOUTS.get(x, x),
                                  disabled=disabled)
            st.caption("真实布局：路网与车位来自导入的 JSON；车辆需求仍为仿真生成。"
                       "车位数/纵深比例滑杆对该布局不生效（已变灰）。")
        else:
            layout = st.selectbox("内置布局", builtin_keys,
                                  format_func=lambda x: LAYOUTS.get(x, x),
                                  disabled=disabled)
        real_layout_mode = layout_source == "导入的真实布局"
        n_spots = st.number_input("车位数（可直接输入）", 5, 500, 15, step=5,
                                  disabled=disabled or real_layout_mode,
                                  help=("真实布局下车位数由 JSON 定义，此项不生效"
                                        if real_layout_mode
                                        else "小数值用 +/- 步进，大数值直接输入；"
                                             "车位数大时所有算法都会运行（CP-SAT/MOSA 带时间熔断）"))
        tandem_ratio = st.slider("纵深比例", 0.0, 1.0, 0.5, 0.1,
                                 disabled=disabled or real_layout_mode,
                                 help=("真实布局下纵深比例由 JSON 定义，此项不生效" if real_layout_mode else None))
    with c2:
        n_vehicles = st.number_input("车辆数（可直接输入）", 10, 2000, 60, step=10,
                                     disabled=disabled or import_mode,
                                     help="小数值用 +/- 步进，大数值直接输入；"
                                          "大型停车场节假日建议 800~2000，车辆越多仿真越慢，"
                                          "「全部对比」在大车辆数下建议先把仿真次数调成 1")
        seed = st.number_input("随机种子", 0, 999, 42, disabled=disabled,
                               help="导入需求序列后仍影响引擎与策略随机性（不影响车辆生成）")
        n_runs = st.slider("仿真次数（多种子取平均）", 1, 10, 3, disabled=disabled,
                           help="随机系统单次结果波动大，多种子取平均更稳定；次数越多越准但越慢")
        wait_policy = st.selectbox("等待调度策略", ["fifo", "shortest"],
                                   format_func=lambda x: "先到先服务（FIFO）" if x == "fifo" else "短停车优先",
                                   disabled=disabled,
                                   help="FIFO 保留各策略差异（对比更明显）；短停车优先能减少等待但策略差异会被抹平")
        strategy_name = st.selectbox("策略", list(STRATEGY_LABELS.keys()),
                                     format_func=lambda x: STRATEGY_LABELS[x],
                                     disabled=disabled)

        # random 策略重复次数单独控制：随机性强，需 100+ 次取平均才有说服力；
        # 其他策略仍用上方「仿真次数」滑杆（1~10），避免被迫一起跑 100+ 次。
        random_reps = 100
        if strategy_name in ("random", "compare_all"):
            random_reps = st.number_input(
                "random 策略重复次数（≥100）", 100, 1000, 100, step=10,
                disabled=disabled,
                help="random 随机性大，建议 100~200 次取平均；"
                     "该次数只作用于 random 策略，其余策略仍用上方「仿真次数」",
            )

    with st.expander("📖 算法说明（分配逻辑与拒绝规则）"):
        st.markdown(strategy_description(strategy_name))
        st.markdown("""
**等待与拒绝规则**

当停车场**所有车位均被占用**时，到达车辆不会立即被拒，而是**排队等待**；若等待超过下方「排队等待上限」仍无空闲车位，才判定为拒绝（计入「拒绝数」指标，等待时长计入「平均等待时间」）。
""")

    # 策略可调参数（按 PARAMS 声明动态渲染）
    if strategy_name != "compare_all" and StrategyRegistry.specs(strategy_name):
        st.markdown("#### 🎛️ 算法参数（可调）")
        last_params = st.session_state.get("last_params", {}).get(strategy_name, {})
        strat_params = render_strategy_params(strategy_name, disabled, initial=last_params)
    else:
        strat_params = {}

    # 环境参数（引擎 + 需求，可调）
    with st.expander("🌐 环境参数（车速/等待/需求，可调）"):
        if import_mode:
            st.caption("导入需求序列后，需求生成参数（仿真时长/停车时长/高峰占比/预估误差）不再生效，已变灰；"
                       "车速与排队等待上限仍生效。")
        env_params = render_env_params(
            disabled, disabled_keys=DEMAND_GEN_ENV_KEYS if import_mode else None)

    # 停车时长上下限校验：下限不应大于上限
    if env_params["duration_min"] > env_params["duration_max"]:
        st.warning("⚠️ 停车时长下限大于上限，已自动交换")
        env_params["duration_min"], env_params["duration_max"] = \
            env_params["duration_max"], env_params["duration_min"]

    return (layout, real_layout_mode, n_spots, tandem_ratio, n_vehicles, seed,
            n_runs, wait_policy, strategy_name, random_reps, strat_params, env_params)
