# 停车场 App 项目目录索引

> 用途：给 AI / 协作者按需读取用。**改哪里就读哪里，不要全量加载。**
> 本索引只回答两个问题：① 文件在哪；② 改什么需求该读哪些文件。
> 维护规则：新增、删除、移动文件时，必须同步更新本索引。
> 状态入口仍是 `PROJECT_STATUS.md`（阶段/里程碑/唯一下一步），本索引只做导航。

---

## 0. 会话入口（每次会话先读）

| 文件 | 行数 | 说明 |
|---|---|---|
| `PROJECT_STATUS.md` | 266 | 项目状态唯一入口：阶段、里程碑、唯一下一步、最近变更。每次会话必读 |
| `AGENTS.md` | — | 长期项目规则（tag 纪律、向后兼容、命令约定） |
| `README.md` | — | 项目简介 |
| `PROJECT_INDEX.md` | — | 本索引：按需读文件的导航 |

---

## 1. 应用入口与配置

| 文件 | 行数 | 说明 |
|---|---|---|
| `app.py` | 86 | Streamlit 瘦入口：sidebar 路由到 9 个页面函数 |
| `local_worker.py` | 349 | **本机计算 worker**：领取云端下发的任务，用本机 CPU 跑仿真并回传结果（含网络抖动自愈重试） |
| `.streamlit/config.toml` | — | Streamlit 主题与服务器配置 |
| `.streamlit/secrets.toml.example` | — | Supabase 密钥模板（复制为 secrets.toml 使用，已被 gitignore） |
| `requirements.txt` | — | 运行依赖（streamlit/networkx/simpy/ortools/pandas/numpy/plotly/supabase） |
| `pyproject.toml` | — | 项目元数据 |
| `runtime.txt` | — | Streamlit Cloud 指定 Python 版本 |
| `credentials.local.txt` | — | 本地登录凭证（已 .gitignore，勿提交/勿分享） |
| `Dockerfile` | — | 企业部署镜像（含健康检查） |
| `docker-compose.yml` | — | 单机部署编排 |
| `.dockerignore` | — | 镜像构建排除项 |
| `.env.example` | — | Docker 环境变量模板 |
| `deploy/nginx.conf.example` | — | HTTPS 反向代理示例 |

---

## 2. UI 层（改页面 / 交互 / 认证，读这里）

| 文件 | 行数 | 说明 |
|---|---|---|
| `src/ui/pages.py` | 2300+ | **9 个页面渲染函数**（见下方函数表） |
| `src/ui/common.py` | 1480+ | UI 公共逻辑：布局构建、参数控件、回放插值、偏好持久化、运行记录、登录守卫（见下方函数表） |
| `src/viz.py` | 212 | Plotly 绘图：`draw_parking_layout`（车位/路网/车辆/路径） |
| `src/auth.py` | 395 | Supabase 认证与 RPC 封装（登录/注册/偏好/反馈/运行记录/审计/健康检查；密钥仅走 secrets/环境变量，无内置默认值；只读 RPC 网络自愈重试） |

### `src/ui/pages.py` 页面函数（改某页时直接按行号 offset 读）

| 行号 | 函数 | 页面 |
|---|---|---|
| 37 | `render_settings(role)` | 仿真设置（布局/需求/策略/参数） |
| 772 | `render_system(role)` | 系统设置（用户管理/导入导出） |
| 1014 | `render_layout_page()` | 布局图（内置/真实布局回显） |
| 1079 | `render_path_page()` | 动态路径（入库/离场/移位动画） |
| 1367 | `render_metrics_page(role)` | 指标分析（排名/需求时序/车辆明细） |
| 1728 | `render_status_page(role)` | 系统状态（健康检查） |
| 1787 | `render_algo_import_page(role)` | 新算法接入（上传/删除文件） |
| 1853 | `render_feedback_page(role)` | 意见反馈（提交/管理员回复/排序/CSV） |
| 2197 | `render_history_page(role)` | 历史运行（sim_runs 持久化/对比/导出/删除） |

### `src/ui/common.py` 主要函数（改公共工具时按行号读）

| 行号 | 函数 | 用途 |
|---|---|---|
| 226–299 | `build_linear/rectangle/lshape/triangle/circle` | 内置示意布局构建 |
| 326 | `run_single(...)` | 单次仿真运行封装 |
| 344–384 | `_avg_metrics` / `_plot_radar` | 均值与雷达图 |
| 385–508 | `save_demand_*` / `render_save_as_button` / `list_demand_files` | 需求序列保存（项目文件夹/浏览器/自定义路径） |
| 496 | `weighted_rank_df` | 加权评分排名 |
| 547–634 | `build_vehicle_detail_rows` / `build_demand_histogram` | 车辆明细表 / 需求时序直方图 |
| 635–821 | `build_timeline` / `replay_state` / `interp_vehicle_pos` / `interp_path_segment` | 动态路径时间轴与插值 |
| 822–912 | `build_vehicle_phases` / `_helper_shift_paths` | 车辆三阶段（入库/离场/移位）与让行辅助虚线 |
| 913 | `build_layout_from_json(data)` | 布局 JSON → 网络对象 |
| 938–1076 | `_load_priority_preference` / `_load_run_history` / `_load_last_params` / `persist_last_params` | Supabase 偏好读写（优先级/调参历史/最近参数） |
| 1077–1125 | `_json_safe` / `persist_sim_run` | 运行记录 JSON 清洗与入库 |
| 1126–1284 | `_sync_custom_layouts_to_globals` / `restore_custom_layouts` / `persist_custom_layouts` / `clear_custom_layouts` | 自定义布局持久化（Supabase + 本地备份自愈） |
| 1285 | `check_login()` | 登录守卫与限流 |
| 1381–1404 | `_coerce_int` / `_coerce_float` | 持久化参数类型兜底 |
| 1405–1479 | `_render_param_widget` / `render_strategy_params` / `render_env_params` | 参数控件动态渲染（含 locked/initial 回填） |

---

## 3. 核心算法包 `src/parking_opt/`（改算法 / 引擎 / 数据，读这里）

| 文件 | 行数 | 说明 |
|---|---|---|
| `domain/spot.py` | 120 | 领域模型：`SpotType`(普通/纵深)、`NodeType`、`Vehicle`、`Spot`、`Event`、`EventType` |
| `routing/path_engine.py` | 126 | 路径引擎：多入口/多出口、Dijkstra 最短路、默认口规则、`get_path_edges` |
| `simulation/parking_lot.py` | 111 | 车位分配状态（占用/缓冲位管理） |
| `simulation/engine.py` | 440 | **SimPy 离散事件仿真引擎**：时间片路口碰撞检测、离场让行、入库让行、排队等待、多入口出口、策略 `prepare` 钩子 |
| `simulation/arrival.py` | 84 | 需求生成（车辆数/时长分布/高峰占比/多入口分配） |
| `simulation/defaults.py` | 13 | 全局常量（车速/等待上限等） |
| `strategies/registry.py` | 52 | 策略注册表（登记/实例化/参数声明） |
| `strategies/__init__.py` | 26 | 登记全部内置策略（新增算法在此追加一行） |
| `strategies/baselines.py` | 91 | `BaseStrategy` + FCFS/最近路径/随机 |
| `strategies/greedy.py` | 179 | 贪心 / 离场贪心 / 时长感知贪心（主方法） |
| `strategies/fusion.py` | 66 | 融合算法接口 + `PeakOffPeakFusion` 示例 |
| `strategies/mosa.py` | 635 | 算法一：NSGA-II 离线多目标预分配（场景权重） |
| `strategies/risk_scoring.py` | 156 | 算法二：在线风险感知多准则评分 |
| `evaluation/metrics.py` | 72 | 指标计算（利用率/移位/等待/行驶） |
| `evaluation/ranking.py` | 130 | 加权多指标评分排名（min–max 归一化 + 实际意义阈值防噪声） |
| `io/demand_io.py` | 138 | 需求序列 JSON 导出/导入（schema v1） |
| `io/road_io.py` | 117 | 布局/路网 JSON 读写 |
| `io/realtime_io.py` | 220 | **真实数据接口预留**：道闸流水/车位状态 CSV 解析 → 需求序列（车牌脱敏） |
| `optimization/cpsat_baseline.py` | 81 | CP-SAT 离线理论最优基准 |
| `cli/main.py` | 123 | 命令行入口 |

---

## 4. 数据库迁移 `migrations/`（Supabase SQL，改表/RPC 读这里）

| 文件 | 行数 | 说明 |
|---|---|---|
| `01_setup.sql` | 263 | `users` 表 + 认证/用户管理 RPC（login/register/validate/logout/list/role/密码/导入导出） |
| `02_preferences.sql` | 65 | `user_preferences` 表 + `get/set_preference` RPC |
| `03_feedback.sql` | 150 | `feedback` 表 + 反馈提交/列表/状态/回复/删除 RPC |
| `04_feedback_display_time.sql` | 31 | feedback 加 `display_time` 字段 + `update_feedback_display_time` RPC |
| `05_security_hardening.sql` | 445 | **bcrypt + audit_log + search_path 加固**（重写认证/反馈 RPC） |
| `06_sim_runs.sql` | 104 | **sim_runs 运行记录表 + save/list/delete RPC** |
| `07_compute_tasks.sql` | 137 | **本地计算任务表 + create/claim/complete/get RPC** |

> 注意：RPC 均为 `SECURITY DEFINER`，新增函数必须自己校验 token/角色。

---

## 5. 测试 `tests/`（改完对应模块跑这里）

| 文件 | 覆盖内容 |
|---|---|
| `test_core.py` | 领域模型/路径引擎基础 |
| `test_strategies_regression.py` | 6 基础策略回归 |
| `test_demand_io.py` | 需求序列导入导出 |
| `test_ranking.py` | 加权排名 |
| `test_engine_robustness.py` | 引擎鲁棒性（不可达车位/NaN 防御） |
| `test_engine_shift_race.py` | 移位让行并发竞态 |
| `test_engine_timeslice.py` | 时间片路口碰撞检测 |
| `test_mosa.py` | 算法一 MOSA |
| `test_risk_scoring.py` | 算法二 risk_scoring |
| `test_multi_entry.py` | 多入口多出口 |
| `test_realtime_io.py` | 真实道闸流水/车位状态解析（10 项） |
| `test_ui_helpers.py` | UI 纯函数（车辆ID排序键 3 项 + worker 启动脚本 2 项） |
| `test_local_worker.py` | local_worker GBK 输出兜底 + 网络自愈重试（3 项） |
| `test_auth_net.py` | 公网 app RPC 网络自愈重试（3 项） |

---

## 6. 文档 `docs/`

| 路径 | 说明 |
|---|---|
| `docs/新算法接入说明.md` | 新算法接入步骤（改算法前先读） |
| `docs/布局导入格式说明.md` | 布局 JSON 格式说明 |
| `docs/research/05_最终路线决策.md` | 阶段 A 最终路线决策（权威路线文档） |
| `docs/algorithms/risk_scoring.md` | 算法二教学文档 |
| `docs/model/*.md` | 问题定义/数学模型/移位模型/伪代码（7 篇） |
| `docs/data/*.md` | 数据字典、输入输出模式、真实数据接口规范 v1 |
| `docs/部署运维说明.md` | 部署/HTTPS/备份/监控/安全自查清单 |
| `docs/道闸流水CSV填写说明.md` | 给停车场运营方的 CSV 填写指南（列名/时间格式/示例/常见错误） |
| `docs/企业可用性检查清单.md` | 交付前三方可用性自检清单 |
| `data/samples/道闸流水示例.csv` | 道闸流水示例文件（可直接上传测试） |
| `docs/architecture/01_软件架构.md` | 软件架构 |
| `docs/plans/*.md` | 各阶段执行计划 |
| `docs/handoffs/*.md` | 阶段交接摘要 |
| `docs/experiments/*.md` | 实验与统计方案、验收标准 |
| `docs/review/C7_全面复核报告.md` | 阶段 C 复核报告 |
| `docs/项目结构说明.md` | 早期结构说明（信息可能滞后，以本索引为准） |
| `docs/启动包完整性检查.md` / `docs/启动包自动检查结果.json` | 自检文档与结果 |

---

## 7. 脚本 `scripts/`

| 文件 | 行数 | 说明 |
|---|---|---|
| `validate_starter_package.py` | 576 | 启动包自检（默认只读，改完跑 `py scripts/validate_starter_package.py`） |
| `exp_risk_scoring.py` | 232 | 算法二实验脚本（产出 `outputs/`） |

---

## 8. 其他目录

| 路径 | 说明 |
|---|---|
| `configs/users.json` | 本地用户配置（现为 `{}`，历史遗留） |
| `data/` | 本地数据目录（`demand_exports/` 需求序列下载、`samples/` 示例文件） |
| `outputs/` | 实验产物（不入库） |
| `references/` | 原始材料、文献 bib、论文（只读） |
| `prompts/` | 四阶段提示词（A/B/C/D） |
| `pending_algorithms/` | 待接入算法快照（当前为空） |
| `prototypes/`、`app/`、`configs/` 等 | 占位目录（.gitkeep） |

---

## 9. 需求 → 文件速查表（改什么读什么）

| 需求 | 必读文件 | 顺带检查 |
|---|---|---|
| 改登录/注册/角色/会话 | `src/auth.py` + `migrations/01_setup.sql` | `src/ui/pages.py:396` 系统设置页 |
| 改密码/审计/密钥 | `src/auth.py` + `migrations/05_security_hardening.sql` | `.streamlit/secrets.toml.example` |
| 改反馈功能 | `src/auth.py` 反馈段 + `migrations/03/04*.sql` | `src/ui/pages.py:1419` |
| 改运行记录/历史页 | `src/auth.py` 运行记录段 + `migrations/06_sim_runs.sql` | `src/ui/pages.py:1688`、`src/ui/common.py` persist_sim_run |
| 改本地计算任务 | `local_worker.py` + `migrations/07_compute_tasks.sql` | `src/auth.py` 任务 RPC、`src/ui/pages.py` 计算位置/下发/载入 |
| 改真实数据导入 | `io/realtime_io.py` + `docs/data/03_真实数据接口规范_v1.md` | `src/ui/pages.py` 需求数据源、`tests/test_realtime_io.py` |
| 改企业 CSV 文档 | `docs/道闸流水CSV填写说明.md` + `data/samples/道闸流水示例.csv` | `io/realtime_io.py` 列名别名表 |
| 改部署/运维 | `Dockerfile` + `docker-compose.yml` + `docs/部署运维说明.md` | `deploy/nginx.conf.example`、`.env.example` |
| 改偏好/参数持久化 | `src/ui/common.py:902-1094` + `migrations/02_preferences.sql` | `src/auth.py` RPC 封装 |
| 新增算法/策略 | `docs/新算法接入说明.md` + `strategies/registry.py` + `strategies/__init__.py` | 新策略文件、`tests/`、`docs/algorithms/` |
| 改仿真引擎 | `simulation/engine.py` | `simulation/parking_lot.py`、`routing/path_engine.py`、`tests/test_engine_*` |
| 改需求生成 | `simulation/arrival.py` | `io/demand_io.py`、`tests/test_demand_io.py` |
| 改指标/排名 | `evaluation/metrics.py` + `evaluation/ranking.py` | `src/ui/pages.py:968`、`tests/test_ranking.py` |
| 改布局图/动态路径/动画 | `src/ui/common.py` + `src/viz.py` | `src/ui/pages.py:630/684` |
| 改参数控件渲染 | `src/ui/common.py:1196-1282` | 各策略 `PARAMS` 声明 |
| 改布局导入格式 | `io/road_io.py` + `docs/布局导入格式说明.md` | `src/ui/common.py:877`、`docs/data/` |
| 改 Supabase 表/RPC | `migrations/0*.sql` | `src/auth.py` 对应封装 |
| 改主题/部署配置 | `.streamlit/config.toml` + `requirements.txt` | `runtime.txt` |
