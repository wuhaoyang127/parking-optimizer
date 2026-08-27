---
project: 智能停车场车位分配与纵深移位优化
status_version: 14
last_updated: 2026-08-27
current_stage: D
stage_status: in_progress
current_milestone: stage-d-mosa-integration
git_initialized: true
current_branch: stage-d-deliver
last_verified_commit: null
current_exec_plan: docs/plans/stage-d-mosa-integration.md
latest_handoff: null
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
- **当前里程碑**：`stage-d-mosa-integration`（算法一 MOSA 多目标优化接入，已实现待验收）；
- **当前阶段阻断项**：无；
- **当前唯一下一步**：用户验收 MOSA 接入（网页策略下拉框出现「MOSA 多目标优化（离线）」，与在线策略对比、调参）；
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
- [x] 阶段 D：算法一 MOSA 接入（离线全信息 NSGA-II 多目标优化：f1 总行驶时间/f2 总行驶距离/f3 利用率均衡，场景权重高峰重时间/平峰重距离/饱和重利用率；BaseStrategy.prepare 钩子 + 引擎自动调用 + 登记注册表网页自动出现，规模保护 >60 车位/>120 车回退贪心），pytest 62 passed、自检通过，待用户验收。

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
- 单元/回归测试：已有（`tests/test_core.py`、`tests/test_strategies_regression.py`、`tests/test_demand_io.py`、`tests/test_ranking.py`、`tests/test_engine_robustness.py`、`tests/test_mosa.py`，共 62 项）；
- 正式实验协议：已冻结（阶段 B）；
- 启动包自检：`python scripts/validate_starter_package.py`（默认只读）；
- 备份存档：git tag `backup-before-mosa-20260827`（2026-08-27）；更早 `backup-before-ui-refactor-20260818`（2026-08-18）、`backup-before-algo-interface-20260817`（2026-08-17）。

## 9. 当前关键文件

| 文件 | 用途 | 状态 |
|---|---|---|
| `AGENTS.md` | 长期项目规则 | 有效 |
| `PROJECT_STATUS.md` | 项目状态唯一入口 | 有效 |
| `.agent/PLANS.md` | ExecPlan 规范 | 有效 |
| `app.py` | Streamlit 多页面 Dashboard 瘦入口（~90 行） | 有效，本轮已完成拆分 |
| `src/auth.py` | Supabase 认证后端（登录/RPC/反馈/偏好） | 有效 |
| `src/viz.py` | Plotly 绘图（trace 已合并提速） | 有效 |
| `src/ui/` | 常量/布局构建器/仿真工具 + 8 页面函数 | 有效 |
| `src/parking_opt/strategies/baselines.py` | 策略基类 + FCFS/最近/随机 | 有效 |
| `src/parking_opt/strategies/greedy.py` | 贪心/离场贪心/时长感知贪心 | 有效 |
| `src/parking_opt/strategies/registry.py` | 统一策略注册表 | 有效 |
| `src/parking_opt/strategies/fusion.py` | 融合算法接口 + 示例 | 有效 |
| `src/parking_opt/strategies/mosa.py` | 算法一 MOSA：NSGA-II 离线多目标预分配策略 | 有效，本轮新增 |
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

1. 用户验收 **算法一 MOSA 接入**（`stage-d-mosa-integration`，计划：`docs/plans/stage-d-mosa-integration.md`）：
   - 网页仿真设置页「策略」下拉框出现「MOSA 多目标优化（离线）」，带 4 个参数控件（种群规模/进化代数/场景模式/评估等待上限）；
   - 单策略运行或「全部对比」均可选 MOSA；注意其 DESCRIPTION 已标注「离线全信息对照基准」，与在线策略对比时为上界参考（与 CP-SAT 定位一致）；
   - 本地验证：pytest 62 passed、启动包自检通过、端到端对比中 MOSA 满足率显著高于在线策略（离线全信息）。
2. 上轮 `stage-d-feedback-round2` 4 项反馈（需求时序可视化/需求序列导入导出/加权多指标排名/布局来源分组）仍**待用户验收**。

## 12. 预计后续需要用户确认

- 融合算法的具体融合语义与比例参数范围；
- 各算法参数最终默认值与取值范围；
- 真实布局数据的接入与脱敏方式。

## 13. 最近重要变更

- 2026-08-27：算法一 MOSA 接入（打 tag `backup-before-mosa-20260827`）：新增 `src/parking_opt/strategies/mosa.py`（NSGA-II 离线全信息多目标优化，f1 总行驶时间/f2 总行驶距离/f3 利用率均衡，场景权重高峰重时间/平峰重距离/饱和重利用率，支持拒绝 -1）；`BaseStrategy` 新增 `prepare` 钩子（离线预分配通用接口），`SimulationEngine.run()` 开头自动调用（向后兼容）；登记注册表后网页自动出现「MOSA 多目标优化（离线）」及参数控件；规模保护（>60 车位或 >120 车跳过优化回退贪心）；新增 `tests/test_mosa.py`（11 项），pytest 62 passed、启动包自检通过；端到端对比中 MOSA 满足率显著高于在线策略（离线全信息上界参考，与 CP-SAT 定位一致）；
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
