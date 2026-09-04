---
project: 智能停车场车位分配与纵深移位优化
status_version: 78
last_updated: 2026-09-04
current_stage: D
stage_status: in_progress
current_milestone: stage-d-dynamic-path-feedback
git_initialized: true
current_branch: stage-d-deliver
last_verified_commit: f0010d6
current_exec_plan: docs/plans/stage-d-dynamic-path-feedback.md
latest_handoff: docs/handoffs/2026-09-02-权限重构与代码拆分.md
next_prompt: null
authoritative_route_document: docs/research/05_最终路线决策.md
current_stage_blockers: []
downstream_blockers: []
ui_framework_preference: Streamlit（已确认）
deliverable_type: 向管理员推荐方案的Dashboard
status_maintainer: 项目主线程或用户指定协调线程
---

# 项目当前状态

> 本文件是跨 Codex 对话的项目状态唯一入口。只记录当前有效状态；详细过程见 ExecPlan、阶段交接摘要和 Git 历史。

## 1. 项目一句话说明

研究普通独立车位与纵深车位混合场景下的动态车位分配，在保证可行和服务需求的前提下，优先提高有效车位时空利用率，并降低移位次数与移位距离。

## 2. 当前状态快照

- **当前阶段**：阶段 D（应用与交付），进行中；
- **验收状态**：`in_progress`；
- **Git 状态**：已初始化，当前在 `stage-d-deliver` 分支；
- **当前里程碑**：`stage-d-dynamic-path-feedback`（动态路径页反馈修复：入库虚线按实际入口、离场/移位动画、移位车辆表；多入口多出口已验收；已于 2026-08-28 用户验收通过）；布局图「内置/真实布局」回显 + 指标分析需求时序按策略切换，已于 2026-08-28 用户验收通过；反馈按修改后显示时间自动排序（含正序/倒序切换），已于 2026-08-28 用户验收通过；**全库 Python 文件已按功能拆分至单文件 ≤200 行**（AGENTS.md 3.2.1 已写入强制规则：源码/测试/脚本全部适用，超 200 行必须按功能拆，一个功能一个文件；`scripts/check_file_lines.py` 自检通过，143 测试通过），已于 2026-09-02 完成；**权限体系全面重做**（9 板块可见性 + 14 项功能权限逐按钮开关：新增本地计算/删除本地任务/导入需求/导出需求/导出结果/删除历史/提交反馈/反馈管理；内置三角色按推荐矩阵：管理员全开、操作员含本地计算与历史删除、访客仅运行+反馈；「自定义」角色可同时勾选板块和功能权限，permissions 存 {sections, features}；迁移 13 最终版 + 迁移 14 旧数据升级），已于 2026-09-02 完成并**用户验收通过**；**动态路径移位修复**（离场段起点改为按事件流重放车辆实际车位：移位后未回位从缓冲位出发、已回位从回位目标出发；移位阶段新增「回位段」可选动画；引擎 `move_vehicle` 同步 `assigned_spot`、`free` 释放缓冲位占用），已于 2026-09-02 完成；**回放路径假直线与内置布局单向边修复**（回放路径找不到真实路线时按引擎口径回退入口、绝不画穿越空地的假直线；内置 linear/rectangle/circle 三布局补齐入口反向边——此前车能进不能出，离场动画无路可画；新增回归测试，全部内置布局每个车位必须能返回入口），已于 2026-09-02 完成，待用户验收；
- **当前阶段阻断项**：无（迁移 13/14 已直连执行并只读核验：`users.permissions` 列、`app_settings.custom_sections` 模板（当前 9 板块 + 13 功能开）与 login_user / validate_session / list_users / update_user_role / get_custom_sections / save_custom_sections 六个 RPC 均已就位）；
- **当前唯一下一步**：☁️ 云端重新部署本次动态路径修复（Deploy）→ 🚗 验收动态路径移位场景：选一辆 🔄移位 车 → 「③ 选择回放阶段」选「移位」应能看到「去程 A→B」与「回位 B→A」两段可选；选「离场」时起点应为车辆离场时刻实际车位（移位后未回位=缓冲位、已回位=回位目标）；随后企业交付前人工待办：删旧 publishable key、正式交付前改管理员强密码、数据授权协议、试点基线、`docs/企业可用性检查清单.md`。
- **禁止事项**：改动前必须先打备份 tag；不破坏现有测试的向后兼容（策略 `cls()` 无参构造）。

当 `current_exec_plan` 或 `latest_handoff` 为 `null` 时，新对话应跳过对应读取步骤，不得自行猜测文件路径。

允许的阶段状态只有：

```text
not_started
in_progress
awaiting_review
approved
blocked
superseded
```

为保证项目自检脚本在没有第三方 YAML 库时仍能严格验证，front matter 中的
`current_stage_blockers` 和 `downstream_blockers` 使用 **YAML 兼容的单行 JSON 数组**。
不得改成脚本无法完整解析的缩进嵌套结构。

## 3. 阶段进度总览

- [x] **阶段 A（研究与路线决策）**：已完成并批准。
- [x] **阶段 B（模型与工程设计）**：已完成并批准，核心定义已冻结。
- [x] **阶段 C（核心实现与验证）**：已完成。领域模型、路网、路径引擎、离散事件仿真、基线/贪心/时长感知策略、指标计算、CP-SAT 离线基准均已实现并带测试。
- [ ] **阶段 D（应用与交付）**：进行中。Streamlit 多页面 Dashboard 已可运行；已完成「算法接入接口 + 参数化」与「UI 拆分重构 + 交付体验优化」并验收通过。

阶段 A 最终推荐路线：

> **路网成本预处理 + 离散事件仿真 + CP-SAT 小规模离线基准 + 带缓冲位的在线贪心策略（主方法）+ 确定性降级，辅以 Dijkstra-SA 作为对照基线。**

详见 `docs/research/05_最终路线决策.md`。

## 4. 已完成并确认

- [x] 四阶段流程、`AGENTS.md`、`.agent/PLANS.md`、阶段提示词与验收提示词；
- [x] 跨对话状态管理、Git/归档/隐私规则、启动包自检脚本；
- [x] 阶段 A：原方案审查、文献调研、候选算法比较、最终路线决策；
- [x] 阶段 B：问题定义、数学模型、数据契约、架构与实验协议冻结；
- [x] 阶段 C：领域模型、路网与路径引擎、SimPy 仿真引擎、需求生成、6 个策略（FCFS/最近/随机/离场贪心/朴素贪心/时长感知贪心）、指标计算、CP-SAT 离线基准；
- [x] 阶段 C/D：排队等待机制（车位满排队 30min 上限）、多 seed 统计、算法优先级字典序推荐、CP-SAT 理论最优对照；
- [x] 阶段 D：Streamlit 多页面 Dashboard（登录/仿真设置/系统设置/布局图/动态路径/指标分析）、Supabase 认证与偏好持久化、自定义布局 JSON 导入。
- [x] 阶段 D：UI 拆分重构（app.py 1827→90 行瘦入口、src/auth·viz·ui 模块化）+ 8 项交付体验优化（备份脱敏/trace 合并/进度条/反馈分页/动态路径分段/登录限流常量/DESCRIPTION 收敛）+ 系统状态页 use_container_width 废弃预警，测试全绿并已验收。
- [x] 阶段 D：算法一 MOSA 接入（离线全信息 NSGA-II 多目标优化：f1 总行驶时间/f2 总行驶距离/f3 利用率均衡，场景权重高峰重时间/平峰重距离/饱和重利用率；BaseStrategy.prepare 钩子 + 引擎自动调用 + 登记注册表网页自动出现，规模保护 >60 车位/>120 车回退贪心），pytest 62 passed、自检通过，已验收。
- [x] 阶段 D：策略最近参数持久化（运行仿真后把该策略本次参数保存到 Supabase 用户偏好 `last_params_v1`，登录/恢复会话自动回填设置页控件，reboot/刷新后参数不丢；持久化值带类型转换与范围夹取兜底），pytest 69 passed、自检通过，已验收。
- [x] 阶段 D：交付体验第三批（布局持久化兜底：Supabase 写入失败可见 + 本地备份文件自愈；新算法接入页文件删除二次确认；反馈显示时间管理员可改并保存（新迁移 `04_feedback_display_time.sql` 需在 Supabase 执行）；权限落实 `can_export`（访客禁止下载/导出），操作员可见新算法接入说明文字但不可上传），pytest 71 passed、自检通过、AppTest 通过，已验收。
- [x] 阶段 D：反馈显示时间提示清理（用户验收后反馈：管理员反馈列表时间行删除「（原始：…）」提示、状态由英文 pending/resolved 改为中文「待处理/已处理」、✎ 编辑面板删除「恢复原始」按钮仅保留「保存/取消」、占位提示不再回显原始时间），pytest 71 passed、自检通过，已于 2026-08-28 验收通过。
- [x] 阶段 D：算法二 risk_scoring 接入（在线「风险感知多准则评分」：候选车位三项原始代价 min–max 归一化后加权 `C = w_d·距离 + w_r·预期移位风险 + w_p·结构惩罚`，argmin 选位；只用当前状态与预估离场，不读真实停车时长；登记注册表网页自动出现 3 个权重滑杆；并入教学文档/18 项单元测试/实验脚本+产物/4 条新文献；另修复实验暴露的引擎移位让行并发竞态并新增 2 项回归测试），pytest 91 passed、自检通过，已于 2026-08-28 验收通过。
- [x] 阶段 D：多入口多出口改造（布局允许多个 `type="entry"`/`type="exit"` 节点，旧单入口布局兼容；`Vehicle` 增 `entry_id`/`exit_id`；`generate_demand` 用 seed 派生独立随机流（+100003/+200003）等概率分配每车入口与出口；引擎按车辆口进出、出口不可达回退入口并记 DEGRADATION；SPOT_ENTRY/DEPARTURE 事件带 entry/exit 元数据；四个策略距离语义改为「该车入口」；需求 JSON 可选 `entry_id`/`exit_id`；viz 渲染全部入口/出口；导入校验放宽为至少一个入口），pytest 101 passed、自检通过（138 文件），已于 2026-08-28 验收通过。
- [x] 阶段 D：动态路径页反馈修复 + 移位车辆表（①入库黄色虚线按该车实际入口；②新增「③ 选择回放阶段」入库/离场/移位，离场动画车位→出口、移位动画 from→to；③离场阶段让行移位轨迹以辅助虚线绘制；另增补「🔄 移位车辆表」折叠区列出全部移位事件，并在选车下拉对移位车标记），pytest 103 passed、自检通过（139 文件），已于 2026-08-28 验收通过。
- [x] 阶段 D：反馈按修改后显示时间自动排序 + 正序/倒序切换（反馈列表按显示时间排序，未修改的按原始提交时间参与排序、时间无法解析的排最后；反馈页顶部「反馈排序」可切换正序 早→晚 / 倒序 晚→早；「我的反馈」「管理员全部反馈」与 CSV 导出统一跟随；管理员修改显示时间保存后自动重排），pytest 103 passed、自检通过（139 文件）、AppTest 反馈页通过，已于 2026-08-28 验收通过。
- [x] 阶段 D：💻 本地计算全链路公网验收通过（222 账号、内置布局、约 200 车位，结果正常载入指标页）+「📂 载入最近一次结果」（迁移 10）公网验收通过 + **「🗑 删除该任务」刷新后失效修复**（用户反馈：刷新页面后 session 丢失 task_id，删除按钮失效、pending 任务在网页上"消失"但实际仍在队列被 worker 继续领取——新增 `migrations/12_latest_task_any.sql` 并已直连执行：`get_latest_compute_task_any` RPC 返回该用户最近一条任务任意状态；`src/ui/pages.py` 新增 `_resolve_delete_task_id` 纯函数，删除按钮改为不依赖 session——无 task_id 时自动定位最近任务，二次确认显示任务 id/状态，无任务时按钮置灰；「🔄 检查」与 caption 提示同步说明刷新后找回/叫停方式），pytest 143 passed、自检通过（171 关键文件），已于 2026-09-02 公网验收通过（含「刷新后删除」场景）；

## 5. 已批准的项目级决定

| 事项 | 当前决定 | 状态 |
|---|---|---|
| 停车场类型 | 普通独立车位为基础，纵深式车位为重要扩展 | 已确认 |
| 当前真实数据 | 平面图、车位坐标、道路连接、入口和出口数量 | 已确认 |
| 初步验证 | 使用明确标记的仿真数据 | 已确认 |
| 规模 | 约 100 个物理停车位置 | 已确认 |
| 使用环境 | ChatGPT 桌面应用中的 Codex（原 Codex App），普通笔记本 | 已确认 |
| 优先目标 | 有效利用率、移位距离 | 已确认 |
| 旧路线 | 可以否定，但必须说明仍符合立项目标 | 已确认 |
| 交付方式 | 分阶段完成研究、模型、代码和展示 | 已确认 |
| 真实车辆控制 | 不属于当前项目范围 | 已确认 |
| 展示框架 | Streamlit | 已确认（原暂定，阶段 D 已采用） |
| 主方法 | 时长感知贪心（DurationAwareGreedy），原贪心降为基线 | 已确认 |

## 6. 尚未冻结

- 融合算法的具体融合语义（时段切换/权重混合/概率选择等由接入方决定）；
- 各算法参数的最优取值（本阶段目标是「可调」，不预设最优）；
- 真实数据接口的最小字段（阶段 D 持续完善）。

## 7. 数据与结论边界

### 当前已有

- 停车场平面图、车位坐标、道路连接、入口和出口数量。

### 当前缺少

- 真实车辆到达、停车和离场时序；
- 实际等待、拥堵、阻挡和移位记录；
- 预约、特殊车辆和预计离场信息。

### 当前允许证明

- 模型和工程逻辑是否可实现；
- 在明确仿真场景中相对指定基线的表现；
- 系统能否提供真实数据接入接口。

### 当前不能声称

- 在真实停车场必然提高某个百分比；
- 在所有场景和指标上优于所有方法；
- 仿真分布等同真实规律；
- 已具备真实无人驾驶车辆控制能力。

## 8. 代码、测试与实验状态

- 核心代码：已完成（`src/parking_opt/` 分层包）；
- Python 环境与依赖：见 `requirements.txt`（streamlit/networkx/simpy/ortools/pandas/numpy/plotly/supabase）；
- 单元/回归测试：已有（`tests/test_core.py`、`tests/test_strategies_regression.py`、`tests/test_demand_io.py`、`tests/test_ranking.py`、`tests/test_engine_robustness.py`、`tests/test_mosa.py`、`tests/test_engine_timeslice.py`、`tests/test_risk_scoring.py`、`tests/test_engine_shift_race.py`、`tests/test_multi_entry.py`、`tests/test_realtime_io.py`、`tests/test_ui_helpers.py`、`tests/test_local_worker.py`、`tests/test_auth_net.py`，共 143 项）；
- 正式实验协议：已冻结（阶段 B）；
- 启动包自检：`python scripts/validate_starter_package.py`（默认只读）；
- 备份存档：git tag `backup-before-delete-button-accept-20260902`、`backup-before-delete-button-always-20260902`、`backup-before-delete-task-20260902`、`backup-before-operator-worker-package-20260902`、`backup-before-latest-task-load-20260902`、`backup-before-local-task-archive-20260902`（2026-09-02）、`backup-before-migration09-20260901`、`backup-before-migration08-20260901`、`backup-before-auth-net-retry-20260901`、`backup-before-worker-net-retry-20260901`、`backup-before-worker-bat-download-20260901`、`backup-before-worker-gbk-fix-20260901`、`backup-before-migration07-executed-20260901`、`backup-before-local-worker-20260901`、`backup-before-cloud-crash-guard-20260901`、`backup-before-layout-restore-accept-20260901`、`backup-before-layout-restore-hardening-20260901`（2026-09-01）、`backup-before-timeout-mark-only-20260831`、`backup-before-timeout-show-all-20260831`、`backup-before-path-page-typeerror-20260831`、`backup-before-scene-b-shift-race-20260831`（2026-08-31）、`backup-before-feedback-sort-accept-20260828`、`backup-before-feedback-sort-desc-20260828`、`backup-before-feedback-time-sort-20260828`、`backup-before-layout-metrics-follow-20260828`、`backup-before-layout-metrics-follow-accept-20260828`、`backup-before-dynamic-path-feedback-20260828`、`backup-before-dynamic-path-feedback-accept-20260828`、`backup-before-shift-table-20260828`、`backup-before-multi-entry-exit-20260828`、`backup-before-risk-scoring-accept-20260828`（2026-08-28）；`backup-before-risk-scoring-20260827`、`backup-before-fb-time-hint-cleanup-20260827`、`backup-before-layout-algo-feedback-perm-20260827`、`backup-before-scene-hint-fix-20260827`、`backup-before-last-params-persist-20260827`、`backup-before-mosa-20260827`（2026-08-27）；更早 `backup-before-ui-refactor-20260818`（2026-08-18）、`backup-before-algo-interface-20260817`（2026-08-17）。

## 9. 当前关键文件

| 文件 | 用途 | 状态 |
|---|---|---|
| `AGENTS.md` | 长期项目规则 | 有效 |
| `PROJECT_STATUS.md` | 项目状态唯一入口 | 有效 |
| `PROJECT_INDEX.md` | 项目目录索引（按需读取导航 + 需求→文件速查表） | 有效，本轮新增 |
| `.agent/PLANS.md` | ExecPlan 规范 | 有效 |
| `app.py` | Streamlit 多页面 Dashboard 瘦入口（~90 行） | 有效，本轮已完成拆分 |
| `local_worker.py` | 本机计算 worker（登录/领任务/本机仿真/回传；GBK 兜底 + 网络自愈 + 进度打印 + 操作员交互登录缓存 + worker_config.toml 配置） | 有效，本轮加固 |
| `src/local_compute.py` | 本地计算纯函数（布局构建/仿真运行/车辆序列化），不依赖 Streamlit/Pandas/Plotly，worker 与 UI 共用 | 有效，本轮新增 |
| `tests/test_local_worker.py` | worker GBK 输出兜底 + 网络自愈重试回归测试（3 项） | 有效，本轮新增 |
| `tests/test_auth_net.py` | 公网 app RPC 网络自愈重试回归测试（3 项） | 有效，本轮新增 |
| `src/auth.py` | Supabase 认证后端（登录/RPC/反馈/偏好/运行记录/审计；只读 RPC 网络自愈重试 + 任务重新排队） | 有效，本轮加固 |
| `migrations/05_security_hardening.sql` | bcrypt + 审计日志 + search_path 加固 | 有效，本轮新增 |
| `migrations/06_sim_runs.sql` | 仿真运行记录表 + RPC | 有效，本轮新增 |
| `migrations/07_compute_tasks.sql` | 本地计算任务表 + 4 任务 RPC | 有效，本轮新增 |
| `migrations/08_worker_token.sql` | worker 独立登录态（login_worker + 双 token 校验） | 有效，本轮新增 |
| `migrations/09_task_requeue.sql` | 卡住任务重新排队 + claim 15 分钟自愈 | 有效，本轮新增 |
| `migrations/10_latest_task_load.sql` | 载入最近一次本地计算结果 RPC（get_latest_compute_task，含 payload+result） | 有效，本轮新增 |
| `migrations/11_delete_compute_task.sql` | 删除本地计算任务 RPC（下发错了叫停；任意状态可删） | 有效，本轮新增 |
| `migrations/12_latest_task_any.sql` | 查询最近一条本地计算任务 RPC（任意状态；删除按钮刷新后仍可定位任务） | 有效，本轮新增 |
| `src/parking_opt/io/realtime_io.py` | 真实道闸流水/车位状态解析（企业对接预留） | 有效，本轮新增 |
| `docs/data/03_真实数据接口规范_v1.md` | 真实数据接口规范 v1 | 有效，本轮新增 |
| `docs/部署运维说明.md` | 部署/HTTPS/备份/安全自查 | 有效，本轮新增 |
| `docs/道闸流水CSV填写说明.md` | 给停车场运营方的 CSV 填写指南 + 示例文件 | 有效，本轮新增 |
| `docs/企业可用性检查清单.md` | 交付前三方可用性自检清单 | 有效，本轮新增 |
| `src/viz.py` | Plotly 绘图（trace 已合并提速） | 有效 |
| `src/ui/` | 常量/布局构建器/仿真工具 + 8 页面函数 | 有效 |
| `src/parking_opt/strategies/baselines.py` | 策略基类 + FCFS/最近/随机 | 有效 |
| `src/parking_opt/strategies/greedy.py` | 贪心/离场贪心/时长感知贪心 | 有效 |
| `src/parking_opt/strategies/registry.py` | 统一策略注册表 | 有效 |
| `src/parking_opt/strategies/fusion.py` | 融合算法接口 + 示例 | 有效 |
| `src/parking_opt/strategies/mosa.py` | 算法一 MOSA：NSGA-II 离线多目标预分配策略 | 有效 |
| `src/parking_opt/strategies/risk_scoring.py` | 算法二 risk_scoring：风险感知多准则评分（在线） | 有效，本轮新增 |
| `tests/test_risk_scoring.py` | 算法二 18 项单元测试 | 有效，本轮新增 |
| `tests/test_engine_shift_race.py` | 引擎移位让行并发竞态回归测试（2 项） | 有效，本轮新增 |
| `docs/algorithms/risk_scoring.md` | 算法二教学文档（数学定义/伪代码/实验/优缺点） | 有效，本轮新增 |
| `scripts/exp_risk_scoring.py` | 算法二第一版实验脚本（产出 `outputs/`，本地产物） | 有效，本轮新增 |
| `src/parking_opt/strategies/rho.py` | 算法三 RHO 滚动时域动态修正（在线，免 statsmodels） | 有效，本轮新增 |
| `src/parking_opt/strategies/_rho_forecast.py` | 算法三 SARIMA-lite 预测器（Holt + AR(1) 误差修正） | 有效，本轮新增 |
| `tests/test_rho.py` | 算法三 19 项单元/回归测试 | 有效，本轮新增 |
| `docs/algorithms/rho_rolling.md` | 算法三教学文档（数学定义/伪代码/实验/优缺点） | 有效，本轮新增 |
| `scripts/exp_rho.py` | 算法三第一版实验脚本（产出 `outputs/exp_rho_*`，本地产物） | 有效，本轮新增 |
| `src/parking_opt/io/demand_io.py` | 需求序列 JSON 导出/导入（schema v1） | 有效，本轮新增 |
| `src/parking_opt/evaluation/ranking.py` | 加权多指标评分排名（归一化+方向） | 有效，本轮新增 |
| `docs/新算法接入说明.md` | 新算法接入步骤文档 | 有效 |
| `docs/布局导入格式说明.md` | 自定义布局 JSON 格式说明 | 有效 |
| `docs/research/05_最终路线决策.md` | 阶段A最终路线决策（权威路线文档） | 已批准 |
| `references/original/` | 两份原始材料，只读 | 已包含 |

## 10. 阻断项与风险

### 当前阶段阻断项

无。

### 重要风险

- 真实时序数据不足，早期只能做仿真可行性验证；
- 利用率与移位、等待和出库效率可能冲突；
- 动态算法可能发生未来真值泄漏；
- 约 100 个车位可能需要复杂度控制；
- 旧方案与主算法必须在公平条件下比较；
- 算法接口与参数化改造需保持向后兼容，不得破坏现有测试。

## 11. 当前唯一下一步

1. ✅ 「💻 本地计算」全链路公网验收通过（222 账号、内置布局、约 200 车位、结果正常载入指标页）；「📦 下载操作员本地计算包（zip）」在操作员自己电脑解压双击即可用（首次自动装精简依赖 + 输入自己的账号密码），操作员依赖安装失败问题已随 v3 包（Python 版本/位数诊断 + 升级 pip + 引导发报错）解决。
2. ✅ 「📂 载入最近一次结果」（迁移 10）公网验收通过：浏览器 session 丢失 task_id（刷新/重开/换电脑）后，一键从 Supabase 找回最近一次已完成的本地计算结果。
3. ✅ 「🗑 删除该任务」刷新后删除场景公网验收通过——不依赖 session（无 task_id 时自动定位该用户最近一条任务，任意状态均可删，二次确认显示任务 id/状态，迁移 12 已执行并验证 RPC 存在）。
4. ✅ ☁️ 云端 Streamlit 重新部署（权限体系版）：公网已生效，权限体系按矩阵验收通过（管理员保存自定义模板成功；114514(custom)/222(操作员)/访客号 导航与按钮均符合预期）。
5. ☁️ 云端重新部署本次动态路径修复（`a94e2e3`）：本地 156 passed、行数检查与启动包自检全绿，已推送到 GitHub；云端 Reboot 后若仍跑旧代码，用「改 requirements.txt 触发全量重建」或「删除后重新部署（先记下 Secrets）」强制生效。
6. 🚗 验收动态路径移位场景：选一辆 🔄移位 车 → 「移位」阶段应能看到「去程 A→B」与「回位 B→A」两段可选动画；「离场」阶段起点应为该车离场时刻实际车位（移位后未回位=缓冲位、已回位=回位目标，不再是移位前原车位）。
7. 企业交付前人工待办：删旧 publishable key、正式交付前改管理员强密码、数据授权协议、试点基线、`docs/企业可用性检查清单.md`。
8. 🚗 验收算法三（RHO 滚动时域动态修正）：仿真设置页策略下拉出现「RHO 滚动时域动态修正」，选中后出现 9 个参数控件；运行后行为说明——高峰/突发时自动切兜底（就近分配），平稳时用基准方案（时长感知贪心）。

## 12. 预计后续需要用户确认

- 融合算法的具体融合语义与比例参数范围；
- 各算法参数最终默认值与取值范围；
- 真实布局数据的接入与脱敏方式。

## 13. 最近重要变更

- 2026-09-04：**算法三 RHO 滚动时域动态修正接入**（用户提供 `新算法接入/算法三/SARIMA+RHO滚动时域_实时动态修正完整解决方案.docx`，已同步转成同名 `.md` 便于上传）：①新增 `src/parking_opt/strategies/rho.py`（在线策略，`rho_rolling`）——预测前置规划 + 滚动窗口动态纠偏 + 实时事件兜底：每 10 分钟滚动校验、60 分钟预测窗口，按窗口累计偏差 `E=|A−F|/F` 分三级修正（≤20% 保持基准方案 / 20%~50% 按实际偏高偏低切换高负载或低负载算法 / >50% 或 5 分钟进场突发降级纯实时兜底，连续 2 个步长回归后自动恢复）；②新增 `_rho_forecast.py` 免依赖 SARIMA-lite 预测器（Holt 水平/趋势 + AR(1) 误差修正，生产环境可替换 statsmodels SARIMA，不新增任何依赖）；③登记注册表后网页自动出现「RHO 滚动时域动态修正」及 9 个参数控件（滚动步长/预测窗口/两级阈值/突发阈值/基准·偏高·偏低·兜底四个子算法下拉）；④信息边界：在线合法——不实现 prepare、不读未来需求与真实停车时长；⑤新增 `tests/test_rho.py`（19 项）、教学文档 `docs/algorithms/rho_rolling.md`、实验脚本 `scripts/exp_rho.py`（产出 `outputs/exp_rho_*`）；pytest 179 passed、行数检查与启动包自检全绿；打 tag `backup-before-rho-algo3-20260904`；状态文档 status_version 77 → 78；待用户网页验收；
- 2026-09-03：**custom 用户刷新后权限回退修复**（用户反馈：刷新一下权限变少了）：根因是 `restore_session()` 恢复会话时没有把 `validate_session` 返回的 `permissions` 带回 session_state——登录路径带上了、刷新恢复路径漏了，刷新后 `st.session_state.permissions=None`，`resolve_role("custom", None)` 回退到 custom 默认（6 板块 + 操作员功能）；修复：`src/auth/session.py` 的 `restore_session` 返回值增加 `permissions`；新增回归测试 1 项（恢复会话必须带回 permissions），pytest 160 passed、行数检查与启动包自检全绿；打 tag `backup-before-restore-permissions-fix-20260903`；状态文档 status_version 76 → 77；
- 2026-09-02：**回放路径假直线与内置布局单向边修复**（用户反馈：离场动画彻底没了，判断「路是单向的」——完全正确）：①核验发现内置布局 `linear`（ENTRY→N0）、`rectangle`（ENTRY→M）、`circle`（ENTRY→R0）三处入口边只加了单方向，车位全部「能进不能出」，离场路径 `spot→entry` 不存在；旧 UI 因此画 `[车位,入口]` 假直线（用户上一轮看到的穿墙线），禁止假直线后动画消失；②补齐三处反向边（`N0→ENTRY`、`M→ENTRY`、`R0→ENTRY`），全部内置布局现在每个车位都能返回入口；③`vehicle_phases.py` 回放路径兜底统一改为「找不到路按引擎口径回退入口，再找不到只标起点不画假直线」（离场/入库/移位/回位/让行全量覆盖）；④新增回归测试（`tests/test_builtin_layouts.py`：全部内置布局双向连通；不可达出口/入口回退测试 2 项），pytest 159 passed、行数检查与启动包自检全绿；状态文档 status_version 75 → 76；
- 2026-09-02：**动态路径移位修复**（用户反馈：移位车的离场路径起点仍是移位前车位，且看不到回位段）：①`src/ui/common/vehicle_phases.py` 新增 `_spot_at_time`——按事件流重放车辆实际车位（shift_start 跟随 to_spot、shift_end 跟随 final_spot/原车位），离场段路径与 `spot_id` 改用该实际车位；②移位阶段新增「回位段」（shift_end 存在时生成 缓冲位→回位目标 的可选动画，kind=return，页面下拉标注「（回位）」）；③`ParkingLot.move_vehicle` 同步 `vehicle.assigned_spot`、`free` 释放缓冲位占用（修复前移归位后引擎离场用错车位的隐患）；新增回归测试 3 项（离场起点=移位后车位、回位段提取、assigned_spot/缓冲位同步），pytest 156 passed、行数检查与启动包自检全绿；打 tag `backup-before-departure-shift-path-20260902`；状态文档 status_version 74 → 75；
- 2026-09-02：交接后恢复会话（新对话）：本地三项自检全绿（pytest 154 passed / `scripts/check_file_lines.py` 全部 ≤200 行 / 启动包自检 260 关键文件）；Supabase 只读核验权限迁移已生效（7 用户：admin 1 / operator 4 / custom 1 / viewer 1；`users.permissions` 列存在；`app_settings.custom_sections` 模板为 9 板块 + 13 功能开；login_user / validate_session / list_users / update_user_role / get_custom_sections / save_custom_sections 六个 RPC 均返回预期 JSON，无 PGRST202）；确认 `stage-d-deliver` HEAD `bf96976` 已推送到 origin；清理状态文档中过期的「迁移 13 待执行」提示（迁移 13/14 已直连执行）；打 tag `backup-before-status-sync-perm-accept-20260902`；状态文档 status_version 73 → 74；
- 2026-09-02：**用户验收通过**「🗑 删除该任务」刷新后删除场景（提交 `fb90a6b`）：下发任务 → F5 刷新 → 删除按钮自动定位最近任务并成功叫停。至此 💻 本地计算全链路、📂 载入最近一次结果、🗑 删除任务（含刷新后叫停）、📦 操作员本地计算包全部公网验收通过；验收前打 tag `backup-before-delete-button-accept-20260902`；状态文档 status_version 62 → 63；
- 2026-09-02：**删除任务按钮刷新后失效修复 + 本地计算公网验收通过**（用户反馈：刷新页面后 pending 任务在网页上「消失」、🗑 删除按钮因 session 丢失 task_id 失效，任务实际仍在队列里被 worker 继续领取；另报：222 账号完成一次简单运算，内置布局约 200 车位，正常看到指标）：①新增 `migrations/12_latest_task_any.sql` 并已直连 Supabase 执行——`get_latest_compute_task_any` RPC 返回该用户最近一条任务（任意状态，按 created_at DESC）；②`src/auth.py` 增加封装（走只读 RPC 重试通道）、`src/ui/common.py` 容错导入；③`src/ui/pages.py` 新增模块级纯函数 `_resolve_delete_task_id`（优先 session task_id，刷新丢失后自动定位最近任务），`_delete_local_task_with_confirm` 改为不依赖 session——二次确认显示任务 id 前 8 位 + 状态（排队中/计算中/已完成/失败），无任务时按钮置灰；④「🔄 检查本地计算结果」与按钮区 caption 提示同步说明刷新后找回/叫停方式。新增测试 4 项，pytest 143 passed、自检通过（171 关键文件）；状态文档 status_version 61 → 62；待用户公网验收「刷新后删除」场景；
- 2026-09-02：**操作员启动脚本增加依赖安装诊断**（操作员反馈依赖安装仍失败，需要定位原因）：`_worker_operator_bat()` 安装前打印 `py --version` 与 Python 位数（ortools 无 32 位 wheel，32 位 Python 必失败并明确提示重装 64 位），并先 `pip install --upgrade pip`（清华镜像）解决老版本 pip 解析失败；失败提示改为引导用户把「Python 位数」起的完整内容发管理员。zip 包版本号 +1（v3），避免缓存旧包。pytest 139 passed；状态文档 status_version 60 → 61；待操作员重新下载 zip 复测；
- 2026-09-02：**操作员包依赖安装改清华镜像优先**（操作员反馈：装精简依赖报「检查网络再试」，开 VPN 也没用——pip 默认不走 VPN 的浏览器代理，命令行需单独配代理）：`_worker_operator_bat()` 改为优先 `-i https://pypi.tuna.tsinghua.edu.cn/simple`（国内直连，无需 VPN，`--timeout 60 --retries 5`），失败自动回退官方源并提示（VPN 需全局/TUN 模式；Python 版本建议 3.10~3.12）。同时 `_WORKER_PACKAGE_VERSION = "2"` 加入 zip 缓存 key，避免公网用户下载到 1 小时缓存里的旧包。pytest 139 passed；状态文档 status_version 59 → 60；待操作员重新下载 zip 验证；
- 2026-09-02：**修复操作员包下载报错「Error: not connected to a server!」**（操作员账号点击 zip 下载时报错）：根因是 `st.download_button` 传 bytes 数据时，前端点击要向服务器请求下载地址，WebSocket 断开/闪断即报该错（前两个 bat 按钮传字符串走浏览器 data URL 所以正常）。修复：`src/ui/pages.py` 新增 `_worker_package_data_url()`——把 zip 转为 `data:application/zip;base64,...` 数据 URL，并用 `st.link_button` 下载（浏览器本地直接下载，不再依赖服务器连接）；同时 `_cached_worker_package_bytes`（st.cache_data，ttl 1h）避免每次渲染重复读文件压缩。pytest 139 passed、自检通过（170 关键文件）；状态文档 status_version 58 → 59；待用户在公网 app 验收；
- 2026-09-02：**本地计算任务删除/叫停**（用户反馈：下发错了没法叫停删除）：①新增 `migrations/11_delete_compute_task.sql` 并已直连 Supabase 执行——`delete_compute_task` RPC（任务 owner 可删除任意状态任务）；②`src/auth.py` 增加 `delete_compute_task` 封装、`src/ui/common.py` 容错导入；③`src/ui/pages.py` 新增 `_delete_local_task_with_confirm`（二次确认），「💻 本地计算」区按钮改为三列：🔄 检查 / 📂 载入最近一次 / 🗑 删除该任务；本地计算模式说明与 120 秒轮询提示同步写明「下发错了刷新页面后点删除即可叫停」；④`local_worker.py` 回传时检查 complete 返回值——任务已被删除则打印「丢弃本次结果」，不再误报完成。已验证：create→delete→get 任务不存在全链路成功。pytest 138 passed；状态文档 status_version 57 → 58；待用户在公网 app 验收；
- 2026-09-02：**操作员本地计算包（zip）+ worker 依赖解耦**（用户疑问：其他操作员用自己电脑能否本地计算——此前「一键启动脚本」依赖项目根目录/credentials/secrets，操作员电脑无法使用）：①新增 `src/local_compute.py` 纯函数模块（布局构建 `LAYOUT_BUILDERS`/`build_layout_from_json`、`run_single`/`_avg_metrics`、`_vehicle_to_dict`），不依赖 Streamlit/Pandas/Plotly；`src/ui/common.py` 改为从该模块 re-export（删除原实现，UI 行为不变）；②`local_worker.py` 改从 `local_compute` 导入（依赖链精简为 supabase/httpx/networkx/simpy/ortools）；③`local_worker.py` 新增操作员友好配置：`worker_config.toml`（与 worker 同级）读取 Supabase 配置、`worker_credentials.json` 交互登录缓存（首次双击输入自己账号密码，验证成功后缓存，下次免输入）；④`src/ui/pages.py` 新增 `_worker_package_bytes` 生成操作员 zip 包（local_worker.py + src/local_compute.py + src/parking_opt/ 全部 28 个 .py + requirements_worker.txt + 操作员版 start_local_worker.bat + worker_config.toml），「💻 本地计算」区新增「📦 下载操作员本地计算包（zip）」按钮。已验证：zip 内容完整、解耦后 `run_local_task` 端到端正常（13 指标/80 事件）、worker 依赖链无界面库。pytest 137 passed、自检通过（169 关键文件）；状态文档 status_version 56 → 57；待用户在公网 app 验收；
- 2026-09-02：**本地计算结果找回按钮「📂 载入最近一次结果」**（用户反馈：本地任务跑完 9000+s 后，浏览器 session 丢失 task_id，网页端无法查看已完成结果）：①新增 `migrations/10_latest_task_load.sql` 并已直连 Supabase 执行——`get_latest_compute_task` RPC 返回该用户最近一条 done 任务（含 payload+result）；②`src/auth.py` 增加 `get_latest_compute_task` 封装（走只读 RPC 重试通道）；③`src/ui/common.py` 新增 `build_local_task_context(payload)` 纯函数——从任务 payload 完整重建布局（内置/真实）/需求/策略/引擎参数与 PathEngine 上下文；④`src/ui/pages.py` 重构出 `_apply_sim_state`（本地结果载入与历史结果载入共用），「💻 本地计算」区新增「📂 载入最近一次结果」按钮（不再依赖 session 里的 local_task_id，刷新/重开浏览器/换电脑均可用）；⑤真实 1000 车任务结果已存档 `data/local_task_results/task_b1422967_20260902.json`（payload+result，目录已 gitignore）。已用真实 1000 车/400 车位任务验证 RPC 返回与上下文重建成功。pytest 133 passed、自检通过（168 关键文件）；状态文档 status_version 55 → 56；待用户在公网 app 验收；
- 2026-09-01：**worker 逐次进度打印（随机分配等多次策略）**（用户要求：能看到随机分配 100 次跑到第几次才安心）：`local_worker.py` 在「全部对比」与单策略模式下，对需要跑多次的策略（如 random 100 次）每 10 次打印一次 `    ├─ 随机分配：第 10/100 次…`，总次数 ≤10 时逐次打印（flush=True）；磁盘上的 local_worker.py 已是最新（提交 `940466d` 已推送）。pytest 129 passed、自检通过（165 关键文件）；状态文档 status_version 54 → 55；
- 2026-09-01：**worker 算法进度打印**（用户问：本地运行到第几个算法了叫什么）：此前 worker 只在领取任务和整体完成时打日志，compare_all 模式看不到中间进度。修复：`local_worker.py` 在「全部对比」每个策略开始前打印 `[⚙️] 算法 i/N：{显示名}（{name}）…`（flush=True 实时输出），单策略模式打印 `[⚙️] 运行策略：{显示名}…`；下次运行在本地 worker 窗口即可直接看到第几个、叫什么。pytest 129 passed、自检通过（165 关键文件）；状态文档 status_version 53 → 54；
- 2026-09-01：**本地计算任务自愈 + 轮询提示修复**（用户反馈：①秒数到 100 左右状态就消失、不跳转；②worker 已关但任务卡在 running）：①轮询 120 秒结束后的提示此前被 `st.rerun()` 立即清掉——改为写入 `status_box` 后用 `st.stop()` 停留在当前页面，提示不再消失；②新增 `migrations/09_task_requeue.sql` 并已直连 Supabase 执行——`requeue_compute_task` RPC（任务 owner 可把 running 任务重新置为 pending）+ `claim_compute_task` 领取前自动把卡住超过 15 分钟的 running 任务重置为 pending；③`src/auth.py`/`src/ui/common.py` 增加 requeue 封装；④网页「🔄 检查本地计算结果」遇到 running 时显示「♻️ 重新排队该任务」按钮（worker 被关后一键恢复）。已验证：create → claim(running) → requeue(pending) → 重新 claim → complete 全链路成功。pytest 129 passed、自检通过（165 关键文件）；状态文档 status_version 52 → 53；待用户在公网 app 验收；
- 2026-09-01：**worker 独立登录态（修复「登录态失效」互踢）**（用户反馈：过一会儿本地 worker 就报登录态失效）：根因是网页与 local_worker 共用 users 表单个 `session_token`，谁后登录谁把前一个顶掉，两边互相踢。修复：新增 `migrations/08_worker_token.sql` 并已直连 Supabase 执行——`users` 表增加 `worker_token`/`worker_expires` 独立列；新增 `login_worker` RPC（worker 专用登录，只更新 worker token，不动网页 session）；计算任务 4 个 RPC（create/claim/complete/get）改为「网页 session token 或 worker token 任一有效即可」；`local_worker.py` 改调 `login_worker`。已验证：worker 登录后网页 session_token 保持不变；create/claim/complete/get 用 worker token 全链路成功。pytest 129 passed、自检通过（164 关键文件）；状态文档 status_version 51 → 52；待用户在公网 app 验收；
- 2026-09-01：**公网 app RPC 网络自愈（修复网页端 10053）**（用户反馈：10053 报错其实出现在网页端）：`src/auth.py` 新增 `_rpc_with_retry`——只读/幂等 RPC（`validate_session`/`get_preference`/`get_compute_task`）遇到瞬时网络错误（httpx 传输错误 / ConnectionError / OSError）自动退避重试（默认 4 次、1.0s 起指数退避）并重建 `_supabase` 连接池，非瞬时错误仍按原契约返回错误 dict；本地计算轮询（`_submit_local_task_and_wait`/`_check_local_task_once`）因此不再被偶发 10053 打断；新增 `tests/test_auth_net.py`（3 项）。pytest 129 passed、自检通过（163 关键文件）；状态文档 status_version 50 → 51；待用户在公网 app 验收；
- 2026-09-01：**local_worker 网络抖动自愈（修复「循环异常 10053」）**（用户反馈：本地 worker 报循环异常 10053）：公网到 Supabase 的连接可能被代理/负载均衡器重置（WinError 10053=已建立的连接被主机软件中断），此前 worker 只做最外层重试，`complete_compute_task` 一旦失败任务会卡在 running。修复：新增 `_SupabaseClient` 封装——所有 RPC（login/claim/complete）遇到瞬时网络错误（httpx 传输错误 / ConnectionError / OSError）自动退避重试（默认 4 次、1.5s 起指数退避）并重建底层连接池，避免刷屏和任务卡死；新增 `_is_transient_net` 识别瞬时错误；`tests/test_local_worker.py` 新增 2 项测试（1→3 项）。重新端到端验证：create → GBK stdout 下 worker 领取并计算 → complete → done（main_events 89 条、metrics 13 项齐全）。pytest 126 passed、自检通过（162 关键文件）；状态文档 status_version 49 → 50；待用户在公网 app 验收；
- 2026-09-01：**本地计算 worker 一键启动脚本（公网网页下载）**（用户反馈：不想自己手动运行 `py local_worker.py`，希望点「本地计算」后第一步就自动打开 worker；公网 Cloud 网页受浏览器安全限制，无法在用户电脑上自动开进程，改为提供最接近「自动」的两步方案）：仿真设置页「💻 本地计算」模式新增两个下载按钮——`start_local_worker.bat`（保存到项目根目录双击即启动 worker）、`install_local_worker_autostart.bat`（双击一次注册 Windows 登录自启 `ParkingOptLocalWorker` 计划任务，以后每次开机自动后台运行 worker，彻底免手动）；下发失败提示同步改为引用启动脚本；新增 `_worker_bat()` 与 2 项测试（`tests/test_ui_helpers.py` 3→5 项）。pytest 124 passed、自检通过（161 关键文件）；状态文档 status_version 48 → 49；待用户在公网 app 验收；
- 2026-09-01：**修复 local_worker.py Windows GBK 输出崩溃 + 本地计算后端全链路验证**：验收时发现 `py local_worker.py` 在 Windows GBK（cp936）控制台/重定向输出下打印 `✓` 触发 `UnicodeEncodeError` 直接崩溃（会话开头失败日志即此因）。修复：模块导入时对 stdout/stderr 设置 `errors="replace"`（保持终端编码不变，中文正常显示，符号降级 `?`，不再崩溃）；新增回归测试 `tests/test_local_worker.py`（GBK 子进程打印 ✓ 不崩溃）。随后完成本地计算后端全链路验证：`create_compute_task` 下发（duration_greedy / linear 15 车位 / 20 车 / seed 42）→ `py local_worker.py`（GBK stdout 下）领取并计算 → `complete_compute_task` 回写 → `get_compute_task` 确认 status=done、metrics 13 项齐全、main_events 85 条。pytest 122 passed、自检通过（161 关键文件）；打 tag `backup-before-worker-gbk-fix-20260901`；状态文档 status_version 47 → 48；待用户在公网 app 浏览器侧验收 UI 流程；
- 2026-09-01：**执行 07 迁移**：`migrations/07_compute_tasks.sql` 已通过 Session pooler 直连 Supabase 执行，验证 `compute_tasks` 表存在、4 个任务 RPC（create/claim/complete/get）创建成功；`credentials.db.txt` 已就位（gitignore 覆盖，注意密码字段勿保留方括号）。打 tag `backup-before-migration07-executed-20260901`；状态文档 status_version 46 → 47；下一步验收本地计算全链路；
- 2026-09-01：**新增「本地计算」能力（云 UI + 本机 worker + Supabase 任务队列）**（用户需求：点一下切换为本地 CPU 计算，云端的程序、本地的算力）：①新增 `migrations/07_compute_tasks.sql`（`compute_tasks` 表 + create/claim/complete/get 四个 SECURITY DEFINER RPC，均带 search_path 加固）；②`src/auth.py` 增加 4 个任务 RPC 封装；③`src/ui/common.py` 增加计算位置偏好 `compute_mode_v1`（cloud/local，登录/恢复会话自动加载）、`_vehicle_to_dict`/`vehicles_from_dicts` 序列化助手；④新增 `local_worker.py`（本机运行，登录后轮询领任务、用本机 CPU 跑 `run_local_task`、结果回传）；⑤仿真设置页新增「计算位置」切换（☁️ 云端 / 💻 本地），本地模式下「运行仿真」改为下发任务并轮询状态（最多 2 分钟），完成后自动载入结果并跳指标页，另有「🔄 检查本地计算结果」按钮；worker 端到端小任务验证通过（compare_all 9 策略、main_events 120 条、cpsat_rate=1.0）。pytest 121 passed、启动包自检通过；打 tag `backup-before-local-worker-20260901`；状态文档 status_version 45 → 46；待用户执行迁移后验收；
- 2026-09-01：**公网云端大参数崩溃兜底**（用户反馈数目一大网站就崩溃，想要「本地计算」方案）：①全部对比每个种子的 `run_single` 加 try/except——单个策略崩溃（OOM/异常）记入 `sim_failed_strategies` 并跳过，其余策略照常对比；②单策略模式失败时显示友好错误 + 云端环境提示改本地运行，不再白屏崩溃；③指标分析页展示「运行失败策略」错误列表；④仿真设置页在公网云端（非本地桌面）且车辆 ≥500 或车位 ≥200 时提前提示「大参数建议本地计算 `py -m streamlit run app.py`（本机计算，云端只存数据）」。pytest 121 passed、启动包自检通过；打 tag `backup-before-cloud-crash-guard-20260901`；状态文档 status_version 44 → 45；待用户在公网 app 验收；
- 2026-09-01：**用户验收通过**布局恢复修复（提交 `e00648f`，公网 app 确认「现在有布局了」）；验收 tag `backup-before-layout-restore-accept-20260901`；状态文档 status_version 43 → 44；阶段 D 继续，等待下一项优化需求；
- 2026-09-01：**修复导入布局「不持久」**（用户反馈每次都要重新导入）：诊断确认布局 JSON 已正确存在 Supabase `custom_layouts_v1`（海仑宾馆停车场 27 车位、恒基地下停车库 152 车位，均可被当前代码重建），但 `restore_custom_layouts()` 把所有异常静默吞掉，网络抖动/限流时布局加载失败且无任何提示。修复：①恢复改为 3 次重试（0.6/1.2/1.8s 退避）；②新增 `ensure_custom_layouts_loaded()`——仿真设置/布局图/导入布局页渲染前若 `custom_layouts` 缺失且有 token 就自动重试恢复（失败后 30 秒节流，避免每个控件交互都打后端）；③恢复失败不再无声：记录 `layout_restore_error`，导入布局页显示警告 + 「🔄 重试加载云端布局」按钮；④退出登录清空相关恢复状态。pytest 121 passed、启动包自检通过、AppTest 登录与 token 恢复两路径验证布局均加载；打 tag `backup-before-layout-restore-hardening-20260901`；状态文档 status_version 42 → 43；待用户在公网 app 验收；
- 2026-08-31：**修正 60 秒语义（用户澄清：不是选 ≤60 秒展示，而是全部展示 + 可选隐藏 >60 秒）**：「全部对比」与单策略模式都**不再因超时 break 或 st.stop**——所有种子照常跑完、结果全部取平均展示，60 秒只把该策略标记进 `sim_timed_out_strategies`；指标分析页提示改为「有种子单次运行超过 60 秒（结果仍全部展示）」，仅全部对比模式显示「隐藏超时策略」勾选框（勾选后含超时种子的策略不参与排名/表格/图表与需求时序切换）；进度条文案改为「超过 60 秒仅标记」。pytest 121 passed、启动包自检通过；打 tag `backup-before-timeout-mark-only-20260831`；状态文档 status_version 41 → 42；待用户在公网 app 验收；
- 2026-08-31：**调整 60 秒熔断语义（用户反馈：先跑再选 ≤60 秒的种子，结果都展示，可选隐藏超时策略）**：「全部对比」循环不再因某个种子超时就把整个策略从结果中剔除——超时种子舍弃，只要有 ≤60 秒的种子就按已完成种子取平均参与对比（所有种子都超时则无数据不参与对比）；指标分析页超时提示改为「超时种子已舍弃、其余种子参与对比」，并新增「隐藏超时策略」勾选框（勾选后含超时种子的策略不参与排名/表格/图表与需求时序策略切换，全部被隐藏时给出提示）；`STRATEGY_TIME_BUDGET` 注释同步更新。pytest 121 passed、启动包自检通过；打 tag `backup-before-timeout-show-all-20260831`；状态文档 status_version 40 → 41；待用户在公网 app 验收；
- 2026-08-31：**修复动态路径页 TypeError**（线上报错，页面 line 830 `sorted(set(...))`）：①`sim_events_raw` 可能为 None（「全部对比」主方法首种子超时被跳过时无事件日志），页面直接迭代 None 崩溃——动态路径页增加空事件日志守卫（提示回设置页重跑），全部对比主方法无事件时回退到第一个成功策略的事件；②车辆 ID 排序键在「含 `_` 数字后缀 ID」与「无 `_` ID」混用时返回 int/str 混合，`sorted` 比较崩溃——新增 `_vehicle_sort_key` 返回同构 `(int, int, str)` 元组（带下划线按末尾数字、否则字典序，后缀非数字回退）。新增 `tests/test_ui_helpers.py`（3 项），pytest 118 → 121 passed、启动包自检通过（157 文件）；打 tag `backup-before-path-page-typeerror-20260831`；状态文档 status_version 39 → 40；待用户在公网 app 验收；
- 2026-08-31：**修复场景 B 入库让行竞态崩溃**（线上 AssertionError）：阻挡车移位去缓冲位的 `_reserve_drive` yield 期间，其自身离场进程可能释放原车位，随后 `move_vehicle(blk_spot, buffer)` 对空车位断言失败。修复：①场景 B 移位行驶后重新校验 `blk_spot.occupied_by == blk_vid`，已离场则跳过本次移位并释放缓冲位；②场景 A/B 均增加「缓冲位在行驶期间被占用则放弃移位」防御（记 BUFFER_FAILED）；③`ParkingLot.get_available_spots` 不再返回已征用的缓冲位，杜绝等待车辆抢占缓冲位。新增回归测试 2 项（确定性复现场景 B 竞态 + 缓冲位排除），pytest 116 → 118 passed、启动包自检通过（157 文件）；打 tag `backup-before-scene-b-shift-race-20260831`；状态文档 status_version 38 → 39；待用户在公网 app 验收；
- 2026-08-30：**random 策略重复次数独立控制（≥100）**：仿真设置页在策略为 random 或全部对比时新增「random 策略重复次数（≥100，默认 100，上限 1000）」数字输入框，random 单独按该次数取平均，其余策略仍用「仿真次数」滑杆（1~10）；全部对比进度条与指标分析页说明会标注 random 的独立次数。pytest 116 passed；状态文档 status_version 37 → 38；待用户验收；
- 2026-08-30：**真实道闸流水导入区新增说明与示例下载**（用户反馈网页里看不到说明文档）：「导入真实道闸流水 CSV」区域新增「📥 下载道闸流水示例 CSV」按钮（读取 `data/samples/道闸流水示例.csv`）与「📖 填写说明」折叠区（列名表/时间格式/示例/常见错误），与仓库文档 `docs/道闸流水CSV填写说明.md` 一致。pytest 116 passed；状态文档 status_version 36 → 37；待用户验收；
- 2026-08-30：**每个种子限时 60 秒，超时跳过并在结果注明**（用户澄清口径为「每个种子」）：`common.py` 新增 `STRATEGY_TIME_BUDGET=60`；「全部对比」每个种子的 run_single 单独计时，单次超过 60 秒即跳过该策略并计入 `sim_timed_out_strategies`，指标分析页顶部黄色警告列出被跳过策略；单策略模式同样处理（提示并停止、结果不保存）；MOSA prepare 预算 120s→45s（保证 MOSA 单次仿真不超 60 秒）。pytest 116 passed；状态文档 status_version 35 → 36；待用户验收；
- 2026-08-30：**取消规模保护 + 车位数上限 50→500**（按用户要求大车位数下所有算法照跑）：CP-SAT 移除「>40 车位/>120 车跳过」，改为时间熔断（模型构建 20s + 求解 10s，超时返回 None=无理论最优对照）；MOSA 移除「>60 车位/>120 车回退贪心」，改为 prepare 时间熔断 120s（任意规模进化，超时返回当前种群最优方案，不回退）；车位数控件改数字输入框 5~500。pytest 116 passed；状态文档 status_version 34 → 35；待用户验收；
- 2026-08-30：**车辆数上限 200→2000 并改为数字输入框**（小数值用步进、大数值直接输入；CP-SAT 与 MOSA 已有规模保护自动回退贪心，不会卡死）；
- 2026-08-30：**排名噪声修复**（提交待记）：用户发现「运行耗时」权重即使很低，random 策略也常排第一——根因是 min–max 归一化把微小耗时差异放大为 1/0 两个极端。修复：`ranking.py` 新增 `SIGNIFICANCE_EPSILON` 实际意义阈值（耗时差 <1s、满足率/利用率差 <0.5pp、等待差 <30s、移位距离差 <20m、行驶距离差 <50m 均视为无区分度，归一化记 0.5 不参与排名）；指标分析页加权模式显示被中和的指标提示；新增 3 项测试。pytest 116 passed；状态文档 status_version 32 → 33；待用户验收；
- 2026-08-30：**企业可用化收尾**（提交 `1952d75`、本轮提交）：①修复公网真实道闸导入区 `session_state=None` 崩溃；②代码移除旧 key 兜底默认值（密钥强制走 secrets/环境变量，未配置时明确报错）；③历史运行页新增「⚖️ 两次运行对比」（8 项指标差异表 + 五维雷达图）；④新增 `docs/道闸流水CSV填写说明.md`（给停车场运营方）与 `data/samples/道闸流水示例.csv`；⑤新增 `docs/企业可用性检查清单.md`（运营方/研发/安全三方自检）；⑥迁移文件 search_path 修复为 `public, extensions`（修复线上 crypt 不可见）。pytest 113 passed、自检通过；状态文档 status_version 31 → 32；待用户验收；
- 2026-08-30：**企业可用化四阶段改造**（提交 `bdd59f2`/`b84faa6`/`f8ec680`/`3112a3e`）：①安全与合规——bcrypt 密码哈希（旧 sha256 登录透明升级）、Supabase 密钥改走 st.secrets/环境变量、session token 改 Cookie 优先（URL 兜底自愈清理）、新增 `audit_log` 审计日志（登录/角色/反馈/仿真运行）、全部 RPC 补 `SET search_path`；②数据沉淀——新增 `sim_runs` 运行记录表与「📜 历史运行」页（跨会话/跨用户对比、CSV 导出、删除）；③部署运维——Dockerfile/docker-compose/nginx HTTPS 示例/密钥模板/`docs/部署运维说明.md`；④真实数据接口预留——`realtime_io.py` 道闸流水/车位状态解析 + `docs/data/03_真实数据接口规范_v1.md` + 仿真设置页新增「导入真实道闸流水 CSV」演示。pytest 113 passed、自检通过；状态文档 status_version 30 → 31；待用户验收；
- 2026-08-30：**新增项目目录索引 `PROJECT_INDEX.md`**（全文件导航 + 需求→文件速查表，供按需读取、避免全量加载上下文）；`PROJECT_STATUS.md` 关键文件表登记该索引；打 tag `backup-before-project-index-20260830`；状态文档 status_version 29 → 30；待用户确认；
- 2026-08-28：**用户验收通过**反馈按修改后显示时间自动排序 + 正序/倒序切换（提交 `d1b25ab`、`a45b537`）；验收前打 tag `backup-before-feedback-sort-accept-20260828`；状态文档 status_version 28 → 29；今日收工，明日继续；
- 2026-08-28：**反馈页新增正序/倒序切换**（用户反馈：增加倒序按钮）：`render_feedback_page` 顶部新增「反馈排序」radio（正序 早→晚 / 倒序 晚→早），「我的反馈」「管理员全部反馈」与 CSV 导出统一跟随选择；`sort_feedbacks` 增加 `reverse` 参数，相关渲染函数透传；pytest 103 passed、AppTest 反馈页通过；打 tag `backup-before-feedback-sort-desc-20260828`；状态文档 status_version 27 → 28；待用户验收；
- 2026-08-28：**反馈按修改后显示时间自动排序**（用户反馈：反馈要按修改后的时间顺序排列，改时间后自动按新顺序排）：`pages.py` 新增 `_parse_feedback_time`/`_feedback_sort_key`/`sort_feedbacks`（显示时间优先、回退创建时间、无法解析排最后，升序）；「我的反馈」「管理员全部反馈」列表与 CSV 导出统一使用该排序；管理员修改显示时间保存后 `st.rerun` 重新拉取并自动重排；pytest 103 passed、自检通过（139 文件）、AppTest 反馈页通过；打 tag `backup-before-feedback-time-sort-20260828`；状态文档 status_version 26 → 27；待用户验收；
- 2026-08-28：**用户验收通过**布局图「内置/真实布局」回显与指标分析「选择要查看的策略」两项反馈修复（提交 `ee52637`）；验收前打 tag `backup-before-layout-metrics-follow-accept-20260828`；状态文档 status_version 25 → 26；阶段 D 继续，等待用户提出下一项优化需求；
- 2026-08-28：**布局图 + 指标分析两项反馈修复**（用户反馈：①布局图「仿真布局」改名「内置布局」，且点内置/真实要分别回显最近一次仿真的内置/真实布局；②指标分析页需求时序分布与车辆明细应跟随所选策略，全部对比时提供策略选择控件）：`render_settings` 运行后记录 `last_builtin_sim`/`last_real_sim`；`render_layout_page` 视图模式改为「内置布局/真实布局」，按选择回显对应最近一次仿真布局；「全部对比」运行循环为每个策略保留第一个种子的事件日志与车辆列表（`sim_events_by_strategy`/`sim_vehicles_by_strategy`），指标页新增「选择要查看的策略」下拉切换需求时序与车辆明细（默认时长感知贪心），单策略模式行为不变；pytest 103 passed、自检通过（139 文件）、AppTest 两页通过；打 tag `backup-before-layout-metrics-follow-20260828`；状态文档 status_version 24 → 25；待用户验收；
- 2026-08-28：**用户验收通过**动态路径页反馈修复（提交 `a770411`）与移位车辆表（提交 `39936c9`）；验收前打 tag `backup-before-dynamic-path-feedback-accept-20260828`；状态文档 status_version 23 → 24；阶段 D 继续，等待用户提出下一项优化需求；
- 2026-08-28：**动态路径页增补移位车辆表**（用户反馈：移位车较少，演示移位需要知道哪些车移位）：页面在车辆选择区新增「🔄 移位车辆表」折叠区，列出全部 `shift_start` 事件（移位车辆/开始时间/从车位/到车位(缓冲)/让行对象/原因/回位时间）；「② 选择车辆」下拉对移位车加「🔄移位」标记；pytest 103 passed、自检通过、UI 模块导入正常；打 tag `backup-before-shift-table-20260828`；待用户验收；
- 2026-08-28：**动态路径页反馈修复**（用户验收多入口多出口后反馈三问题，ExecPlan `docs/plans/stage-d-dynamic-path-feedback.md`）：①入库黄色虚线改为按该车实际入口（`spot_entry.entry` 元数据，不再写死默认入口）；②动态路径页新增「③ 选择回放阶段」（入库/离场/移位），离场动画展示车位→出口过程，移位动画展示移位车 from→to 轨迹；③离场阶段的让行移位轨迹以辅助虚线绘制；`common.py` 新增 `build_vehicle_phases`/`interp_path_segment`，`viz.py` 新增 `highlight_path_color`/`extra_paths`，引擎有阻挡 DEPARTURE 事件补 `exit` 元数据；新增 2 项测试，pytest 103 passed、自检通过（139 文件）、UI 模块导入正常；打 tag `backup-before-dynamic-path-feedback-20260828`；待用户验收；
- 2026-08-28：**多入口多出口改造验收通过**（用户确认其余内容可验收，动态路径三问题转入反馈修复）：布局允许多个 `type="entry"`/`type="exit"` 节点（旧单入口文件兼容）；`Vehicle` 增 `entry_id`/`exit_id`；`PathEngine` 支持多入口/多出口与默认口规则（`ENTRY`/`EXIT` 优先，无出口回退入口）；`generate_demand` 用 seed 派生独立随机流（+100003/+200003）等概率分配每车入口与出口（不污染主随机流，旧单口实验完全可复现）；引擎入库按车辆入口、离场按车辆出口、出口不可达回退入口并记 DEGRADATION；SPOT_ENTRY/DEPARTURE 事件带 entry/exit 元数据；四个策略距离语义改为「该车入口」；需求 JSON 可选 `entry_id`/`exit_id`（schema 仍 v1）；导入校验放宽为至少一个入口；viz 渲染全部入口（三角）与出口（倒三角）；新增 `tests/test_multi_entry.py`（10 项），pytest 101 passed、自检通过（138 文件）；打 tag `backup-before-multi-entry-exit-20260828`；
- 2026-08-28：**用户验收通过**算法二 risk_scoring「风险感知多准则评分」（提交 `dc1a7f8`）与反馈显示时间提示清理（提交 `bf82cdc`）；打 tag `backup-before-risk-scoring-accept-20260828`；状态文档 status_version 20 → 21；阶段 D 继续，等待用户提出下一项优化需求；
- 2026-08-27：**算法二 risk_scoring 接入**（用户提供 `新算法接入/算法二` 快照，本会话并入 `stage-d-deliver`，主干其它内容全部保留）：新增 `src/parking_opt/strategies/risk_scoring.py`（在线「风险感知多准则评分」，候选车位内 min–max 归一化后加权 `C = w_d·距离 + w_r·预期移位风险 + w_p·结构惩罚`，argmin 选位，不读真实停车时长），登记注册表网页自动出现 3 个权重滑杆（默认 1.0/1.5/0.5）；并入 18 项单元测试、教学文档 `docs/algorithms/risk_scoring.md`、实验脚本 `scripts/exp_risk_scoring.py`（本地产出 `outputs/exp_risk_scoring_*`）、4 条新文献（bib + 文献矩阵 §11）；**修复实验暴露的引擎移位让行并发竞态**——回位 `move_vehicle` 前后加防御检查（缓冲位若已被其它进程移走则跳过回位），新增 `tests/test_engine_shift_race.py`（2 项）；实验按当前引擎重跑，文档 §11 数字与默认权重选取理由如实改写（默认保持 1.0/1.5/0.5：均值移位 0.2 次、行驶 5588m，比严格零移位组合少 92m）；pytest 91 passed、自检通过；打 tag `backup-before-risk-scoring-20260827`；待用户验收；
- 2026-08-27：反馈显示时间提示清理（用户验收后反馈）：管理员反馈列表时间行删除「（原始：…）」提示，状态由英文 pending/resolved 改为中文「待处理/已处理」；✎ 编辑面板删除「恢复原始」按钮，仅保留「保存 / 取消」；输入框占位提示不再回显原始时间（placeholder 固定为示例格式）；pytest 71 passed、自检通过（129 文件）；打 tag `backup-before-fb-time-hint-cleanup-20260827`；待用户验收；
- 2026-08-27：修复反馈时间编辑入口的 Streamlit 异常：✎ 按钮的控件 key 与 session_state 状态 key 分离（`fb_dt_btn_*` / `fb_dt_open_*`），避免「控件实例化后修改同 key session_state」的 StreamlitAPIException；pytest 71 passed、AppTest 反馈页无异常；
- 2026-08-27：交付体验第三批：①**布局持久化兜底**——`persist_custom_layouts()` 返回 (ok,error) 并在 UI 显示云端保存失败原因；本地桌面运行时额外写 `data/custom_layouts_backup.json`，Supabase 恢复为空时回退本地备份并自愈回写；②**新算法接入页文件删除**——每个已上传算法文件增加「🗑 删除」+ 行内二次确认（确认/取消）；③**反馈显示时间可改**——新增迁移 `migrations/04_feedback_display_time.sql`（feedback 表加 `display_time` 字段 + `update_feedback_display_time` RPC 仅管理员），管理员在全部反馈区每条反馈可修改显示时间并保存（入口为时间旁低调小「✎」按钮，点击后才展开编辑，不显式标注），我的反馈/CSV 导出同步使用；④**权限落实**——`can_export` 实际生效（访客在设置页/指标页看不到下载导出控件），操作员在新算法接入页可见全部说明文字但不可上传（`can_configure` 可见 / `can_import_algo` 可传）；pytest 71 passed、自检通过（129 文件）、AppTest 通过；打 tag `backup-before-layout-algo-feedback-perm-20260827`；待用户验收；
- 2026-08-27：修复真实布局 MOSA 场景判定提示：设置页场景绑定提示在「导入的真实布局」下改用导入 JSON 的**实际车位数**（此前误用变灰滑杆的默认值 15）；有导入需求序列时改用新增的 `resolve_scene()` 按真实车辆时序精确判定（与运行时 `_resolve_scene` 共用同一规则，杜绝 UI 预估与运行时权重不一致）；新增测试 2 项，pytest 71 passed、自检通过、AppTest 真实布局 20 车位提示验证通过；打 tag `backup-before-scene-hint-fix-20260827`；
- 2026-08-27：策略最近参数持久化：新增 Supabase 用户偏好 `last_params_v1`——每次运行仿真后保存该策略本次参数（`persist_last_params`），登录/恢复会话时 `_load_last_params()` 拉回，设置页按策略自动回填控件（reboot/刷新后参数不丢）；`_render_param_widget`/`render_strategy_params` 支持 `initial` 回填，并对持久化值做类型转换与 min/max 夹取兜底（防脏数据崩溃）；打 tag `backup-before-last-params-persist-20260827`；pytest 69 passed、启动包自检通过、AppTest 回填/运行后保存验证通过，待用户验收；
- 2026-08-27：MOSA 场景权重与车位数/车辆数/时间**自动绑定**：新增 `estimate_scene()` 公共判定函数（需求密度 = 车辆数×平均停车时长 / (车位数×时间跨度)，≥0.85 饱和/≥0.6 高峰/否则平峰，共 3 种情况）；`scene` 参数标记 `locked`（网页渲染为灰色不可调，默认 auto）；UI 参数渲染器支持 PARAMS 项的 `locked` 字段（置灰），MOSA 策略下仿真设置页实时显示「当前车位数/车辆数/平均停车时长 → 判定为哪种场景及权重（时间/距离/利用率）」；新增场景绑定测试 3 项，pytest 69 passed、自检通过；
- 2026-08-27：按用户批准改造引擎对齐算法一文档：①**时间片路口碰撞检测**——所有车辆运动（入库/离场/移位）按有向边生成 `TimeSlice`，同一边时间片不重叠（`EDGE_GAP=2s` 硬约束），冲突时等待推进；②**场景 B 入库让行**——新车停里层车位被外层车挡时，外层车移位让行 → 新车停入 → 外层车回位（场景 A 离场让行已有）；`PathEngine` 新增 `get_path_edges`；新增 `tests/test_engine_timeslice.py`（4 项），pytest 69 passed、启动包自检通过（128 个关键文件）；
- 2026-08-27：算法一 MOSA 接入（打 tag `backup-before-mosa-20260827`）：新增 `src/parking_opt/strategies/mosa.py`（NSGA-II 离线全信息多目标优化，f1 总行驶时间/f2 总行驶距离/f3 利用率均衡，场景权重高峰重时间/平峰重距离/饱和重利用率，支持拒绝 -1）；`BaseStrategy` 新增 `prepare` 钩子（离线预分配通用接口），`SimulationEngine.run()` 开头自动调用（向后兼容）；登记注册表后网页自动出现「MOSA 多目标优化（离线）」及参数控件；规模保护（>60 车位或 >120 车跳过优化回退贪心）；新增 `tests/test_mosa.py`（11 项）；按原算法 `mosa_full.py` 对齐修正：Pareto 前沿 **min-max 归一化加权选解**（场景权重真正生效：peak/normal/saturated 选解不同）、拒绝惩罚 1000、种群/代数默认 30/50、初始化与变异按场景引导（peak 最近/saturated 类型均衡/normal 随机）；
- 2026-08-21：布局持久化：自定义布局以 `session_state.custom_layouts` 为真相源，登录/恢复会话时从 Supabase 偏好（`custom_layouts_v1`）恢复，导入/删除时回写；渲染相关页面前 `_sync_custom_layouts_to_globals()` 重建全局镜像（清除进程残留），退出登录 `clear_custom_layouts()` 清空。解决「退出登录后布局能用但删不掉/不显示」问题；打备份 tag `backup-before-layout-persist-20260823`；pytest 51 passed、AppTest 同步三场景通过、自检通过；
- 2026-08-21：布局删除入口优化：系统设置→导入布局→已导入列表的删除按钮改为红色 primary「🗑 删除」+ 行内二次确认（确认/取消），防误删；打备份 tag `backup-before-layout-delete-confirm-20260823`；pytest 51 passed、AppTest 删除/取消/确认三场景通过、自检通过；
- 2026-08-21：修复线上崩溃（Cloud 报 `build_demand_histogram` ValueError）：根因是导入的真实布局存在从入口不可达的车位时，行驶时间 inf 传播进 SimPy 时钟产生 nan 事件时间。三层防御：①引擎层——分配/等待分配时拒绝不可达车位、移位不可达缓冲位记 BUFFER_FAILED，杜绝 inf/nan 事件；②导入校验——布局 JSON 校验每个车位「入口可达且可返回入口」，不连通直接报错拒收；③UI 层——直方图/车辆明细表/时钟格式化对 None/nan/inf/字符串时间全部兜底。新增 `tests/test_engine_robustness.py`（2 项），pytest 51 passed、自检通过；
- 2026-08-21：按用户反馈，仿真设置页「停车场布局」下拉拆为「布局来源」分组（内置示意布局 / 导入的真实布局，仅在有导入布局时显示后者）；真实布局下加说明「路网/车位真实，车辆需求仍为仿真；车位数/纵深比例滑杆不生效」；新增 `BUILTIN_LAYOUT_KEYS` 常量区分内置/自定义布局；打备份 tag `backup-before-layout-source-20260821`；pytest 49 passed、AppTest 两场景通过、启动包自检通过，待用户验收；
- 2026-08-21：打备份 tag `backup-before-feedback-round2-20260821`；完成反馈优化第二批 `stage-d-feedback-round2`：需求时序条形图/车辆明细表/需求序列 JSON 导出导入 + 指标权重百分条/归一化/加权排名（与字典序并存切换），pytest 49 passed，自检与 AppTest 通过；后续按用户反馈定稿需求序列保存方式：①「浏览器下载」（时间戳防重名）②「下载到项目文件夹 data/demand_exports/」（一键，快速测试复现性，配套导入下拉）③「保存到指定位置（自选目录与文件名，长期保留用，默认折叠）」；「从项目文件夹选择」导入下拉保留；移动/删除下载文件功能已移除；仿真设置页在「导入需求序列」模式下把不再生效的参数变灰（车辆数、仿真时长/停车时长/高峰占比/预估误差），仍生效的保留可调（布局/策略/策略参数/车速/等待上限/种子/运行次数/优先级）；保存区定稿为「浏览器下载（通用）+ 另存为…（浏览器 File System Access API，访问者自选位置，Cloud/本机可用，不支持自动降级）+ 下载到项目文件夹（仅本机运行时显示）+ 保存到指定位置（自选目录与文件名）」；指标分析页排序模式默认改为「加权评分」（字典序保留可切换，顶部优先级区块标注仅字典序生效）；随后按用户反馈把「排序模式 + 权重」配置整体上移到仿真设置页「算法排名设置」，指标分析页只按设置展示对应内容（加权显示权重表+加权排名，字典序显示优先级表+字典序排名），单策略模式同样生效（打 tag `backup-before-demand-save-20260821`）；布局导入说明开放给操作员查看（说明+示例下载，上传仍仅管理员），待用户验收；
- 2026-08-18：完成「UI 拆分重构 + 交付体验优化」8 项优化（备份脱敏/trace 合并/进度条/反馈分页/动态路径分段/登录限流常量/app.py 拆分 1827→90 行/DESCRIPTION 收敛）+ 系统状态页 use_container_width 废弃预警，测试全绿，已验收；
- 2026-08-18：打备份 tag `backup-before-ui-refactor-20260818`；
- 2026-08-17：完成「算法接入接口 + 参数化」改造：PARAMS 参数声明规范、StrategyRegistry 统一注册表、策略/引擎/需求参数全暴露、融合算法示例 PeakOffPeakFusion、网页参数控件动态渲染 + 每策略 5 条调参历史、新算法接入说明文档；
- 2026-08-17：打备份 tag `backup-before-algo-interface-20260817`；
- 2026-08-15：修复动态路径页时间轴滑杆崩溃、移位时序竞争、引擎车位重复分配等 bug；
- 2026-08-13：新增等待调度策略可选（FIFO/短停车优先）、多 seed 统计、雷达图、策略回归测试；
- 2026-08-12：时长感知贪心设为主方法，CP-SAT 理论最优接入指标页，算法优先级升级为 Supabase 跨会话持久化；
- 2026-08-04：完成阶段 A 全部里程碑并批准路线。
