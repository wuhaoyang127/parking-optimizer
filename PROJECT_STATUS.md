---
project: 智能停车场车位分配与纵深移位优化
status_version: 7
last_updated: 2026-08-17
current_stage: D
stage_status: in_progress
current_milestone: stage-d-algo-interface
git_initialized: true
current_branch: stage-d-deliver
last_verified_commit: null
current_exec_plan: null
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
- **当前里程碑**：`stage-d-algo-interface`（算法接入接口与参数化改造）；
- **当前阶段阻断项**：无；
- **当前唯一下一步**：完成算法接入接口、参数可调与融合算法示例，见本对话执行计划；
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
- [ ] **阶段 D（应用与交付）**：进行中。Streamlit 多页面 Dashboard 已可运行；当前聚焦「算法接入接口 + 参数可调 + 融合算法示例」。

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
- 单元/回归测试：已有（`tests/test_core.py`、`tests/test_strategies_regression.py`）；
- 正式实验协议：已冻结（阶段 B）；
- 启动包自检：`python scripts/validate_starter_package.py`（默认只读）；
- 备份存档：git tag `backup-before-algo-interface-20260817`（2026-08-17）。

## 9. 当前关键文件

| 文件 | 用途 | 状态 |
|---|---|---|
| `AGENTS.md` | 长期项目规则 | 有效 |
| `PROJECT_STATUS.md` | 项目状态唯一入口 | 有效 |
| `.agent/PLANS.md` | ExecPlan 规范 | 有效 |
| `app.py` | Streamlit 多页面 Dashboard 入口 | 有效，本阶段重点改造 |
| `src/parking_opt/strategies/baselines.py` | 策略基类 + FCFS/最近/随机 | 有效，本阶段改造 |
| `src/parking_opt/strategies/greedy.py` | 贪心/离场贪心/时长感知贪心 | 有效，本阶段改造 |
| `src/parking_opt/strategies/registry.py` | 统一策略注册表 | 待新增 |
| `src/parking_opt/strategies/fusion.py` | 融合算法示例 | 待新增 |
| `docs/新算法接入说明.md` | 新算法接入步骤文档 | 待新增 |
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

执行「算法接入接口 + 参数可调 + 融合算法示例」改造，步骤如下：

1. 修复布局说明文档网页打不开；
2. 定义参数声明规范（`PARAMS`）并参数化策略/引擎/需求；
3. 建立统一 `StrategyRegistry` 注册表，替换硬编码字典；
4. 提供融合算法示例 `PeakOffPeakFusion`；
5. 网页端动态渲染参数控件 + 每策略 5 条运行历史对比；
6. 新增 `docs/新算法接入说明.md`。

## 12. 预计后续需要用户确认

- 融合算法的具体融合语义与比例参数范围；
- 各算法参数最终默认值与取值范围；
- 真实布局数据的接入与脱敏方式。

## 13. 最近重要变更

- 2026-08-17：打备份 tag `backup-before-algo-interface-20260817`，开始「算法接入接口 + 参数化」改造；
- 2026-08-15：修复动态路径页时间轴滑杆崩溃、移位时序竞争、引擎车位重复分配等 bug；
- 2026-08-13：新增等待调度策略可选（FIFO/短停车优先）、多 seed 统计、雷达图、策略回归测试；
- 2026-08-12：时长感知贪心设为主方法，CP-SAT 理论最优接入指标页，算法优先级升级为 Supabase 跨会话持久化；
- 2026-08-04：完成阶段 A 全部里程碑并批准路线。
