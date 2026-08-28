---
project: 智能停车场车位分配与纵深移位优化
status_version: 24
last_updated: 2026-08-28
current_stage: D
stage_status: in_progress
current_milestone: stage-d-dynamic-path-feedback
git_initialized: true
current_branch: stage-d-deliver
last_verified_commit: 39936c9
current_exec_plan: docs/plans/stage-d-dynamic-path-feedback.md
latest_handoff: docs/handoffs/stage-d-risk-scoring-20260827.md
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
- **当前里程碑**：`stage-d-dynamic-path-feedback`（动态路径页反馈修复：入库虚线按实际入口、离场/移位动画、移位车辆表；多入口多出口已验收；已于 2026-08-28 用户验收通过）；
- **当前阶段阻断项**：无；
- **当前唯一下一步**：等待用户提出下一项优化需求。
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
- 单元/回归测试：已有（`tests/test_core.py`、`tests/test_strategies_regression.py`、`tests/test_demand_io.py`、`tests/test_ranking.py`、`tests/test_engine_robustness.py`、`tests/test_mosa.py`、`tests/test_engine_timeslice.py`、`tests/test_risk_scoring.py`、`tests/test_engine_shift_race.py`、`tests/test_multi_entry.py`，共 103 项）；
- 正式实验协议：已冻结（阶段 B）；
- 启动包自检：`python scripts/validate_starter_package.py`（默认只读）；
- 备份存档：git tag `backup-before-dynamic-path-feedback-20260828`、`backup-before-dynamic-path-feedback-accept-20260828`、`backup-before-shift-table-20260828`、`backup-before-multi-entry-exit-20260828`、`backup-before-risk-scoring-accept-20260828`（2026-08-28）；`backup-before-risk-scoring-20260827`、`backup-before-fb-time-hint-cleanup-20260827`、`backup-before-layout-algo-feedback-perm-20260827`、`backup-before-scene-hint-fix-20260827`、`backup-before-last-params-persist-20260827`、`backup-before-mosa-20260827`（2026-08-27）；更早 `backup-before-ui-refactor-20260818`（2026-08-18）、`backup-before-algo-interface-20260817`（2026-08-17）。

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
| `src/parking_opt/strategies/mosa.py` | 算法一 MOSA：NSGA-II 离线多目标预分配策略 | 有效 |
| `src/parking_opt/strategies/risk_scoring.py` | 算法二 risk_scoring：风险感知多准则评分（在线） | 有效，本轮新增 |
| `tests/test_risk_scoring.py` | 算法二 18 项单元测试 | 有效，本轮新增 |
| `tests/test_engine_shift_race.py` | 引擎移位让行并发竞态回归测试（2 项） | 有效，本轮新增 |
| `docs/algorithms/risk_scoring.md` | 算法二教学文档（数学定义/伪代码/实验/优缺点） | 有效，本轮新增 |
| `scripts/exp_risk_scoring.py` | 算法二第一版实验脚本（产出 `outputs/`，本地产物） | 有效，本轮新增 |
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

1. 动态路径页反馈修复（提交 `a770411`）与移位车辆表（提交 `39936c9`）已于 2026-08-28 用户验收通过；多入口多出口改造（提交 `49a6b8b`）此前已验收。
2. 等待用户提出下一项优化需求。

## 12. 预计后续需要用户确认

- 融合算法的具体融合语义与比例参数范围；
- 各算法参数最终默认值与取值范围；
- 真实布局数据的接入与脱敏方式。

## 13. 最近重要变更

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
