import base64
import math
from datetime import datetime
from ui.common import *
from ui.common import (_avg_metrics, _plot_radar, _sync_custom_layouts_to_globals,
                      _json_safe, vehicles_from_dicts,
                      persist_custom_layouts, restore_custom_layouts,
                      ensure_custom_layouts_loaded)


def _worker_bat(kind: str) -> str:
    """生成本机 worker 启动脚本（公网网页下载后放到项目根目录双击运行）。"""
    if kind == "install_autostart":
        return (
            "@echo off\r\n"
            "chcp 65001 >nul\r\n"
            "title 停车场 App 本机计算 worker（开机自启安装）\r\n"
            "cd /d %~dp0\r\n"
            "echo 正在注册 Windows 登录自启任务 ParkingOptLocalWorker ...\r\n"
            "schtasks /Create /F /TN \"ParkingOptLocalWorker\" /SC ONLOGON /RL LIMITED "
            "/TR \"cmd /c cd /d %~dp0 && py local_worker.py --poll 1\"\r\n"
            "if errorlevel 1 (echo 安装失败，请右键以管理员身份运行本脚本 & pause & exit /b 1)\r\n"
            "echo 安装成功，立即启动一次 worker ...\r\n"
            "schtasks /Run /TN \"ParkingOptLocalWorker\"\r\n"
            "echo 完成。以后每次登录 Windows 都会自动在后台运行 worker，无需再手动打开。\r\n"
            "pause\r\n"
        )
    return (
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        "title 停车场 App 本机计算 worker\r\n"
        "cd /d %~dp0\r\n"
        "echo 正在启动本机计算 worker（保持本窗口开启，用完可关闭）...\r\n"
        "py local_worker.py --poll 1\r\n"
        "pause\r\n"
    )


# 操作员本地计算包（zip）内嵌文件内容：精简依赖 + 双击启动脚本
WORKER_REQUIREMENTS_TXT = (
    "# 停车场 App 本机计算 worker 精简依赖（无需 Streamlit/Pandas/Plotly）\n"
    "supabase>=2.0.0\n"
    "httpx>=0.27.0\n"
    "networkx>=3.0\n"
    "simpy>=4.0\n"
    "ortools>=9.7\n"
)


def _worker_operator_bat() -> str:
    """操作员包内的启动脚本：检测 Python → 首次安装精简依赖 → 启动 worker。

    依赖安装优先走清华 PyPI 镜像（国内直连，无需 VPN，比官方源更稳），
    失败后回退官方源（适合有稳定外网/代理的环境）。
    """
    return (
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        "title 停车场 App 本机计算 worker（操作员）\r\n"
        "cd /d %~dp0\r\n"
        "where py >nul 2>nul\r\n"
        "if errorlevel 1 (\r\n"
        "  echo [错误] 未检测到 Python。请先到 https://www.python.org/downloads/ 安装，\r\n"
        "  echo        安装时务必勾选 \"Add python.exe to PATH\"。\r\n"
        "  pause\r\n"
        "  exit /b 1\r\n"
        ")\r\n"
        "if not exist \".deps_installed\" (\r\n"
        "  echo 首次运行：正在安装精简依赖（supabase/networkx/simpy/ortools）...\r\n"
        "  py --version\r\n"
        "  py -c \"import struct; print('Python 位数：64 位' if struct.calcsize('P')==8 else 'Python 位数：32 位（ortools 不支持 32 位，请到 python.org 重装 64 位 Python）')\"\r\n"
        "  echo 优先使用清华 PyPI 镜像（国内直连更快，不需要 VPN）...\r\n"
        "  py -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout 60 --retries 5\r\n"
        "  py -m pip install -r requirements_worker.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout 60 --retries 5\r\n"
        "  if errorlevel 1 (\r\n"
        "    echo [提示] 镜像源失败，改用官方源重试（需要稳定外网；若开 VPN，请确认 VPN 为全局/TUN 模式，pip 不走浏览器代理）...\r\n"
        "    py -m pip install -r requirements_worker.txt --timeout 60 --retries 5\r\n"
        "    if errorlevel 1 (\r\n"
        "      echo [错误] 依赖安装失败。常见原因：① 32 位 Python（上方会提示，请重装 64 位）；② 网络问题，请换网络后重试；③ 公司网络限制，请用手机热点试试。\r\n"
        "      echo 请把本窗口从「Python 位数」开始的全部内容截图/复制发管理员。\r\n"
        "      pause\r\n"
        "      exit /b 1\r\n"
        "    )\r\n"
        "  )\r\n"
        "  echo ok> .deps_installed\r\n"
        ")\r\n"
        "echo 正在启动本机计算 worker（保持本窗口开启，用完可关闭）...\r\n"
        "py local_worker.py --poll 1\r\n"
        "pause\r\n"
    )


def _worker_package_bytes(supabase_url: str = "", supabase_anon_key: str = "") -> bytes:
    """生成「操作员本地计算包」zip：worker 代码 + 核心算法包 + 精简依赖 + 启动脚本 + 配置。

    supabase_url / supabase_anon_key 缺省时从 auth 模块（st.secrets/环境变量）读取。
    """
    import io
    import zipfile
    import auth as auth_mod

    sb_url = supabase_url or auth_mod.SUPABASE_URL
    sb_key = supabase_anon_key or auth_mod.SUPABASE_ANON_KEY
    if not sb_url or not sb_key:
        raise RuntimeError("Supabase 未配置，无法生成操作员本地计算包")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("local_worker.py",
                    (PROJECT_ROOT / "local_worker.py").read_text(encoding="utf-8"))
        zf.writestr("src/local_compute.py",
                    (PROJECT_ROOT / "src" / "local_compute.py").read_text(encoding="utf-8"))
        pkg = PROJECT_ROOT / "src" / "parking_opt"
        for p in sorted(pkg.rglob("*.py")):
            arc = str(p.relative_to(PROJECT_ROOT)).replace("\\", "/")
            zf.writestr(arc, p.read_text(encoding="utf-8"))
        zf.writestr("requirements_worker.txt", WORKER_REQUIREMENTS_TXT)
        zf.writestr("start_local_worker.bat", _worker_operator_bat())
        zf.writestr("worker_config.toml",
                    f'SUPABASE_URL = "{sb_url}"\nSUPABASE_ANON_KEY = "{sb_key}"\n')
    return buf.getvalue()


# 操作员 zip 包版本号：包内容（启动脚本/依赖清单）变更时 +1，避免 st.cache_data 命中旧包
_WORKER_PACKAGE_VERSION = "3"


@st.cache_data(show_spinner=False, ttl=3600)
def _cached_worker_package_bytes(sb_url: str, sb_key: str, pkg_version: str) -> bytes:
    """缓存操作员 zip 字节（同一小时内不重复读取/压缩 28 个核心文件）。"""
    return _worker_package_bytes(sb_url, sb_key)


def _worker_package_data_url() -> str:
    """操作员 zip 的 data URL：浏览器本地直接下载，不依赖 WebSocket 服务器连接。

    修复公网 app 报错「Error: not connected to a server!」：
    st.download_button 传 bytes 时前端点击要向服务器要下载地址，WebSocket
    一断就报该错；换成 data URL 后点击由浏览器直接处理。
    """
    import auth as auth_mod
    data = _cached_worker_package_bytes(
        auth_mod.SUPABASE_URL or "", auth_mod.SUPABASE_ANON_KEY or "",
        _WORKER_PACKAGE_VERSION)
    return "data:application/zip;base64," + base64.b64encode(data).decode("ascii")


def _resolve_delete_task_id(session_task_id, latest_any_res):
    """解析「删除该任务」按钮要删的任务 ID。

    优先用本会话下发的 task_id；session 丢失（刷新/重开浏览器）时，
    从 get_latest_compute_task_any 的结果里取最近一条任务（任意状态）。
    返回 (task_id, task_status, source)；无任务可删时 (None, None, None)。
    """
    if session_task_id:
        return session_task_id, None, "本会话任务"
    task = (latest_any_res or {}).get("task")
    if isinstance(task, dict) and task.get("id"):
        return task.get("id"), task.get("status"), "最近一条任务（刷新后自动定位）"
    return None, None, None


def render_settings(role):
    """页面1: 仿真设置"""
    ensure_custom_layouts_loaded()
    st.subheader("⚙️ 仿真参数配置")
    disabled = not role["can_configure"]
    if disabled: st.caption("⚠️ 当前角色仅可查看，不可修改参数")

    # 需求数据源：自动生成（种子）/ 导入 JSON 文件 / 导入真实道闸流水 CSV（企业对接演示）
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
            # 示例文件下载（给停车场运营方按格式准备数据）
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
                # 从项目文件夹 data/demand_exports/ 直接选择（本地保存的需求序列）
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
                    # 本次会话之前已导入过（例如运行后回来），沿用缓存
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

    # MOSA 场景权重自动绑定提示：由车位数/车辆数/停车时长自动判定（共 3 种，控件已变灰）
    if strategy_name == "mosa":
        eff_n_vehicles = len(imported_vehicles) if import_mode and imported_vehicles else n_vehicles
        avg_duration = (env_params["duration_min"] + env_params["duration_max"]) / 2
        # 真实布局下车位数由导入的 JSON 定义（车位数滑杆不生效），场景判定必须取实际车位数
        if real_layout_mode:
            try:
                _, hint_spots = LAYOUT_BUILDERS[layout](n_spots, tandem_ratio)
                hint_n_spots = len(hint_spots)
            except Exception:
                hint_n_spots = n_spots
        else:
            hint_n_spots = n_spots
        # 有导入需求序列时按真实车辆精确判定（与运行时 _resolve_scene 同规则）；否则用滑杆参数预估
        if import_mode and imported_vehicles:
            scene = resolve_mosa_scene(hint_n_spots, imported_vehicles)
        else:
            scene = estimate_mosa_scene(hint_n_spots, eff_n_vehicles,
                                        env_params["sim_duration"], avg_duration)
        weights_txt = {"peak": "0.6 / 0.2 / 0.2",
                       "normal": "0.2 / 0.6 / 0.2",
                       "saturated": "0.2 / 0.2 / 0.6"}[scene]
        src_txt = "导入文件车辆数" if import_mode and imported_vehicles else "车辆数"
        st.info(f"🔒 MOSA 场景权重**自动绑定**：车位数 {hint_n_spots}、{src_txt} {eff_n_vehicles}、"
                f"平均停车时长约 {avg_duration / 60:.0f} 分钟 → 判定为"
                f"「{MOSA_SCENE_LABELS[scene]}」，权重（时间/距离/利用率）＝ {weights_txt}。"
                f"该参数不可手动调节（已变灰）。")

    # 算法排名设置（加权评分 / 字典序优先级），运行后指标分析页按此展示
    st.markdown("#### 🏆 算法排名设置")
    if "rank_mode" not in st.session_state:
        st.session_state.rank_mode = "加权评分"
    rank_mode = st.radio("排序模式", ["加权评分", "字典序优先级"],
                         horizontal=True, key="rank_mode", disabled=disabled)

    if rank_mode == "加权评分":
        st.caption("指标权重（总和应为 100，将自动归一化；指标先 min-max 归一化再加权求和）")
        weights_by_label = {}
        default_weights = st.session_state.get("rank_weights", DEFAULT_WEIGHTS_BY_LABEL)
        wcols = st.columns(4)
        for i, name in enumerate(list(PRIORITY_METRICS.keys())):
            with wcols[i % 4]:
                weights_by_label[name] = st.number_input(
                    name, 0, 100, int(default_weights.get(name, 10)), step=5,
                    key=f"rank_weight_{name}", disabled=disabled,
                    help=f"{PRIORITY_METRICS[name][2]}（"
                         f"{'越大越好' if PRIORITY_METRICS[name][1] == 'max' else '越小越好'}）")
        total_w = sum(weights_by_label.values())
        if total_w != 100:
            st.warning(f"⚠️ 权重总和为 {total_w}（应为 100），计算排名时将按比例归一化")
        else:
            st.caption("权重总和 = 100 ✅")
        st.session_state.rank_weights = weights_by_label
    else:
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

    # 计算位置：云端 CPU / 本机 worker（云 UI + 本地算力）
    compute_mode = st.session_state.get("compute_mode", "cloud")
    mode_options = ["☁️ 云端计算", "💻 本地计算（本机 CPU）"]
    mode_sel = st.radio("计算位置", mode_options, horizontal=True,
                        index=0 if compute_mode != "local" else 1,
                        key="compute_mode_sel",
                        help="本地计算：云端界面 + 本机 worker 计算，大参数不再受云端内存限制")
    new_mode = "local" if mode_sel == mode_options[1] else "cloud"
    if new_mode != compute_mode:
        persist_compute_mode(new_mode)
        st.rerun()
    compute_mode = new_mode
    st.session_state.compute_mode = compute_mode

    # 需求来源（导入序列所有 run/策略复用同一批，保证公平；否则按种子生成）
    base_vehicles = list(imported_vehicles) if imported_vehicles else None
    if base_vehicles is not None:
        demand_source_used = ("real_gate"
                              if (imported_meta or {}).get("source") == "real_gate"
                              else "imported")
    else:
        demand_source_used = "generated"

    def _apply_sim_state(result, ctx):
        """把仿真结果写入 session_state 并跳转指标分析页（本地计算/载入历史共用）。"""
        if not isinstance(result, dict) or not result:
            st.error("结果为空，无法载入")
            st.stop()
        if ctx.get("custom_layout"):
            st.session_state.setdefault("custom_layouts", {}).update(ctx["custom_layout"])
            _sync_custom_layouts_to_globals()
        st.session_state.sim_net = ctx["net"]
        st.session_state.sim_spots = ctx["spots"]
        st.session_state.sim_pe = ctx["pe"]
        st.session_state.sim_n_spots = int(ctx["n_spots"])
        st.session_state.sim_seed = int(ctx["seed"])
        st.session_state.sim_strategy_name = ctx["strategy_name"]
        st.session_state.sim_strategy_params = ctx["strat_params"]
        st.session_state.sim_env_params = ctx["env_params"]
        st.session_state.sim_layout = ctx["layout"]
        if ctx.get("layout_category") == "builtin":
            st.session_state.last_builtin_sim = {
                "layout": ctx["layout"], "net": ctx["net"], "spots": ctx["spots"]}
            st.session_state.sim_layout_category = "builtin"
        else:
            st.session_state.last_real_sim = {
                "layout": ctx["layout"], "net": ctx["net"], "spots": ctx["spots"]}
            st.session_state.sim_layout_category = "real"
        st.session_state.sim_metrics = result.get("metrics")
        st.session_state.sim_all_metrics = result.get("all_m")
        st.session_state.sim_timed_out_strategies = result.get("timed_out") or []
        st.session_state.sim_failed_strategies = result.get("failed") or []
        st.session_state.sim_cpsat_rate = result.get("cpsat_rate")
        evs = result.get("events_by_strategy") or {}
        vehs_raw = result.get("vehicles_by_strategy") or {}
        st.session_state.sim_events_by_strategy = evs
        st.session_state.sim_vehicles_by_strategy = {
            k: vehicles_from_dicts(v) for k, v in vehs_raw.items()}
        st.session_state.sim_events_raw = result.get("main_events")
        demand_source_used = ctx.get("demand_source") or "generated"
        st.session_state.sim_demand_source = demand_source_used
        if demand_source_used in ("imported", "real_gate"):
            st.session_state.sim_demand_meta = ctx.get("imported_meta") or {}
        else:
            st.session_state.sim_demand_meta = {"seed": ctx["seed"], "generator_params": {
                "total_vehicles": int(ctx["n_vehicles"]),
                "sim_duration": ctx["env_params"]["sim_duration"],
                "duration_min": ctx["env_params"]["duration_min"],
                "duration_max": ctx["env_params"]["duration_max"],
                "peak_ratio": ctx["env_params"]["peak_ratio"],
                "error_ratio": ctx["env_params"]["error_ratio"]}}
        strategy_name_used = ctx["strategy_name"]
        if strategy_name_used != "compare_all":
            st.session_state.sim_vehicles = (st.session_state.sim_vehicles_by_strategy
                                             .get(strategy_name_used) or [])
        else:
            st.session_state.sim_vehicles = (
                st.session_state.sim_vehicles_by_strategy.get("duration_greedy")
                or (next(iter(st.session_state.sim_vehicles_by_strategy.values()))
                    if st.session_state.sim_vehicles_by_strategy else []))
        st.session_state.sim_n_vehicles = len(st.session_state.sim_vehicles) or int(ctx["n_vehicles"])
        st.session_state.sim_n_runs = int(ctx["n_runs"])
        st.session_state.sim_random_reps = int(ctx["random_reps"])
        st.session_state.sim_has_run = True
        st.session_state.replay_time = 0.0
        st.session_state.replay_playing = False
        st.session_state.selected_vehicle = None
        st.session_state.page = "📊 指标分析"
        st.rerun()

    def _apply_local_result(result):
        """把本机 worker 返回的结果载入 session_state，等同云端跑完一次仿真。"""
        net, spots = LAYOUT_BUILDERS[layout](n_spots, tandem_ratio)
        pe = PathEngine(net)
        ctx = {
            "layout": layout,
            "layout_category": "builtin" if layout in BUILTIN_LAYOUT_KEYS else "real",
            "custom_layout": None,
            "n_spots": int(n_spots),
            "tandem_ratio": float(tandem_ratio),
            "net": net,
            "spots": spots,
            "pe": pe,
            "strategy_name": strategy_name,
            "strat_params": strat_params,
            "env_params": env_params,
            "wait_policy": wait_policy,
            "seed": int(seed),
            "n_runs": int(n_runs),
            "random_reps": int(random_reps),
            "base_vehicles": base_vehicles,
            "demand_source": demand_source_used,
            "imported_meta": imported_meta if demand_source_used in ("imported", "real_gate") else None,
            "n_vehicles": int(n_vehicles),
        }
        _apply_sim_state(result, ctx)

    def _load_latest_local_task():
        """载入该用户最近一次已完成的本地计算任务（session 丢失 task_id 后找回）。"""
        token = st.session_state.get("token")
        if not token:
            st.error("未登录，无法载入本地计算任务")
            st.stop()
        res = auth_get_latest_compute_task(token)
        if not (isinstance(res, dict) and res.get("success")):
            st.error(f"❌ 载入失败：{(res or {}).get('error', '未知错误')}\n\n"
                     "请确认 Supabase 已执行 migrations/10_latest_task_load.sql。")
            st.stop()
        task = res.get("task")
        if not isinstance(task, dict) or not task.get("result"):
            st.info("暂无已完成的本地计算任务。先在下方「▶️ 下发本地计算任务」跑一次，"
                    "完成后即可在这里一键载入。")
            return
        try:
            ctx = build_local_task_context(task.get("payload") or {})
        except Exception as e:
            st.error(f"❌ 任务参数解析失败：{type(e).__name__}: {e}")
            st.stop()
        _apply_sim_state(task.get("result") or {}, ctx)

    def _delete_local_task_with_confirm():
        """删除本地计算任务（下发错了叫停用），带二次确认。

        优先删本会话下发的 task_id；刷新/重开浏览器后 session 丢失 task_id 时，
        自动查询该用户最近一条任务（任意状态）来删，按钮不再因刷新而失效。
        """
        token = st.session_state.get("token")
        if not token:
            st.info("未登录，无法删除本地计算任务")
            return
        task_id = st.session_state.get("local_task_id")
        task_status = None
        if not task_id:
            res = auth_get_latest_compute_task_any(token)
            if isinstance(res, dict) and not res.get("success"):
                st.error(f"❌ 查询最近任务失败：{(res or {}).get('error', '未知错误')}")
                return
            task_id, task_status, task_source = _resolve_delete_task_id(None, res)
        else:
            task_source = "本会话任务"
        if not task_id:
            st.button("🗑 删除该任务", use_container_width=True, disabled=True,
                      help="暂无本地计算任务可删除：下发任务后（或刷新页面后）这里即可叫停")
            return
        status_cn = {"pending": "排队中", "running": "计算中",
                     "done": "已完成", "failed": "失败"}.get(task_status, task_status or "未知")
        confirm_key = f"confirm_delete_task_{task_id}"
        if st.session_state.get(confirm_key):
            st.warning(f"将删除{task_source}：`{str(task_id)[:8]}…`（状态：{status_cn}）。\n\n"
                       "若本机 worker 正在计算，回传时会自动丢弃结果。")
            c_yes, c_no = st.columns(2)
            with c_yes:
                if st.button("⚠️ 确认删除", use_container_width=True):
                    res = auth_delete_compute_task(token, task_id)
                    if isinstance(res, dict) and res.get("success"):
                        st.session_state.pop("local_task_id", None)
                        st.session_state.pop("local_task_notice", None)
                        st.session_state.pop(confirm_key, None)
                        st.success("🗑 任务已删除。若本机 worker 正在计算，回传时会自动丢弃结果。")
                        st.rerun()
                    else:
                        st.error(f"❌ 删除失败：{(res or {}).get('error', '未知错误')}")
            with c_no:
                if st.button("取消", use_container_width=True):
                    st.session_state.pop(confirm_key, None)
                    st.rerun()
        else:
            if st.button("🗑 删除该任务", use_container_width=True,
                         help="下发错了想叫停：优先删本会话任务；刷新丢失任务 ID 后自动定位最近一条任务删除"
                              "（排队/计算中/已完成均可删，worker 若正在计算回传时自动丢弃结果）"):
                st.session_state[confirm_key] = True
                st.rerun()

    def _check_local_task_once():
        token = st.session_state.get("token")
        task_id = st.session_state.get("local_task_id")
        if not token or not task_id:
            st.info("浏览器里没有本会话的任务 ID（可能刷新过页面）。\n\n"
                    "若刚下发过任务，本机 worker 会自动领取计算，完成后点「📂 载入最近一次结果」找回；\n\n"
                    "要叫停，点「🗑 删除该任务」。")
            return
        stt = auth_get_compute_task(token, task_id)
        if isinstance(stt, dict) and stt.get("success"):
            s = stt.get("status")
            if s == "done":
                st.success("✅ 本机计算完成，正在载入结果…")
                _apply_local_result(stt.get("result") or {})
            elif s == "failed":
                st.error(f"❌ 本机计算失败：{stt.get('error')}")
            elif s == "running":
                st.warning("⚙️ 任务仍在计算中。若本机 worker 已关闭或崩溃，可把任务重新排队，"
                           "重启 worker 后继续计算。")
                if st.button("♻️ 重新排队该任务（worker 已关闭时用）"):
                    rq = auth_requeue_compute_task(token, task_id)
                    if isinstance(rq, dict) and rq.get("success"):
                        st.success("✅ 已重新排队。请启动本机 worker（双击 start_local_worker.bat），"
                                   "稍后再点「🔄 检查本地计算结果」。")
                    else:
                        st.error(f"❌ 重新排队失败：{(rq or {}).get('error', '未知错误')}")
            else:
                st.info(f"任务状态：{s}。请确认本机 `py local_worker.py` 正在运行。")
        else:
            st.info("暂无任务状态。请先运行 `py local_worker.py`，再下发任务。")

    def _submit_local_task_and_wait():
        token = st.session_state.get("token")
        if not token:
            st.error("未登录，无法下发本地计算任务")
            st.stop()
        if layout in BUILTIN_LAYOUT_KEYS:
            layout_payload = {"source": "builtin", "builtin_key": layout,
                              "n_spots": int(n_spots), "tandem_ratio": float(tandem_ratio)}
        else:
            linfo = (st.session_state.get("custom_layouts") or {}).get(layout) or {}
            layout_payload = {"source": "custom", "custom_data": linfo.get("data")}
        if base_vehicles is not None:
            demand_payload = {"source": demand_source_used,
                              "json_str": export_demand_json(base_vehicles, source=demand_source_used)}
        else:
            demand_payload = {"source": "generated", "generator": {
                "total_vehicles": int(n_vehicles),
                "sim_duration": env_params["sim_duration"],
                "duration_min": env_params["duration_min"],
                "duration_max": env_params["duration_max"],
                "peak_ratio": env_params["peak_ratio"],
                "error_ratio": env_params["error_ratio"]}}
        payload = {
            "layout": layout_payload,
            "demand": demand_payload,
            "strategy": {"name": strategy_name, "params": strat_params},
            "engine": {"wait_policy": wait_policy,
                       "car_speed": env_params["car_speed"],
                       "max_wait_time": env_params["max_wait_time"],
                       "seed": int(seed), "n_runs": int(n_runs),
                       "random_reps": int(random_reps),
                       "budget": float(STRATEGY_TIME_BUDGET)},
        }
        res = auth_create_compute_task(token, _json_safe(payload))
        if not (isinstance(res, dict) and res.get("success")):
            st.error(f"❌ 下发本地计算任务失败：{(res or {}).get('error', '未知错误')}\n\n"
                     "请确认：① Supabase 已执行 migrations/07_compute_tasks.sql；"
                     "② 本机 worker 正在运行（项目根目录双击 `start_local_worker.bat`，"
                     "或命令行 `py local_worker.py`）。")
            st.stop()
        task_id = res["task_id"]
        st.session_state.local_task_id = task_id
        status_box = st.empty()
        for i in range(60):
            time.sleep(2)
            stt = auth_get_compute_task(token, task_id)
            if not (isinstance(stt, dict) and stt.get("success")):
                status_box.info(f"⏳ 任务已下发（{str(task_id)[:8]}…），等待本机 worker 领取…")
                continue
            s = stt.get("status")
            if s == "pending":
                status_box.info(f"⏳ 任务排队中，等待本机 worker 领取（已等 {(i + 1) * 2}s）…")
            elif s == "running":
                status_box.info(f"⚙️ 本机 worker 正在计算（已等 {(i + 1) * 2}s）…")
            elif s == "done":
                status_box.success("✅ 本机计算完成，正在载入结果…")
                _apply_local_result(stt.get("result") or {})
                return
            elif s == "failed":
                status_box.error(f"❌ 本机计算失败：{stt.get('error')}")
                st.stop()
        st.session_state.local_task_notice = (
            "⏳ 已等待 120 秒，任务仍在计算中。稍后点上方「🔄 检查本地计算结果」查看；"
            "若本机 worker 已关闭，请先双击 `start_local_worker.bat` 启动，"
            "再用「♻️ 重新排队该任务」恢复。\n\n"
            "**下发错了想叫停？** 刷新页面（F5）回到本页后，点「🗑 删除该任务」即可删除；"
            "worker 若正在计算，回传时会自动丢弃结果。")
        status_box.warning(st.session_state.local_task_notice)
        st.stop()

    if compute_mode == "local":
        st.info("💻 **本地计算模式**：云端界面 + 本机 CPU。\n\n"
                "**本机就是项目电脑（管理员）**：下载「📥 一键启动脚本」放到项目根目录双击运行；\n\n"
                "**操作员/同事自己的电脑**：直接下载「📦 操作员本地计算包（zip）」→ 解压到任意文件夹 → "
                "双击 `start_local_worker.bat`（首次自动装精简依赖，输入自己的账号密码）；\n\n"
                "然后点「▶️ 下发本地计算任务」，本机算完后结果自动载入。"
                "**下发错了？** 刷新页面后点「🗑 删除该任务」即可叫停。")
        c_dl1, c_dl2, c_dl3 = st.columns(3)
        with c_dl1:
            st.download_button(
                "📥 下载 worker 一键启动脚本",
                data=_worker_bat("run"),
                file_name="start_local_worker.bat",
                mime="application/octet-stream",
                use_container_width=True,
                help="保存到项目根目录（和 local_worker.py 同一个文件夹）后双击，即启动本机 worker")
        with c_dl2:
            st.download_button(
                "📥 下载『开机自启』安装脚本（装一次，以后免手动）",
                data=_worker_bat("install_autostart"),
                file_name="install_local_worker_autostart.bat",
                mime="application/octet-stream",
                use_container_width=True,
                help="保存到项目根目录双击一次：注册 Windows 登录自启，以后每次开机自动运行 worker，无需再手动打开")
        with c_dl3:
            try:
                st.link_button(
                    "📦 下载操作员本地计算包（zip）",
                    url=_worker_package_data_url(),
                    use_container_width=True,
                    help="给其他操作员/同事的电脑用：解压后双击 start_local_worker.bat，"
                         "首次运行自动装精简依赖并输入自己的账号密码，之后即可本地计算")
            except Exception as exc:
                st.button("📦 操作员包（暂不可用）", use_container_width=True,
                          disabled=True, help=f"生成失败：{exc}")
        c_refresh, c_load, c_delete = st.columns(3)
        with c_refresh:
            if st.button("🔄 检查本地计算结果", use_container_width=True,
                         help="按本会话下发的任务 ID 查询状态（任务跑完自动载入）"):
                _check_local_task_once()
        with c_load:
            if st.button("📂 载入最近一次结果", use_container_width=True,
                         help="从 Supabase 拉取该用户最近一次已完成的本地计算任务并载入；"
                              "刷新页面、重开浏览器或换电脑后也能找回结果"):
                _load_latest_local_task()
        with c_delete:
            _delete_local_task_with_confirm()
        if st.session_state.get("local_task_id"):
            st.caption(f"最近任务：{st.session_state.local_task_id}")
        else:
            st.caption("浏览器里没有本会话的任务 ID？点「📂 载入最近一次结果」找回已完成结果；"
                       "点「🗑 删除该任务」叫停最近一次任务（刷新后也能删）。")

    # 公网云端资源受限，大参数提前提示（本地 Windows 桌面不提示）
    if (not is_local_desktop() and compute_mode == "cloud"
            and (n_vehicles >= 500 or n_spots >= 200)):
        st.info("🌐 当前在**公网云端**运行：车辆/车位较多时容易内存不足或超时。\n"
                "可切换到上面的「💻 本地计算」，并在本机运行 `py local_worker.py`。")

    run_label = "▶️ 下发本地计算任务" if compute_mode == "local" else "▶️ 运行仿真"
    if st.button(run_label, type="primary", use_container_width=True,
                 disabled=not role["can_run_simulation"]):
        if compute_mode == "local":
            _submit_local_task_and_wait()
            st.stop()
        with st.spinner("仿真运行中..."):
            net, spots = LAYOUT_BUILDERS[layout](n_spots, tandem_ratio)
            pe = PathEngine(net)

            # 需求生成 / 引擎公共参数（多入口/多出口：把布局的口列表传给生成器，
            # 由随机种子独立分配；内置布局均为单入口且无出口，行为与旧版一致）
            demand_kwargs = dict(total_vehicles=n_vehicles,
                                 sim_duration=env_params["sim_duration"],
                                 duration_min=env_params["duration_min"],
                                 duration_max=env_params["duration_max"],
                                 peak_ratio=env_params["peak_ratio"],
                                 error_ratio=env_params["error_ratio"],
                                 entry_ids=pe.entry_ids,
                                 exit_ids=pe.exit_ids)
            eng_kwargs = dict(car_speed=env_params["car_speed"],
                              max_wait_time=env_params["max_wait_time"])
            sim_vehicles_candidate = None

            # random 策略用独立的重复次数（≥100），其余策略用「仿真次数」滑杆
            def _n_runs_for(name: str) -> int:
                return int(random_reps) if name == "random" else int(n_runs)

            if strategy_name == "compare_all":
                all_m = []
                timed_out_strategies = []
                failed_strategies = []
                main_events_raw = None
                events_by_strategy = {}
                vehicles_by_strategy = {}
                all_strategies = list(StrategyRegistry.all().items())
                total = len(all_strategies)
                prog = st.progress(0.0, text="准备运行全部策略对比...")
                for i, (nm, cls) in enumerate(all_strategies):
                    runs_for_this = _n_runs_for(nm)
                    prog.progress((i + 1) / total,
                                  text=f"运行策略 {i + 1}/{total}：{cls.label}（{runs_for_this} 次取平均，超过 {int(STRATEGY_TIME_BUDGET)} 秒仅标记）")
                    seed_metrics = []
                    strategy_timed_out = False
                    strategy_error = None
                    for r in range(runs_for_this):
                        s = seed + r
                        vehs = (list(base_vehicles) if base_vehicles is not None
                                else generate_demand(seed=s, **demand_kwargs))
                        t_seed = time.time()
                        try:
                            m, ev, _ = run_single(net, spots, vehs, cls(), s, wait_policy, **eng_kwargs)
                        except Exception as e:
                            # 单个策略崩溃不拖垮整个对比（公网云端大参数易 OOM）
                            strategy_error = f"{type(e).__name__}: {e}"
                            break
                        # 60 秒仅作标记：超时种子结果仍保留、全部展示，可在指标页选择隐藏
                        if time.time() - t_seed > STRATEGY_TIME_BUDGET:
                            strategy_timed_out = True
                        seed_metrics.append(m)
                        # 每个策略都保留第一个种子的事件日志，供指标页「需求时序/车辆明细」切换查看；
                        # 主方法（时长感知贪心）的事件日志额外供「车辆动态路径」页展示
                        if r == 0:
                            ev_raw = [{"time": e.time, "type": e.event_type.value,
                                       "vehicle_id": e.vehicle_id or "", "spot_id": e.spot_id or "",
                                       "metadata": dict(e.metadata)} for e in ev]
                            events_by_strategy[nm] = ev_raw
                            vehicles_by_strategy[nm] = list(vehs)
                            if nm == "duration_greedy":
                                main_events_raw = ev_raw
                                sim_vehicles_candidate = list(vehs)
                    if strategy_error:
                        failed_strategies.append((nm, strategy_error))
                    if strategy_timed_out:
                        timed_out_strategies.append(nm)
                    # 有已完成种子就取平均参与对比；全部种子失败则该策略无数据
                    if seed_metrics:
                        all_m.append(_avg_metrics(seed_metrics))
                prog.empty()
                st.session_state.sim_all_metrics = all_m
                st.session_state.sim_timed_out_strategies = timed_out_strategies
                st.session_state.sim_failed_strategies = failed_strategies
                st.session_state.sim_metrics = next((m for m in all_m if m.get("strategy") == "duration_greedy"), None)
                # 主方法若首种子超时没有事件日志，回退到第一个成功策略的事件
                # （动态路径页依赖 sim_events_raw，不能为 None）
                if main_events_raw is None and events_by_strategy:
                    first_nm = next(iter(events_by_strategy))
                    main_events_raw = events_by_strategy[first_nm]
                    sim_vehicles_candidate = vehicles_by_strategy.get(first_nm, sim_vehicles_candidate)
                st.session_state.sim_events_by_strategy = events_by_strategy
                st.session_state.sim_vehicles_by_strategy = vehicles_by_strategy
                st.session_state.sim_events_raw = main_events_raw
            else:
                seed_metrics = []
                events_raw = None
                strategy_timed_out = False
                for r in range(_n_runs_for(strategy_name)):
                    s = seed + r
                    vehs = (list(base_vehicles) if base_vehicles is not None
                            else generate_demand(seed=s, **demand_kwargs))
                    # 每次新建策略实例（避免有状态策略跨 run 污染）
                    strategy = StrategyRegistry.create(strategy_name, **strat_params)
                    t_seed = time.time()
                    try:
                        m, ev, _ = run_single(net, spots, vehs, strategy, s, wait_policy, **eng_kwargs)
                    except Exception as e:
                        st.error(f"❌ 仿真运行失败：{type(e).__name__}: {e}")
                        if not is_local_desktop():
                            st.info("当前运行在公网云端（资源受限），车辆/车位较多时容易内存不足。\n"
                                    "建议大参数改在本地运行：`py -m streamlit run app.py`（本机计算，云端只存数据）。")
                        st.stop()
                    # 60 秒仅作标记：超时种子结果仍保留、全部展示
                    if time.time() - t_seed > STRATEGY_TIME_BUDGET:
                        strategy_timed_out = True
                    seed_metrics.append(m)
                    if r == 0:
                        events_raw = [{"time": e.time, "type": e.event_type.value,
                                       "vehicle_id": e.vehicle_id or "", "spot_id": e.spot_id or "",
                                       "metadata": dict(e.metadata)} for e in ev]
                        sim_vehicles_candidate = list(vehs)
                avg_m = _avg_metrics(seed_metrics)
                st.session_state.sim_metrics = avg_m
                st.session_state.sim_timed_out_strategies = [strategy_name] if strategy_timed_out else []
                st.session_state.sim_failed_strategies = []
                st.session_state.sim_events_raw = events_raw
                st.session_state.sim_all_metrics = None
                st.session_state.sim_events_by_strategy = {strategy_name: events_raw}
                st.session_state.sim_vehicles_by_strategy = {strategy_name: sim_vehicles_candidate}

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

                # 持久化最近一次参数（reboot 后自动回填该策略控件）
                persist_last_params(strategy_name, strat_params)

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
            st.session_state.sim_n_runs = (_n_runs_for(strategy_name)
                                           if strategy_name != "compare_all" else n_runs)
            st.session_state.sim_random_reps = int(random_reps)
            st.session_state.sim_strategy_name = strategy_name
            st.session_state.sim_layout = layout
            # 记录最近一次仿真使用的内置/真实布局（布局图页按视图模式回显）
            if layout in BUILTIN_LAYOUT_KEYS:
                st.session_state.last_builtin_sim = {"layout": layout, "net": net, "spots": spots}
                st.session_state.sim_layout_category = "builtin"
            else:
                st.session_state.last_real_sim = {"layout": layout, "net": net, "spots": spots}
                st.session_state.sim_layout_category = "real"
            st.session_state.sim_strategy_params = strat_params
            st.session_state.sim_env_params = env_params
            st.session_state.sim_vehicles = sim_vehicles_candidate
            st.session_state.sim_demand_source = demand_source_used
            st.session_state.sim_demand_meta = (imported_meta or {}
                                                if demand_source_used in ("imported", "real_gate")
                                                else {"seed": seed, "generator_params": demand_kwargs})

            # 持久化运行记录到 Supabase sim_runs（跨会话/跨用户可查，支持导出与对比）
            try:
                if strategy_name == "compare_all":
                    persist_sim_run("compare_all", strat_params, env_params,
                                    st.session_state.sim_all_metrics,
                                    layout, demand_source_used)
                else:
                    persist_sim_run(strategy_name, strat_params, env_params,
                                    st.session_state.sim_metrics,
                                    layout, demand_source_used)
            except Exception:
                pass

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
        if not role["can_configure"]:
            st.info("仅管理员/操作员可查看布局导入说明")
        else:
            with st.expander("📖 布局导入格式说明", expanded=False):
                st.markdown(_load_layout_doc())
                st.download_button("📥 下载示例布局 JSON",
                                   json.dumps(EXAMPLE_LAYOUT, indent=2, ensure_ascii=False),
                                   "example_layout.json", "application/json")
            if not role["can_manage_data"]:
                st.info("📤 上传布局仅管理员可操作")
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
    """上传自定义停车场布局（仅管理员调用；说明文档在 tab3 公共区展示）"""
    ensure_custom_layouts_loaded()
    if st.session_state.get("layout_restore_error"):
        st.warning(f"⚠️ 上次从云端恢复布局失败：{st.session_state.layout_restore_error}")
        if st.button("🔄 重试加载云端布局", key="retry_layout_restore"):
            st.session_state.pop("layout_restore_error", None)
            st.session_state.pop("layout_restore_retry_at", None)
            st.session_state.pop("custom_layouts", None)
            restore_custom_layouts()
            st.rerun()
    if "custom_layouts" not in st.session_state:
        st.session_state.custom_layouts = {}

    uploaded = st.file_uploader("📤 上传布局 JSON", type=["json"], key="import_layout")
    if uploaded is not None:
        try:
            data = json.loads(uploaded.read().decode("utf-8"))
            if "name" not in data or "nodes" not in data or "edges" not in data:
                st.error("JSON 格式不正确，需包含 name/nodes/edges 字段")
                st.stop()
            # 校验
            node_ids = {nd["id"] for nd in data["nodes"]}
            entry_ids = [nd["id"] for nd in data["nodes"] if nd.get("type") == "entry"]
            if not entry_ids:
                st.error("节点中必须至少包含一个 type='entry' 的入口节点")
                st.stop()
            for ed in data["edges"]:
                if ed["from"] not in node_ids or ed["to"] not in node_ids:
                    st.error(f"边 {ed['from']}→{ed['to']} 引用了不存在的节点")
                    st.stop()
            # 测试构建 + 连通性校验（每个车位必须从入口可达且能返回入口）
            net, spots = build_layout_from_json(data)
            pe_check = PathEngine(net)
            bad_in = [s.spot_id for s in spots
                      if not math.isfinite(pe_check.distance_to_spot(s.node_id))]
            bad_out = [s.spot_id for s in spots
                       if not math.isfinite(pe_check.shortest_distance(s.node_id, pe_check.entry_id))]
            if bad_in or bad_out:
                problems = list(dict.fromkeys(bad_in + bad_out))
                st.error("布局校验失败：以下车位与入口不连通（请检查 edges 是否双向完整、有无遗漏）："
                         + "、".join(problems[:12]) + ("…" if len(problems) > 12 else ""))
                st.stop()
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
                ok, err = persist_custom_layouts()
                if ok:
                    st.success(f"✅ `{name}` 已添加并保存！在仿真设置中可选")
                else:
                    st.warning(f"⚠️ 布局已在本会话生效，但云端保存失败：{err}"
                               f"（重新登录/重启后可能丢失）")
                # 清除 uploader
                st.rerun()
        except json.JSONDecodeError:
            st.error("不是有效的 JSON 文件")
        except Exception as e:
            st.error(f"校验失败: {e}")

    # 已导入的布局列表
    if st.session_state.custom_layouts:
        st.divider()
        st.caption("**已导入的布局（管理）：**")
        for lid, linfo in st.session_state.custom_layouts.items():
            c1, c2 = st.columns([4, 1])
            c1.write(f"📐 **{linfo['name']}** ({len(linfo['spots'])}车位)")
            confirm_key = f"confirm_del_{lid}"
            if not st.session_state.get(confirm_key):
                if c2.button("🗑 删除", key=f"del_layout_{lid}",
                             help=f"删除布局「{linfo['name']}」", type="primary"):
                    st.session_state[confirm_key] = True
                    st.rerun()
            else:
                with c2:
                    st.warning(f"确认删除「{linfo['name']}」？")
                    cc1, cc2 = st.columns(2)
                    if cc1.button("✅ 确认", key=f"del_ok_{lid}", type="primary"):
                        st.session_state.custom_layouts.pop(lid, None)
                        LAYOUT_BUILDERS.pop(lid, None)
                        LAYOUTS.pop(lid, None)
                        st.session_state.pop(confirm_key, None)
                        ok, err = persist_custom_layouts()
                        if ok:
                            st.success(f"已删除布局「{linfo['name']}」")
                        else:
                            st.warning(f"⚠️ 已在本会话删除，但云端同步失败：{err}")
                        st.rerun()
                    if cc2.button("取消", key=f"del_cancel_{lid}"):
                        st.session_state.pop(confirm_key, None)
                        st.rerun()


def _build_custom(data):
    """lambda 包装：从预存 data 构建自定义布局"""
    net, spots = build_layout_from_json(data)
    return net, spots


def render_layout_page():
    """页面3: 停车场布局图 — 内置布局/真实布局分别回显最近一次仿真的布局"""
    ensure_custom_layouts_loaded()
    st.subheader("🅿️ 停车场布局图")
    if not st.session_state.get("sim_has_run"):
        st.info("👈 请先在 **仿真设置** 中运行仿真")
        return

    builtin_sim = st.session_state.get("last_builtin_sim")
    real_sim = st.session_state.get("last_real_sim")
    options = []
    if builtin_sim:
        options.append("内置布局")
    if real_sim:
        options.append("真实布局")
    if not options:
        st.info("暂无已仿真的布局（请先在仿真设置中运行）")
        return

    if "layout_view_mode" not in st.session_state or st.session_state.layout_view_mode not in options:
        st.session_state.layout_view_mode = (
            "真实布局"
            if st.session_state.get("sim_layout_category") == "real" and real_sim
            else "内置布局")
    mode = st.radio(
        "视图模式", options, horizontal=True, key="layout_view_mode",
        help="内置布局回显最近一次仿真的内置示意布局；真实布局回显最近一次仿真的导入布局")

    if mode == "真实布局":
        sim_info = real_sim
        st.caption(f"真实布局：{LAYOUTS.get(sim_info['layout'], sim_info['layout'])}"
                   f"（最近一次仿真的导入布局）")
    else:
        sim_info = builtin_sim
        st.caption(f"内置布局：{LAYOUTS.get(sim_info['layout'], sim_info['layout'])}"
                   f"（最近一次仿真的内置示意布局）")
    net = sim_info["net"]
    spots = sim_info["spots"]
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


def _vehicle_sort_key(v: str):
    """车辆ID排序键：带下划线时按末尾数字排序，否则按字典序；
    返回同构 (int, int, str) 元组，避免 int/str 混合比较 TypeError。"""
    if "_" in v:
        try:
            return (0, int(v.rsplit("_", 1)[-1]), v)
        except ValueError:
            pass
    return (1, 0, v)


def render_path_page():
    """页面4: 车辆动态路径 — 20帧快照回放"""
    st.subheader("🚗 车辆动态路径")
    if not st.session_state.get("sim_has_run"):
        st.info("👈 请先在 **仿真设置** 中运行仿真")
        return

    net = st.session_state.sim_net
    spots = st.session_state.sim_spots
    events = st.session_state.get("sim_events_raw") or []
    if not events:
        st.info("本次仿真没有可回放的事件日志（可能因运行超时被跳过）。"
                "请回到仿真设置重新运行仿真。")
        return
    max_time = max(e["time"] for e in events)

    if "replay_time" not in st.session_state: st.session_state.replay_time = 0.0
    if "frame_index" not in st.session_state: st.session_state.frame_index = 0
    if "frame_playing" not in st.session_state: st.session_state.frame_playing = False
    if "selected_vehicle" not in st.session_state: st.session_state.selected_vehicle = None

    all_vehs = sorted(set(
        str(e.get("vehicle_id", "")) for e in events
        if str(e.get("vehicle_id", "")) and e.get("type") in ("vehicle_arrival", "parking_assigned", "spot_entry")
    ), key=_vehicle_sort_key)

    # 移位车辆表：收集所有 shift_start 事件（演示移位动态时按此选车）
    shift_rows = []
    for e in events:
        if e.get("type") != "shift_start":
            continue
        meta = e.get("metadata", {}) or {}
        vid = str(e.get("vehicle_id", ""))
        end_time = None
        for e2 in events:
            if (e2.get("type") == "shift_end" and str(e2.get("vehicle_id", "")) == vid
                    and float(e2["time"]) >= float(e["time"])):
                end_time = float(e2["time"]); break
        shift_rows.append({
            "移位车辆": vid,
            "开始(s)": round(float(e["time"]), 1),
            "从车位": meta.get("from_spot", ""),
            "到车位(缓冲)": meta.get("to_spot", ""),
            "让行对象": str(meta.get("blocked_vehicle", "—")),
            "原因": meta.get("reason", ""),
            "回位(s)": round(end_time, 1) if end_time is not None else "未回位",
        })
    shift_vehicles = {r["移位车辆"] for r in shift_rows}

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

    with st.expander(f"🔄 移位车辆表（{len(shift_rows)} 条，演示移位动态用）", expanded=bool(shift_rows)):
        if shift_rows:
            st.dataframe(shift_rows, use_container_width=True)
            st.caption("在「② 选择车辆」中选带 🔄 标记的车辆，回放阶段选「移位」即可演示；"
                       "内层车离场时也可看到让行车的辅助虚线。")
        else:
            st.caption("本仿真没有发生移位（可提高需求强度或增加纵深车位比例后再运行）。")

    # 若已选车辆不在当前段，则重置
    if st.session_state.get("selected_vehicle") and st.session_state.selected_vehicle not in filtered_vehs:
        st.session_state.selected_vehicle = None

    st.selectbox("② 选择车辆", [""] + filtered_vehs, key="selected_vehicle",
                 format_func=lambda v: (f"🚙 {v}" if v else "— 选择车辆 —")
                                        + (" 🔄移位" if v in shift_vehicles else ""))

    hl_veh = st.session_state.selected_vehicle
    if not hl_veh:
        st.info("请选择一辆车")
        return

    veh_ev = sorted([e for e in events if str(e.get("vehicle_id","")) == hl_veh], key=lambda e: e["time"])
    pe = st.session_state.get("sim_pe")
    phases = build_vehicle_phases(net, pe, events, hl_veh) if pe else {"enter": None, "leave": None, "shifts": []}

    # 阶段选择（入库 / 离场 / 移位，只显示存在事件的阶段）
    phase_choices = []
    if phases.get("enter"): phase_choices.append(("enter", "🚗 入库"))
    if phases.get("leave"): phase_choices.append(("leave", "🚪 离场"))
    if phases.get("shifts"): phase_choices.append(("shift", "🔄 移位"))
    if not phase_choices:
        rej = [e for e in veh_ev if e.get("type") == "rejected"]
        if rej:
            reason = (rej[0].get("metadata", {}) or {}).get("reason", "停车场无空闲车位")
            st.error(f"🚫 该车辆被拒绝：{reason}")
        else:
            st.warning("该车辆尚无入库/离场/移位事件")
        return

    phase_labels = [lbl for _, lbl in phase_choices]
    if st.session_state.get("path_phase_radio") not in phase_labels:
        st.session_state.path_phase_radio = phase_labels[0]  # 防切换车辆后选项不匹配
    phase_sel = st.radio("③ 选择回放阶段", phase_labels,
                         horizontal=True, key="path_phase_radio")
    phase_key = next(k for k, lbl in phase_choices if lbl == phase_sel)

    if phase_key == "shift":
        shifts = phases["shifts"]
        if len(shifts) > 1:
            shift_labels = [f"{s['from_spot']} → {s['to_spot']}" for s in shifts]
            shift_sel = st.selectbox("选择移位段", shift_labels, key="path_shift_sel")
            seg = shifts[shift_labels.index(shift_sel)]
        else:
            seg = shifts[0]
        t_start, t_end = seg["t_start"], seg["t_end"]
        path = seg["path"]
        spot_id = f"{seg['from_spot']} → {seg['to_spot']}"
    else:
        seg = phases[phase_key]
        t_start, t_end = seg["t_start"], seg["t_end"]
        path = seg["path"]
        spot_id = seg.get("spot_id", "")

    st.session_state.path_phase_key = phase_key
    st.session_state.path_phase_seg = seg
    st.session_state.path_phase_path = path
    st.session_state.path_phase_t_start = t_start
    st.session_state.path_phase_t_end = t_end

    N = 20
    frames = [t_start + (t_end - t_start) * i / (N - 1) for i in range(N)]

    phase_label = {"enter": "入库", "leave": "离场", "shift": "移位"}.get(phase_key, phase_key)
    st.caption(f"🅿️ 车位: **{spot_id}** | {phase_label}: {t_start:.1f}s → {t_end:.1f}s ({(t_end-t_start):.1f}s)")

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
    hl_color, extra_paths = None, []

    if hl_veh:
        phase_key = st.session_state.get("path_phase_key", "enter")
        phase_seg = st.session_state.get("path_phase_seg")
        if phase_seg:
            hl_path = phase_seg.get("path") or None
            hl_color = {"enter": "#FFEB3B", "leave": "#FF9800", "shift": "#9C27B0"}.get(phase_key, "#FFEB3B")
            extra_paths = [{"path": h.get("path"), "color": "#9C27B0"}
                           for h in phase_seg.get("helper_shifts", []) if h.get("path")]
            # 高亮车位置：入库用事件插值；离场/移位按路径段插值
            if phase_key == "enter":
                ipos = interp_vehicle_pos(net, events, hl_veh, st.session_state.replay_time)
            else:
                ipos = interp_path_segment(net, hl_path or [],
                                           phase_seg.get("t_start", 0.0),
                                           phase_seg.get("t_end", 0.0),
                                           st.session_state.replay_time)
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
                                       highlight_path=hl_path, highlight_path_color=hl_color,
                                       extra_paths=extra_paths, height=480, scale=sc)
            st.plotly_chart(fig, use_container_width=True, config={"scrollZoom": True})
        with c2:
            st.caption(f"🔍 {hl_veh} 周边")
            if hl_center:
                fig = draw_parking_layout(net, spots, state, highlight_vehicle=hl_veh,
                                           highlight_path=hl_path, highlight_path_color=hl_color,
                                           extra_paths=extra_paths,
                                           view_center=hl_center, view_radius=18, height=480, scale=sc)
                st.plotly_chart(fig, use_container_width=True, config={"scrollZoom": True})
            else:
                st.info("车辆尚未出现在画面中")
    else:
        sc = (520/400)*zoom
        st.caption("🌍 全局视图 — 选择一辆车查看双窗口回放")
        fig = draw_parking_layout(net, spots, state, height=520, scale=sc)
        st.plotly_chart(fig, use_container_width=True, config={"scrollZoom": True})


def render_metrics_page(role):
    """页面5: 指标分析"""
    st.subheader("📊 指标分析")
    can_export = role.get("can_export", False)
    if not st.session_state.get("sim_has_run"):
        st.info("👈 请先在 **仿真设置** 中运行仿真")
        return

    # 超时仅作标记：结果全部展示，可勾选隐藏含超时种子的策略
    timed_out = st.session_state.get("sim_timed_out_strategies") or []
    sim_all_metrics = st.session_state.get("sim_all_metrics") or []
    hide_timed_out = False
    if timed_out:
        names = "、".join(STRATEGY_LABELS.get(n, n) for n in timed_out)
        st.warning(f"⏱ 以下策略有种子单次运行超过 {int(STRATEGY_TIME_BUDGET)} 秒（结果仍全部展示）：{names}")
        if sim_all_metrics:
            hide_timed_out = st.checkbox(
                "隐藏超时策略", value=False,
                help="勾选后，含超时种子的策略不参与排名、表格与图表展示")

    # 运行失败策略（单个策略崩溃不拖垮全部对比）
    failed = st.session_state.get("sim_failed_strategies") or []
    if failed:
        names = "、".join(f"{STRATEGY_LABELS.get(n, n)}（{err}）" for n, err in failed)
        st.error(f"⚠️ 以下策略运行失败、未参与对比：{names}")
        if not is_local_desktop():
            st.info("公网云端资源受限（内存/CPU），大参数容易失败。\n"
                    "建议改在本地运行：`py -m streamlit run app.py`（本机计算，云端只存数据）。")

    # 排名设置展示：与仿真设置页一致（权重 / 优先级）
    rank_mode = st.session_state.get("rank_mode", "加权评分")
    if rank_mode == "加权评分":
        st.markdown("### 🎚️ 指标权重（在仿真设置页调整）")
        weights_show = st.session_state.get("rank_weights", DEFAULT_WEIGHTS_BY_LABEL)
        wsum = sum(weights_show.values())
        wtab = pd.DataFrame([
            [name, weights_show.get(name, 0),
             "越高越好" if PRIORITY_METRICS[name][1] == "max" else "越低越好",
             PRIORITY_METRICS[name][2]]
            for name in list(PRIORITY_METRICS.keys())
        ], columns=["指标", "权重", "方向", "说明"])
        st.dataframe(wtab, use_container_width=True, hide_index=True)
        st.caption(f"权重总和 {wsum}{'（≠100，排名时按比例归一化）' if wsum != 100 else ' = 100 ✅'}")
    else:
        st.markdown("### 🎯 算法筛选优先级（字典序）")
        st.caption("按以下顺序逐项比较：先比第一项，相同再比下一项")
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
    timed_out_set = set(timed_out)
    visible_all_m = [m for m in sim_all_metrics
                     if not (hide_timed_out and m.get("strategy") in timed_out_set)]
    if visible_all_m:
        st.markdown("### 🏆 多策略对比")
        n_runs = st.session_state.get("sim_n_runs", 1)
        demand_source = st.session_state.get("sim_demand_source", "generated")
        src_note = ("同一导入需求序列" if demand_source in ("imported", "real_gate")
                    else f"{n_runs} 次不同随机种子的平均值（降低随机波动）")
        random_reps = st.session_state.get("sim_random_reps")
        if random_reps:
            src_note += f"；random 策略单独取 {int(random_reps)} 次平均"
        st.caption(f"基于 {src_note}")
        all_m = visible_all_m

        # 排序模式与权重在「仿真设置 → 算法排名设置」中配置，此处按配置展示
        rank_mode = st.session_state.get("rank_mode", "加权评分")

        if rank_mode == "加权评分":
            weights_by_label = st.session_state.get("rank_weights", DEFAULT_WEIGHTS_BY_LABEL)
            st.caption("当前为加权评分模式；权重在「仿真设置 → 算法排名设置」中调整")
            wdf, ranked = weighted_rank_df(all_m, weights_by_label)
            neutrals = neutralized_metric_labels(all_m)
            if neutrals:
                st.caption("⚖️ 以下指标各策略差异低于实际意义阈值，已按无区分度处理（不参与排名）："
                           + "、".join(neutrals))
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
            if can_export:
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
            if can_export:
                st.download_button("📥 下载 CSV", df.to_csv(index=False).encode('utf-8'),
                                   "parking_comparison.csv", "text/csv")

        c1, c2 = st.columns(2)
        with c1: st.bar_chart(df.set_index("策略")["满足率"], height=200)
        with c2: st.bar_chart(df.set_index("策略")["移位次数"], height=200)
        st.markdown("#### 📡 多维指标雷达图（外圈=更好）")
        st.plotly_chart(_plot_radar(all_m), use_container_width=True)
    elif sim_all_metrics:
        st.info("所有策略均含超时种子且已被隐藏。取消勾选「隐藏超时策略」即可查看。")
    else:
        # 单策略详情
        m = st.session_state.get("sim_metrics")
        if m:
            st.markdown(f"### 📈 策略: {STRATEGY_LABELS.get(m['strategy'], m['strategy'])}")
            if st.session_state.get("rank_mode", "加权评分") == "加权评分":
                st.caption("当前为加权评分模式（权重见上方表格）；单策略无对比基准，此处展示该策略各指标，"
                           "加权排名请运行「全部对比」。")
            else:
                st.caption("当前为字典序优先级模式（优先级见上方表格）。")
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
            if can_export:
                st.download_button("📥 下载指标", pd.DataFrame([m]).to_csv(index=False).encode('utf-8'),
                                   f"parking_{m.get('strategy','result')}.csv", "text/csv")

    # ── 需求时序分布 + 车辆明细（跟随所选策略；「全部对比」时可切换查看）──
    st.markdown("---")
    st.markdown("### 🕒 需求时序分布与车辆明细")
    demand_source = st.session_state.get("sim_demand_source", "generated")
    events_by_strategy = st.session_state.get("sim_events_by_strategy") or {}
    vehicles_by_strategy = st.session_state.get("sim_vehicles_by_strategy") or {}

    view_strategy = None
    if visible_all_m:
        view_options = [m.get("strategy") for m in visible_all_m
                        if m.get("strategy") in events_by_strategy]
        if view_options:
            default_idx = view_options.index("duration_greedy") if "duration_greedy" in view_options else 0
            if st.session_state.get("demand_view_strategy") not in view_options:
                st.session_state.demand_view_strategy = view_options[default_idx]
            view_strategy = st.selectbox(
                "选择要查看的策略",
                view_options,
                format_func=lambda n: STRATEGY_LABELS.get(n, n),
                key="demand_view_strategy",
                help="「全部对比」模式下可切换查看各策略的需求时序与车辆明细",
            )
            events_raw = events_by_strategy.get(view_strategy)
            vehs = vehicles_by_strategy.get(view_strategy)
        else:
            events_raw = None
            vehs = None
        if demand_source in ("imported", "real_gate"):
            src_label = "真实道闸流水" if demand_source == "real_gate" else "导入的需求序列"
            st.caption(f"事件日志来自{src_label}；当前展示策略："
                       f"**{STRATEGY_LABELS.get(view_strategy, view_strategy) if view_strategy else '—'}**。")
        else:
            st.caption("事件日志来自最近一次仿真；当前展示策略："
                       f"**{STRATEGY_LABELS.get(view_strategy, view_strategy) if view_strategy else '—'}**。")
    else:
        events_raw = st.session_state.get("sim_events_raw")
        vehs = st.session_state.get("sim_vehicles")
        if demand_source in ("imported", "real_gate"):
            src_label = "真实道闸流水" if demand_source == "real_gate" else "导入的需求序列"
            st.caption(f"事件日志来自{src_label}（所选策略）。")
        else:
            st.caption("事件日志来自最近一次仿真（所选策略）。")

    if events_raw:
        hist = build_demand_histogram(events_raw)
        if hist is not None:
            st.plotly_chart(hist, use_container_width=True)
        else:
            st.info("暂无到达/离场事件")
        rows = build_vehicle_detail_rows(events_raw)
        if rows:
            vdf = pd.DataFrame(rows)
            st.dataframe(vdf, use_container_width=True, hide_index=True)
            if can_export:
                st.download_button("📥 下载车辆明细 CSV",
                                   vdf.to_csv(index=False).encode('utf-8-sig'),
                                   "parking_vehicle_details.csv", "text/csv")
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
            if can_export:
                cdl, csave = st.columns(2)
                with cdl:
                    st.download_button("📥 浏览器下载",
                                       json_str.encode("utf-8"),
                                       download_name, "application/json")
                    st.caption("每次下载文件名带时间戳，不会重名")
                with csave:
                    render_save_as_button(json_str, download_name)
                if is_local_desktop():
                    if st.button("💾 下载到项目文件夹（仅本机运行可用）",
                                 use_container_width=True, key="save_demand_project",
                                 help="一键保存到本机项目的 data/demand_exports/（自动命名），"
                                      "回仿真设置页可从下拉直接导入，方便快速测试复现性"):
                        saved = save_demand_to_project(
                            vehs, seed=meta.get("seed"), source=demand_source,
                            generator_params=meta.get("generator_params"),
                            generated_at=meta.get("generated_at"))
                        st.success(f"✅ 已保存：{saved.name}")
                        st.caption("回「仿真设置 → 导入需求序列 JSON → 从项目文件夹选择」即可快速导入")
                with st.expander("💾 保存到指定位置（长期保留：自选目录与文件名）", expanded=False):
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
    can_upload = role["can_import_algo"]
    can_view_docs = role["can_configure"] or can_upload
    if not can_view_docs:
        st.info("仅管理员/操作员可查看新算法接入说明")
        return
    st.markdown("""
上传你的算法描述文件（**文字说明 / 代码示例 / 伪代码**，支持 `.md` / `.txt` / `.py` / `.json`），
文件会保存到仓库 `pending_algorithms/` 目录。

> 上传后，请回到 **Deep Code 对话** 中说一句「接入算法」，AI 会读取文件、编写代码、复检并接入，
> 最后跑仿真比较，选出最优算法。
""")
    if not can_upload:
        st.info("📤 上传/删除算法文件仅管理员可操作；操作员可查看以上接入说明。")
        return

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
            c1, c2 = st.columns([4, 1])
            c1.write(f"📄 `{f.name}`（{f.stat().st_size} 字节）")
            confirm_key = f"confirm_algo_del_{f.name}"
            if not st.session_state.get(confirm_key):
                if c2.button("🗑 删除", key=f"del_algo_{f.name}",
                             help=f"删除算法文件「{f.name}」", type="primary"):
                    st.session_state[confirm_key] = True
                    st.rerun()
            else:
                with c2:
                    st.warning(f"确认删除「{f.name}」？")
                    cc1, cc2 = st.columns(2)
                    if cc1.button("✅ 确认", key=f"del_algo_ok_{f.name}", type="primary"):
                        try:
                            f.unlink()
                            st.session_state.pop(confirm_key, None)
                            st.success(f"已删除「{f.name}」")
                        except Exception as e:
                            st.error(f"删除失败：{e}")
                        st.rerun()
                    if cc2.button("取消", key=f"del_algo_cancel_{f.name}"):
                        st.session_state.pop(confirm_key, None)
                        st.rerun()
    else:
        st.caption("暂无已上传的算法文件")


def render_feedback_page(role):
    """页面: 用户反馈 —— 意见箱 + 仿真结果反馈"""
    st.subheader("💬 反馈")
    is_admin = role.get("can_manage_users", False)

    if "feedback_sort_order" not in st.session_state:
        st.session_state.feedback_sort_order = "正序（早→晚）"
    st.radio("反馈排序", ["正序（早→晚）", "倒序（晚→早）"],
             horizontal=True, key="feedback_sort_order",
             help="按反馈显示时间排序（未修改过的用原始提交时间）")
    sort_desc = st.session_state.feedback_sort_order.startswith("倒序")

    with st.expander("📝 提交反馈", expanded=True):
        _render_submit_feedback()

    with st.expander("📋 我的反馈", expanded=False):
        _render_my_feedbacks(reverse=sort_desc)

    if is_admin:
        st.divider()
        st.markdown("### 🗂 全部反馈（管理员）")
        _render_admin_feedbacks(reverse=sort_desc)


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


def _feedback_display_time(f: dict) -> str:
    """反馈显示时间：管理员可覆盖 display_time，未覆盖时用原始 created_at。"""
    return f.get("display_time") or f.get("created_at", "")


def _parse_feedback_time(value):
    """把反馈时间解析为无时区的墙上时间；无法解析返回 None。"""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.replace(tzinfo=None)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _feedback_sort_key(f: dict):
    """排序键：按显示时间升序（早→晚）；时间无法解析的排在有时间的后面。"""
    disp = _feedback_display_time(f)
    disp_dt = _parse_feedback_time(disp)
    if disp_dt is not None:
        return (0, disp_dt, str(disp))
    created_dt = _parse_feedback_time(f.get("created_at", ""))
    if created_dt is not None:
        return (1, created_dt, str(disp))
    return (2, None, str(disp))


def sort_feedbacks(items, reverse=False):
    """反馈列表按显示时间排序（display_time 优先，回退 created_at）；reverse=True 为倒序（晚→早）。"""
    return sorted(items or [], key=_feedback_sort_key, reverse=reverse)


def _render_my_feedbacks(reverse=False):
    """展示当前用户自己提交的反馈及管理员回复"""
    items = sort_feedbacks(auth_list_my_feedbacks(st.session_state.token), reverse=reverse)
    if not items:
        st.caption("暂无反馈记录")
        return
    for f in items:
        cat = "仿真" if f.get("category") == "simulation" else "通用"
        status = f.get("status", "pending")
        icon = "✅" if status == "resolved" else "⏳"
        st.markdown(f"**{f.get('title', '')}**  `[{cat}]` {icon} `{status}`")
        st.caption(f"提交时间：{_feedback_display_time(f)}")
        st.write(f.get("content", ""))
        if f.get("reply"):
            st.info(f"💬 管理员回复：{f['reply']}")
        st.divider()


def _feedback_to_csv(items, reverse=False):
    """把反馈列表转为 UTF-8 BOM 的 CSV 字节（Excel 可直接打开中文）"""
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["标题", "类型", "提交人", "角色", "状态", "内容", "回复", "时间"])
    for f in sort_feedbacks(items, reverse=reverse):
        w.writerow([f.get("title", ""), f.get("category", ""), f.get("username", ""),
                    f.get("role", ""), f.get("status", ""), f.get("content", ""),
                    f.get("reply", ""), _feedback_display_time(f)])
    return buf.getvalue().encode("utf-8-sig")


def _render_admin_feedbacks(reverse=False):
    """管理员查看全部反馈、筛选、标记状态、回复、删除、导出"""
    items = sort_feedbacks(auth_list_feedbacks(st.session_state.token), reverse=reverse)
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
        st.download_button("📥 导出反馈 CSV", _feedback_to_csv(items, reverse=reverse),
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
        disp_time = _feedback_display_time(f)
        status_label = "已处理" if status == "resolved" else "待处理"
        time_txt = f"时间：{disp_time} | 状态：{status_label}"
        c_time, c_edit = st.columns([12, 1])
        with c_time:
            st.caption(time_txt)
        with c_edit:
            open_key = f"fb_dt_open_{fid}"
            if st.button("✎", key=f"fb_dt_btn_{fid}"):
                st.session_state[open_key] = not st.session_state.get(open_key, False)
                st.rerun()
        if f.get("related_run"):
            with st.expander("关联仿真信息"):
                st.code(f.get("related_run"))
        st.write(f.get("content", ""))
        if f.get("reply"):
            st.info(f"💬 已回复：{f['reply']}")

        if st.session_state.get(open_key):
            new_dt = st.text_input(
                "显示时间", value=f.get("display_time") or "",
                key=f"fb_dt_{fid}",
                placeholder="例：2026-08-27 15:30",
                label_visibility="collapsed",
            )
            cb1, cb3 = st.columns([1, 2])
            with cb1:
                if st.button("保存", key=f"fb_dt_save_{fid}"):
                    res = auth_update_feedback_display_time(
                        st.session_state.token, fid, new_dt.strip())
                    if isinstance(res, dict) and res.get("success"):
                        st.session_state[open_key] = False
                        st.success("✅ 已保存")
                    else:
                        st.error((res or {}).get("error", "保存失败"))
                    st.rerun()
            with cb3:
                if st.button("取消", key=f"fb_dt_cancel_{fid}"):
                    st.session_state[open_key] = False
                    st.rerun()

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


def _fmt_run_time(value):
    """把 Supabase 时间字符串格式化为易读本地时间。"""
    if not value:
        return ""
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return value.replace("T", " ")[:16]
    return str(value)[:16]


def _run_summary(metrics):
    """从 metrics（dict 单策略 / list 全部对比）提取代表性指标与说明。"""
    if isinstance(metrics, dict):
        return metrics, ""
    if isinstance(metrics, list) and metrics:
        best = max(metrics, key=lambda m: (m.get("satisfaction_rate", 0),
                                           -m.get("shift_count", 0)))
        label = STRATEGY_LABELS.get(best.get("strategy"), best.get("strategy"))
        return best, f"全部对比 {len(metrics)} 策略；最佳：{label}"
    return {}, ""


# 两次运行对比的指标清单（显示名, 字段, 方向）
COMPARE_FIELDS = [
    ("满足率", "satisfaction_rate", "max"),
    ("利用率", "spatial_utilization", "max"),
    ("平均等待(s)", "avg_wait_time_s", "min"),
    ("移位次数", "shift_count", "min"),
    ("移位距离(m)", "shift_distance_m", "min"),
    ("行驶距离(m)", "total_drive_distance_m", "min"),
    ("拒绝数", "rejected_count", "min"),
    ("运行耗时(s)", "runtime_s", "min"),
]


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _fmt_metric(label: str, v):
    if v is None:
        return "—"
    if label in ("满足率", "利用率"):
        return f"{v:.1%}"
    if label in ("移位次数", "拒绝数"):
        return f"{v:.0f}"
    if label.endswith("(s)"):
        return f"{v:.1f}"
    if label.endswith("(m)"):
        return f"{v:.0f}"
    return f"{v:.3f}"


def _compare_radar(rep_a: dict, rep_b: dict):
    """两次运行的五维雷达图（每维按两者 min–max 归一化，外圈=更好）。"""
    import plotly.graph_objects as go
    dims = [("满足率", "satisfaction_rate", "max"),
            ("利用率", "spatial_utilization", "max"),
            ("平均等待", "avg_wait_time_s", "min"),
            ("移位次数", "shift_count", "min"),
            ("行驶距离", "total_drive_distance_m", "min")]
    labels = [d[0] for d in dims]
    norm_a, norm_b = [], []
    for _, field, direction in dims:
        a = _num(rep_a.get(field)) or 0.0
        b = _num(rep_b.get(field)) or 0.0
        lo, hi = min(a, b), max(a, b)
        if hi == lo:
            na = nb = 0.5
        else:
            na = (a - lo) / (hi - lo)
            nb = (b - lo) / (hi - lo)
            if direction == "min":
                na, nb = 1 - na, 1 - nb
        norm_a.append(na)
        norm_b.append(nb)
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(r=norm_a + [norm_a[0]], theta=labels + [labels[0]],
                                  name="运行 A", fill="toself", opacity=0.45))
    fig.add_trace(go.Scatterpolar(r=norm_b + [norm_b[0]], theta=labels + [labels[0]],
                                  name="运行 B", fill="toself", opacity=0.45))
    fig.update_layout(height=400, margin=dict(l=60, r=60, t=50, b=50),
                      legend=dict(orientation="h", yanchor="bottom", y=-0.15),
                      polar=dict(radialaxis=dict(range=[0, 1], showticklabels=False)))
    return fig


def render_history_page(role):
    """页面: 历史运行记录（sim_runs 持久化，跨会话/跨用户可查）"""
    st.subheader("📜 历史运行")
    is_admin = bool(role.get("can_manage_users"))
    can_export = bool(role.get("can_export"))
    token = st.session_state.get("token")
    if not token:
        st.info("未登录")
        return

    st.caption("运行仿真后自动保存；管理员可查看全部用户记录，普通用户仅查看自己的。")
    runs = auth_list_sim_runs(token, all_users=is_admin)
    if not runs:
        st.info("暂无运行记录。请在「仿真设置」运行一次仿真，记录会自动保存到这里。")
        return

    rows = []
    for r in runs:
        rep, note = _run_summary(r.get("metrics"))
        rows.append({
            "id": r.get("id"),
            "时间": _fmt_run_time(r.get("created_at")),
            "用户": r.get("username", ""),
            "策略": STRATEGY_LABELS.get(r.get("strategy"), r.get("strategy")),
            "布局": r.get("layout_key") or "",
            "需求": "导入序列" if r.get("demand_source") == "imported" else "自动生成",
            "满足率": rep.get("satisfaction_rate"),
            "利用率": rep.get("spatial_utilization"),
            "移位次数": rep.get("shift_count"),
            "平均等待(s)": rep.get("avg_wait_time_s"),
            "说明": note,
        })

    df = pd.DataFrame(rows)
    strategies = sorted({x for x in df["策略"] if x})
    if strategies:
        sel_strategy = st.selectbox("按策略筛选", ["全部"] + strategies)
        if sel_strategy != "全部":
            df = df[df["策略"] == sel_strategy]

    show_cols = ["时间", "策略", "布局", "需求", "满足率", "利用率", "移位次数",
                 "平均等待(s)", "说明"]
    if is_admin:
        show_cols = ["时间", "用户"] + show_cols[1:]

    st.dataframe(
        df[show_cols].style.format({
            "满足率": "{:.1%}", "利用率": "{:.1%}",
            "平均等待(s)": "{:.1f}", "移位次数": "{:.0f}",
        }, na_rep="—"),
        use_container_width=True, hide_index=True,
    )

    if can_export:
        st.download_button(
            "📥 下载历史运行 CSV",
            df.to_csv(index=False).encode("utf-8-sig"),
            "parking_sim_runs.csv", "text/csv",
        )

    # 运行标签（对比 / 删除共用）
    labels = [f"{_fmt_run_time(r.get('created_at'))} · {r.get('username','')} · "
              f"{STRATEGY_LABELS.get(r.get('strategy'), r.get('strategy'))}"
              for r in runs]

    # ── 两次运行对比 ──
    st.markdown("---")
    st.markdown("### ⚖️ 两次运行对比")
    if len(runs) < 2:
        st.caption("至少需要两条运行记录才能对比（再跑一次仿真即可）。")
    else:
        ca, cb = st.columns(2)
        with ca:
            sel_a = st.selectbox("运行 A", labels, key="hist_cmp_a")
        with cb:
            sel_b = st.selectbox("运行 B", labels, key="hist_cmp_b",
                                 index=min(1, len(labels) - 1))
        if sel_a == sel_b:
            st.warning("请选择两条不同的运行记录")
        else:
            run_a = runs[labels.index(sel_a)]
            run_b = runs[labels.index(sel_b)]
            rep_a, note_a = _run_summary(run_a.get("metrics"))
            rep_b, note_b = _run_summary(run_b.get("metrics"))
            if not rep_a or not rep_b:
                st.info("所选记录没有可对比的指标数据。")
            else:
                for tag, note in (("运行 A", note_a), ("运行 B", note_b)):
                    if note:
                        st.caption(f"{tag}：{note}")
                cmp_rows = []
                for label, field, direction in COMPARE_FIELDS:
                    a = _num(rep_a.get(field))
                    b = _num(rep_b.get(field))
                    if a is None and b is None:
                        continue
                    a_val = a if a is not None else 0
                    b_val = b if b is not None else 0
                    if direction == "max":
                        better = ("B 更优" if b_val > a_val
                                  else "A 更优" if a_val > b_val else "持平")
                    else:
                        better = ("B 更优" if b_val < a_val
                                  else "A 更优" if a_val < b_val else "持平")
                    cmp_rows.append({
                        "指标": label,
                        "运行 A": _fmt_metric(label, a),
                        "运行 B": _fmt_metric(label, b),
                        "更优": better,
                    })
                st.dataframe(pd.DataFrame(cmp_rows), use_container_width=True, hide_index=True)
                st.plotly_chart(_compare_radar(rep_a, rep_b), use_container_width=True)

    # 删除（管理员任意 / 本人自己的）
    with st.expander("🗑 删除运行记录"):
        sel = st.selectbox("选择要删除的记录", labels, key="hist_del_sel")
        if st.button("确认删除", key="hist_del_btn"):
            idx = labels.index(sel)
            res = auth_delete_sim_run(token, runs[idx].get("id"))
            if isinstance(res, dict) and res.get("success"):
                st.success("已删除")
            else:
                st.error((res or {}).get("error", "删除失败"))
            st.rerun()


