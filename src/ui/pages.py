from ui.common import *
from ui.common import _avg_metrics, _plot_radar

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

    # 需求数据源：自动生成（种子）或导入 JSON 文件（上次仿真导出的需求序列可复用）
    st.markdown("#### 📦 需求数据源")
    demand_source = st.radio(
        "车辆到达/离场需求来源",
        ["自动生成（随机种子）", "导入需求序列 JSON"],
        horizontal=True,
        help="导入后所有策略共用同一批车辆需求（保证对比公平），相同种子/相同序列可复现结果",
    )
    imported_vehicles = None
    imported_meta = None
    if demand_source.startswith("导入"):
        up = st.file_uploader("上传需求序列 JSON（.json）", type=["json"],
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
            # 从项目文件夹 data/demand_exports/ 直接选择（本地保存的需求序列）
            local_files = list_demand_files()
            if local_files:
                labels = [disp for _, disp in local_files]
                sel = st.selectbox(
                    "或从项目文件夹选择（data/demand_exports/）",
                    ["（不选择）"] + labels, key="local_demand_sel",
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
                # 本次会话之前已导入过（例如运行后回来），沿用缓存
                imported_vehicles = st.session_state.imported_vehicles
                imported_meta = st.session_state.get("imported_meta") or {}
                st.info(f"沿用本会话已导入的需求序列（{len(imported_vehicles)} 辆车）。"
                        f"重新上传文件可替换。")
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

    with st.expander("📖 算法说明（分配逻辑与拒绝规则）"):
        st.markdown(strategy_description(strategy_name))
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

            # 需求来源：导入序列（所有 run/策略复用同一批，保证公平）或按种子生成
            base_vehicles = list(imported_vehicles) if imported_vehicles else None
            demand_source_used = "imported" if base_vehicles is not None else "generated"
            sim_vehicles_candidate = None

            if strategy_name == "compare_all":
                all_m = []
                main_events_raw = None
                all_strategies = list(StrategyRegistry.all().items())
                total = len(all_strategies)
                prog = st.progress(0.0, text="准备运行全部策略对比...")
                for i, (nm, cls) in enumerate(all_strategies):
                    prog.progress((i + 1) / total,
                                  text=f"运行策略 {i + 1}/{total}：{cls.label}（{n_runs} 次取平均）")
                    seed_metrics = []
                    for r in range(n_runs):
                        s = seed + r
                        vehs = (list(base_vehicles) if base_vehicles is not None
                                else generate_demand(seed=s, **demand_kwargs))
                        m, ev, _ = run_single(net, spots, vehs, cls(), s, wait_policy, **eng_kwargs)
                        seed_metrics.append(m)
                        # 主方法事件日志（取第一个种子），供「车辆动态路径」页展示
                        if nm == "duration_greedy" and r == 0:
                            main_events_raw = [{"time": e.time, "type": e.event_type.value,
                                                "vehicle_id": e.vehicle_id or "", "spot_id": e.spot_id or "",
                                                "metadata": dict(e.metadata)} for e in ev]
                            sim_vehicles_candidate = list(vehs)
                    all_m.append(_avg_metrics(seed_metrics))
                prog.empty()
                st.session_state.sim_all_metrics = all_m
                st.session_state.sim_metrics = next((m for m in all_m if m.get("strategy") == "duration_greedy"), None)
                st.session_state.sim_events_raw = main_events_raw
            else:
                seed_metrics = []
                events_raw = None
                for r in range(n_runs):
                    s = seed + r
                    vehs = (list(base_vehicles) if base_vehicles is not None
                            else generate_demand(seed=s, **demand_kwargs))
                    # 每次新建策略实例（避免有状态策略跨 run 污染）
                    strategy = StrategyRegistry.create(strategy_name, **strat_params)
                    m, ev, _ = run_single(net, spots, vehs, strategy, s, wait_policy, **eng_kwargs)
                    seed_metrics.append(m)
                    if r == 0:
                        events_raw = [{"time": e.time, "type": e.event_type.value,
                                       "vehicle_id": e.vehicle_id or "", "spot_id": e.spot_id or "",
                                       "metadata": dict(e.metadata)} for e in ev]
                        sim_vehicles_candidate = list(vehs)
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

                # 持久化到 Supabase（登录用户跨会话保留调参历史）
                token = st.session_state.get("token")
                if token:
                    try:
                        auth_set_pref(token, "run_history", json.dumps(history))
                    except Exception:
                        pass

            st.session_state.sim_net = net
            st.session_state.sim_spots = spots
            st.session_state.sim_pe = pe
            st.session_state.sim_n_spots = n_spots
            st.session_state.sim_n_vehicles = (len(sim_vehicles_candidate)
                                               if sim_vehicles_candidate else n_vehicles)
            st.session_state.sim_seed = seed
            st.session_state.sim_n_runs = n_runs
            st.session_state.sim_strategy_name = strategy_name
            st.session_state.sim_layout = layout
            st.session_state.sim_strategy_params = strat_params
            st.session_state.sim_env_params = env_params
            st.session_state.sim_vehicles = sim_vehicles_candidate
            st.session_state.sim_demand_source = demand_source_used
            st.session_state.sim_demand_meta = (imported_meta or {}
                                                if demand_source_used == "imported"
                                                else {"seed": seed, "generator_params": demand_kwargs})

            # 计算理论最优（CP-SAT 离线全信息上界，最多约 10 秒）
            cpsat_rate = None
            with st.spinner("计算 CP-SAT 理论最优（最多约 10 秒）..."):
                try:
                    cps_vehs = (list(base_vehicles) if base_vehicles is not None
                                else generate_demand(seed=seed, **demand_kwargs))
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
        if not role["can_manage_data"]:
            st.info("仅管理员可进行数据备份")
        else:
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
        if not role["can_manage_data"]:
            st.info("仅管理员可导入布局")
        else:
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
    doc_path = Path(__file__).resolve().parents[2] / "docs" / "布局导入格式说明.md"
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

    # 按车辆序号分段（每段 20 辆），先选段再细选
    SEGMENT_SIZE = 20
    segment_labels = []
    segment_map = {}
    for i in range(0, len(all_vehs), SEGMENT_SIZE):
        chunk = all_vehs[i:i + SEGMENT_SIZE]
        label = f"{chunk[0]} ~ {chunk[-1]}"
        segment_labels.append(label)
        segment_map[label] = chunk

    if segment_labels:
        seg_sel = st.selectbox("① 选择车辆区间", segment_labels)
        filtered_vehs = segment_map[seg_sel]
    else:
        filtered_vehs = all_vehs

    # 若已选车辆不在当前段，则重置
    if st.session_state.get("selected_vehicle") and st.session_state.selected_vehicle not in filtered_vehs:
        st.session_state.selected_vehicle = None

    st.selectbox("② 选择车辆", [""] + filtered_vehs, key="selected_vehicle",
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
        demand_source = st.session_state.get("sim_demand_source", "generated")
        src_note = ("同一导入需求序列" if demand_source == "imported"
                    else f"{n_runs} 次不同随机种子的平均值（降低随机波动）")
        st.caption(f"基于 {src_note}")
        all_m = st.session_state.sim_all_metrics

        # 排序模式：字典序（原有，保留）/ 加权评分（新增）
        rank_mode = st.radio("排序模式", ["字典序优先级", "加权评分"],
                             horizontal=True, key="rank_mode")

        if rank_mode == "加权评分":
            st.markdown("#### 🎚️ 指标权重（总和应为 100，已自动归一化）")
            weights_by_label = {}
            default_weights = st.session_state.get("rank_weights", DEFAULT_WEIGHTS_BY_LABEL)
            wcols = st.columns(4)
            for i, name in enumerate(list(PRIORITY_METRICS.keys())):
                with wcols[i % 4]:
                    weights_by_label[name] = st.number_input(
                        name, 0, 100, int(default_weights.get(name, 10)), step=5,
                        key=f"weight_{name}",
                        help=f"{PRIORITY_METRICS[name][2]}（"
                             f"{'越大越好' if PRIORITY_METRICS[name][1] == 'max' else '越小越好'}）")
            st.session_state.rank_weights = weights_by_label
            total_w = sum(weights_by_label.values())
            if total_w != 100:
                st.warning(f"⚠️ 权重总和为 {total_w}（应为 100），将按比例归一化后计算排名")
            else:
                st.caption("权重总和 = 100 ✅")
            wdf, ranked = weighted_rank_df(all_m, weights_by_label)
            best = ranked[0]
            st.markdown(f'> 🏆 加权推荐: **{STRATEGY_LABELS.get(best["strategy"], best["strategy"])}**'
                        f' 综合得分 {best["weighted_score"]:.3f}（满分 1.0）')
            cpsat_rate = st.session_state.get("sim_cpsat_rate")
            if cpsat_rate is not None:
                gap = best["satisfaction_rate"] - cpsat_rate
                st.markdown(f'> 🎯 理论最优（CP-SAT 离线全信息）满足率 **{cpsat_rate:.1%}**，'
                            f'推荐策略距最优 {gap:.1%}')
            df = wdf
            styled = (df.style
                      .format({"综合得分": "{:.3f}", "满足率": "{:.1%}", "利用率": "{:.1%}",
                               "平均等待(s)": "{:.1f}", "移位距离(m)": "{:.1f}",
                               "行驶距离(m)": "{:.1f}", "耗时(s)": "{:.3f}"})
                      .apply(lambda row: ['background-color: #d4edda' if row.name == 0
                                          else '' for _ in row], axis=1))
            st.dataframe(styled, use_container_width=True, hide_index=True)
            st.download_button("📥 下载加权排名 CSV", wdf.to_csv(index=False).encode('utf-8'),
                               "parking_weighted_ranking.csv", "text/csv")
        else:
            # 按用户定义的优先级做字典序排序（原有逻辑，保留）
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
            df = pd.DataFrame(sorted_m)[["strategy", "satisfaction_rate", "spatial_utilization",
                                         "avg_wait_time_s", "shift_count", "shift_distance_m",
                                         "total_drive_distance_m", "rejected_count", "runtime_s"]]
            df.columns = ["策略", "满足率", "利用率", "平均等待(s)", "移位次数",
                          "移位距离(m)", "行驶距离(m)", "拒绝数", "耗时(s)"]
            st.markdown(f'> 🏆 推荐: **{STRATEGY_LABELS.get(best["strategy"], best["strategy"])}**'
                        f' 满足率 {best["satisfaction_rate"]:.1%}')
            cpsat_rate = st.session_state.get("sim_cpsat_rate")
            if cpsat_rate is not None:
                gap = best["satisfaction_rate"] - cpsat_rate
                st.markdown(f'> 🎯 理论最优（CP-SAT 离线全信息）满足率 **{cpsat_rate:.1%}**，'
                            f'最佳策略距最优 {gap:.1%}')
            styled = (df.style
                      .format({"满足率": "{:.1%}", "利用率": "{:.1%}", "平均等待(s)": "{:.1f}",
                               "移位距离(m)": "{:.1f}", "行驶距离(m)": "{:.1f}", "耗时(s)": "{:.3f}"})
                      .apply(lambda row: ['background-color: #d4edda' if row.name == 0
                                          else '' for _ in row], axis=1))
            st.dataframe(styled, use_container_width=True, hide_index=True)
            st.download_button("📥 下载 CSV", df.to_csv(index=False).encode('utf-8'),
                               "parking_comparison.csv", "text/csv")

        c1, c2 = st.columns(2)
        with c1: st.bar_chart(df.set_index("策略")["满足率"], height=200)
        with c2: st.bar_chart(df.set_index("策略")["移位次数"], height=200)
        st.markdown("#### 📡 多维指标雷达图（外圈=更好）")
        st.plotly_chart(_plot_radar(all_m), use_container_width=True)
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

    # ── 需求时序分布 + 车辆明细（反馈优化第二批）──
    st.markdown("---")
    st.markdown("### 🕒 需求时序分布与车辆明细")
    events_raw = st.session_state.get("sim_events_raw")
    demand_source = st.session_state.get("sim_demand_source", "generated")
    if events_raw:
        if demand_source == "imported":
            st.caption("事件日志来自导入的需求序列；「全部对比」模式下为当前主方法（时长感知贪心）的事件日志。")
        else:
            st.caption("事件日志来自最近一次仿真；「全部对比」模式下为当前主方法（时长感知贪心）的事件日志。")
        hist = build_demand_histogram(events_raw)
        if hist is not None:
            st.plotly_chart(hist, use_container_width=True)
        else:
            st.info("暂无到达/离场事件")
        rows = build_vehicle_detail_rows(events_raw)
        if rows:
            vdf = pd.DataFrame(rows)
            st.dataframe(vdf, use_container_width=True, hide_index=True)
            st.download_button("📥 下载车辆明细 CSV",
                               vdf.to_csv(index=False).encode('utf-8-sig'),
                               "parking_vehicle_details.csv", "text/csv")
        vehs = st.session_state.get("sim_vehicles")
        if vehs:
            meta = st.session_state.get("sim_demand_meta") or {}
            json_str = export_demand_json(
                vehs,
                seed=meta.get("seed"),
                source=demand_source,
                generator_params=meta.get("generator_params"),
                generated_at=meta.get("generated_at"),
            )
            default_name = f"demand_{demand_source}_{time.strftime('%Y%m%d_%H%M%S')}.json"
            download_name = f"parking_demand_{time.strftime('%Y%m%d_%H%M%S')}.json"
            cdl, csl = st.columns(2)
            with cdl:
                st.download_button("📥 浏览器下载",
                                   json_str.encode("utf-8"),
                                   download_name, "application/json")
                st.caption("每次下载文件名带时间戳，不会重名")
            with csl:
                dl_files = list_downloaded_demand_files()
                if dl_files:
                    labels = [disp for _, disp in dl_files]
                    move_sel = st.multiselect(
                        "选择要移动的文件", labels, default=[labels[0]],
                        key="move_dl_sel",
                        help="勾选要移动到 data/demand_exports/ 的文件（默认最新一个）")
                    del_sel = st.multiselect(
                        "选择要删除的文件", labels, default=[],
                        key="del_dl_sel",
                        help="勾选要从 Downloads 删除的文件（清理 (1)(2) 等重复文件）")
                    move_name = st.text_input(
                        "移动后命名（仅移动 1 个时生效）", "parking_demand.json",
                        key="move_name_input",
                        help="只勾选 1 个文件时，移动过去并改成这个名字；不带 .json 自动补")
                    cmv, cdel = st.columns(2)
                    with cmv:
                        if st.button("📥 移动选中", use_container_width=True,
                                     key="move_dl_btn"):
                            paths = [dl_files[labels.index(x)][0] for x in move_sel]
                            moved = move_downloaded_demand_files(
                                paths, new_name=move_name if len(paths) == 1 else None)
                            if moved:
                                st.success("已移动：" + "、".join(p.name for p in moved))
                            else:
                                st.info("未选择要移动的文件")
                    with cdel:
                        if st.button("🗑 删除选中", use_container_width=True,
                                     key="del_dl_btn"):
                            paths = [dl_files[labels.index(x)][0] for x in del_sel]
                            deleted = delete_downloaded_demand_files(paths)
                            if deleted:
                                st.success("已删除：" + "、".join(deleted))
                            else:
                                st.info("未选择要删除的文件")
                else:
                    st.info(f"Downloads 文件夹（{get_downloads_dir()}）里没有找到 "
                            f"parking_demand*.json，请先点「浏览器下载」。")
            with st.expander("💾 保存到项目文件夹（可改文件名与位置）", expanded=True):
                cdir, cfile = st.columns(2)
                with cdir:
                    save_dir = st.text_input(
                        "保存目录", str(DEMAND_EXPORT_DIR), key="save_dir_input",
                        help="绝对路径，或相对项目根目录的路径（默认 data/demand_exports/）")
                with cfile:
                    save_name = st.text_input(
                        "文件名", default_name, key="save_name_input",
                        help="不含 .json 后缀会自动补上；填完整路径则忽略左侧目录")
                if st.button("💾 保存到该位置", key="save_demand_manual"):
                    try:
                        name_p = Path(save_name)
                        if name_p.is_absolute():
                            target = name_p
                        else:
                            base = Path(save_dir)
                            if not base.is_absolute():
                                base = PROJECT_ROOT / base
                            target = base / save_name
                        saved_path = save_demand_to_path(
                            vehs, target,
                            seed=meta.get("seed"),
                            source=demand_source,
                            generator_params=meta.get("generator_params"),
                            generated_at=meta.get("generated_at"),
                        )
                        st.success(f"✅ 已保存：{saved_path}")
                    except OSError as exc:
                        st.error(f"❌ 保存失败：{exc}")
    else:
        st.info("暂无事件日志（请先运行仿真）")

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


def _detect_ui_compat():
    """检测前端 UI 依赖的 use_container_width 是否仍被 Streamlit 支持。

    项目有 27 处控件使用 use_container_width，Streamlit 已将其标记废弃（计划移除）。
    一旦被移除，这些控件会抛 TypeError 导致页面崩溃，此处运行时探测以提前预警。
    """
    import inspect
    import streamlit as _st
    try:
        if "use_container_width" in inspect.signature(_st.button).parameters:
            return {"removed": False,
                    "detail": f"use_container_width 可用（Streamlit {_st.__version__}，已标记废弃但尚未移除）"}
        return {"removed": True,
                "detail": f"use_container_width 已被 Streamlit {_st.__version__} 移除，界面控件将报错，需立即升级代码"}
    except Exception as e:
        return {"removed": None, "detail": f"无法检测（{e}）"}


def render_status_page(role):
    """页面: 系统状态与预警 —— 主动探测 Supabase 后端可用性"""
    st.subheader("🚨 系统状态与预警")
    if not role["can_debug"]:
        st.info("仅管理员和操作员可查看系统状态")
        return
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

    # ── 前端 UI 兼容性检测（use_container_width 废弃预警）──
    st.markdown("---")
    ui = _detect_ui_compat()
    if ui["removed"]:
        st.error(f"🚫 **前端兼容性风险**：{ui['detail']}")
    elif ui["removed"] is None:
        st.warning(f"⚠️ **前端兼容性未知**：{ui['detail']}")
    else:
        st.caption(f"✅ **前端 UI 兼容性**：{ui['detail']}")

    st.markdown("""
**说明**
- 本页主动探测 `auth.py` 中配置的 Supabase 后端（URL 与 anon key）是否可用。
- 后端在线但 API key 失效 → key 已过期或权限变更，需到 Supabase 控制台检查。
- 无法连接 → 项目可能已暂停（免费项目 7 天无活动会自动暂停）或已过期。
""")


def render_algo_import_page(role):
    """页面: 新算法接入 —— 上传算法描述文件，供 AI 后台接入"""
    st.subheader("🧩 新算法接入")
    if not role["can_import_algo"]:
        st.info("仅管理员可接入新算法")
        return
    st.markdown("""
上传你的算法描述文件（**文字说明 / 代码示例 / 伪代码**，支持 `.md` / `.txt` / `.py` / `.json`），
文件会保存到仓库 `pending_algorithms/` 目录。

> 上传后，请回到 **Deep Code 对话** 中说一句「接入算法」，AI 会读取文件、编写代码、复检并接入，
> 最后跑仿真比较，选出最优算法。
""")

    pending_dir = Path(__file__).resolve().parents[2] / "pending_algorithms"
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


def render_feedback_page(role):
    """页面: 用户反馈 —— 意见箱 + 仿真结果反馈"""
    st.subheader("💬 反馈")
    is_admin = role.get("can_manage_users", False)

    with st.expander("📝 提交反馈", expanded=True):
        _render_submit_feedback()

    with st.expander("📋 我的反馈", expanded=False):
        _render_my_feedbacks()

    if is_admin:
        st.divider()
        st.markdown("### 🗂 全部反馈（管理员）")
        _render_admin_feedbacks()


def _render_submit_feedback():
    """提交反馈表单（所有登录用户）"""
    category = st.radio("反馈类型", ["general", "simulation"],
                        format_func=lambda x: "通用意见" if x == "general" else "仿真结果反馈",
                        horizontal=True)
    title = st.text_input("标题", placeholder="一句话概括你的反馈")
    content = st.text_area("内容", placeholder="详细描述你的意见 / 问题 / 建议...")

    related_run = None
    if category == "simulation":
        if st.session_state.get("sim_has_run"):
            sn = st.session_state.get("sim_strategy_name", "")
            strat_params = st.session_state.get("sim_strategy_params", {})
            env_params = st.session_state.get("sim_env_params", {})
            st.caption(f"将关联最近一次仿真：策略「{STRATEGY_LABELS.get(sn, sn)}」")
            related_run = json.dumps({"strategy": sn, "params": strat_params, "env": env_params},
                                     ensure_ascii=False)
        else:
            st.info("当前尚未运行仿真，反馈将以通用形式提交")
            category = "general"

    if st.session_state.get("fb_submitted"):
        st.success("✅ 反馈已提交！")
        st.session_state.fb_submitted = False

    if st.button("提交反馈", type="primary"):
        if not title.strip() or not content.strip():
            st.error("请填写标题和内容")
        else:
            res = auth_submit_feedback(st.session_state.token, category, title.strip(),
                                       content.strip(), related_run)
            if res.get("success"):
                st.session_state.fb_submitted = True
                st.rerun()
            else:
                st.error(res.get("error", "提交失败"))


def _render_my_feedbacks():
    """展示当前用户自己提交的反馈及管理员回复"""
    items = auth_list_my_feedbacks(st.session_state.token)
    if not items:
        st.caption("暂无反馈记录")
        return
    for f in items:
        cat = "仿真" if f.get("category") == "simulation" else "通用"
        status = f.get("status", "pending")
        icon = "✅" if status == "resolved" else "⏳"
        st.markdown(f"**{f.get('title', '')}**  `[{cat}]` {icon} `{status}`")
        st.caption(f"提交时间：{f.get('created_at', '')}")
        st.write(f.get("content", ""))
        if f.get("reply"):
            st.info(f"💬 管理员回复：{f['reply']}")
        st.divider()


def _feedback_to_csv(items):
    """把反馈列表转为 UTF-8 BOM 的 CSV 字节（Excel 可直接打开中文）"""
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["标题", "类型", "提交人", "角色", "状态", "内容", "回复", "时间"])
    for f in items:
        w.writerow([f.get("title", ""), f.get("category", ""), f.get("username", ""),
                    f.get("role", ""), f.get("status", ""), f.get("content", ""),
                    f.get("reply", ""), f.get("created_at", "")])
    return buf.getvalue().encode("utf-8-sig")


def _render_admin_feedbacks():
    """管理员查看全部反馈、筛选、标记状态、回复、删除、导出"""
    items = auth_list_feedbacks(st.session_state.token)
    if not items:
        st.caption("暂无反馈")
        return

    # 筛选 + 导出
    c_f1, c_f2, c_f3 = st.columns([1, 1, 1.4])
    with c_f1:
        status_filter = st.selectbox("状态筛选", ["全部", "待处理", "已处理"], key="fb_status_filter")
    with c_f2:
        cat_filter = st.selectbox("类型筛选", ["全部", "通用", "仿真"], key="fb_cat_filter")
    with c_f3:
        st.download_button("📥 导出反馈 CSV", _feedback_to_csv(items),
                           "feedback.csv", "text/csv", use_container_width=True)

    status_map = {"待处理": "pending", "已处理": "resolved"}
    cat_map = {"通用": "general", "仿真": "simulation"}
    filtered = [f for f in items
                if (status_filter == "全部" or f.get("status") == status_map[status_filter])
                and (cat_filter == "全部" or f.get("category") == cat_map[cat_filter])]

    if not filtered:
        st.caption("无符合条件的反馈")
        return

    # 分页（每页 10 条）
    PAGE_SIZE = 10
    total_pages = max(1, (len(filtered) + PAGE_SIZE - 1) // PAGE_SIZE)
    if "fb_page" not in st.session_state:
        st.session_state.fb_page = 0
    if st.session_state.fb_page >= total_pages:
        st.session_state.fb_page = 0
    start = st.session_state.fb_page * PAGE_SIZE
    page_items = filtered[start:start + PAGE_SIZE]

    # 分页控件
    c_pg1, c_pg2, c_pg3 = st.columns([1, 2, 1])
    with c_pg1:
        if st.button("← 上一页", disabled=st.session_state.fb_page == 0, key="fb_prev"):
            st.session_state.fb_page -= 1
            st.rerun()
    with c_pg2:
        st.caption(f"第 {st.session_state.fb_page + 1} / {total_pages} 页，共 {len(filtered)} 条")
    with c_pg3:
        if st.button("下一页 →", disabled=st.session_state.fb_page >= total_pages - 1, key="fb_next"):
            st.session_state.fb_page += 1
            st.rerun()

    for f in page_items:
        fid = str(f.get("id", ""))
        cat = "仿真" if f.get("category") == "simulation" else "通用"
        status = f.get("status", "pending")
        st.markdown(f"**{f.get('title', '')}**  `[{cat}]` — {f.get('username', '')}({f.get('role', '')})")
        st.caption(f"时间：{f.get('created_at', '')} | 状态：{status}")
        if f.get("related_run"):
            with st.expander("关联仿真信息"):
                st.code(f.get("related_run"))
        st.write(f.get("content", ""))
        if f.get("reply"):
            st.info(f"💬 已回复：{f['reply']}")

        c1, c2, c3 = st.columns([1, 1, 3])
        with c1:
            if status == "pending":
                if st.button("标记已处理", key=f"fb_done_{fid}"):
                    auth_update_feedback_status(st.session_state.token, fid, "resolved")
                    st.rerun()
            else:
                if st.button("标记未处理", key=f"fb_undo_{fid}"):
                    auth_update_feedback_status(st.session_state.token, fid, "pending")
                    st.rerun()
        with c2:
            if st.button("🗑 删除", key=f"fb_del_{fid}"):
                auth_delete_feedback(st.session_state.token, fid)
                st.rerun()
        with c3:
            reply = st.text_area("回复", key=f"fb_reply_{fid}", placeholder="输入回复...")
            if st.button("提交回复", key=f"fb_reply_btn_{fid}"):
                if reply.strip():
                    auth_reply_feedback(st.session_state.token, fid, reply.strip())
                    st.rerun()
        st.divider()


