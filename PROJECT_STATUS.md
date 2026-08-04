---
project: 智能停车场车位分配与纵深移位优化
status_version: 5
last_updated: 2026-08-04
current_stage: A
stage_status: approved
current_milestone: stage-a-approved
git_initialized: true
current_branch: stage-a-research
last_verified_commit: d9baa01
current_exec_plan: docs/plans/stage-a-research.md
latest_handoff: null
next_prompt: prompts/B_数学模型与工程设计.md
authoritative_route_document: docs/research/05_最终路线决策.md
current_stage_blockers: []
downstream_blockers: [{"target_stage":"C","issue":"纵深阻挡、移位、缓冲位和指标口径尚未在阶段 B 冻结"}]
ui_framework_preference: Streamlit（暂定，阶段 D0 复核）
deliverable_type: 向管理员推荐方案的Dashboard
status_maintainer: 项目主线程或用户指定协调线程
---

# 项目当前状态

> 本文件是跨 Codex 对话的项目状态唯一入口。只记录当前有效状态；详细过程见 ExecPlan、阶段交接摘要和 Git 历史。

## 1. 项目一句话说明

研究普通独立车位与纵深车位混合场景下的动态车位分配，在保证可行和服务需求的前提下，优先提高有效车位时空利用率，并降低移位次数与移位距离。

## 2. 当前状态快照

- **当前阶段**：阶段 A 已完成，等待用户审查批准；
- **验收状态**：`awaiting_review`；
- **Git 状态**：已初始化，当前在 `stage-a-research` 分支；
- **当前 ExecPlan**：`docs/plans/stage-a-research.md`；
- **最近交接摘要**：`null`，首次执行，无前置阶段；
- **当前阶段阻断项**：等待用户审查并批准最终路线决策（`docs/research/05_最终路线决策.md`）；
- **当前唯一下一步**：用户批准后执行 `prompts/阶段验收与复核.md`，然后进入阶段B；
- **禁止事项**：用户批准前不进入阶段B。

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

## 3. 候选路线状态（阶段A已完成）

阶段A最终推荐的路线是：

> **路网成本预处理 + 离散事件仿真 + CP-SAT小规模离线基准 + 带缓冲位的在线贪心策略（主方法）+ 确定性降级，辅以 Dijkstra-SA 作为对照基线。**

详见 `docs/research/05_最终路线决策.md`。

- [x] 已形成候选路线；
- [x] 已完成文献核验（20条文献矩阵，部分待验证DOI）；
- [x] 已完成候选算法决策矩阵（8条路线×13维度）；
- [x] 已通过阶段 A 执行完成；
- [ ] 已由用户批准最终路线。

## 4. 已完成并确认

- [x] 确定 A、B、C、D 四阶段流程；
- [x] 建立并整理 `AGENTS.md`；
- [x] 建立 `.agent/PLANS.md`；
- [x] 建立阶段提示词和验收提示词；
- [x] 建立跨对话状态管理和阶段交接模板；
- [x] 建立 Git、归档、隐私和 `.gitignore` 规则；
- [x] 将两份原始 Word 纳入 `references/original/`；
- [x] 增加可执行的启动包结构与一致性检查脚本；
- [x] 自检脚本支持初始模式与 Git 项目模式，默认运行不修改仓库；
- [x] 已完成阶段 A：原方案审查、文献调研、候选算法比较、最终路线决策；
- [ ] 尚未开始阶段 B（数学模型与工程设计）；
- [ ] 尚未开始核心代码。

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

## 6. 尚未冻结

- 最终主算法和对照算法；
- 阻挡、移位和缓冲位的精确定义；
- 利用率最终口径；
- 离线基准、在线策略和最终动态方法的具体形式；
- 是否引入需求预测；
- 决策周期、候选裁剪和运行时间限制；
- 正式实验协议和统计方法；
- 现实数据接口最小字段；
- 最终展示框架。当前暂定优先考虑 Streamlit，阶段 D0 必须复核。

## 7. 数据与结论边界

### 当前已有

- 停车场平面图；
- 车位坐标；
- 道路连接；
- 入口和出口数量。

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

- 核心代码：未开始；
- Python 环境和依赖：计划在阶段 C1 建立；
- 单元测试：未建立；
- 集成测试：未建立；
- 正式实验协议：未冻结；
- 可复现实验结果：暂无；
- 启动包初始检查：`python scripts/validate_starter_package.py --initial`；
- Git 初始化后的持续检查：`python scripts/validate_starter_package.py`；
- 两种默认检查均只读；只有加 `--write-report` 才更新 JSON 报告。

## 9. 当前关键文件

| 文件 | 用途 | 状态 |
|---|---|---|
| `AGENTS.md` | 长期项目规则 | 有效 |
| `PROJECT_STATUS.md` | 项目状态唯一入口 | 有效 |
| `.agent/PLANS.md` | ExecPlan 规范 | 有效 |
| `docs/research/05_最终路线决策.md` | 阶段A最终路线决策（权威路线文档） | 待批准 |
| `docs/plans/stage-a-research.md` | 阶段A ExecPlan | 已完成 |
| `docs/handoffs/TEMPLATE.md` | 阶段交接模板 | 有效 |
| `prompts/阶段验收与复核.md` | 当前下一提示词 | 待执行 |
| `prompts/B_数学模型与工程设计.md` | 阶段B提示词 | 待批准后执行 |
| `scripts/validate_starter_package.py` | 启动包与项目状态一致性检查 | 有效 |
| `references/original/` | 两份原始材料，只读 | 已包含 |
| `references/bibliography.bib` | 文献库（BibTeX） | 已创建 |
| `docs/research/01-07` | 阶段A全部研究产出 | 已完成 |

## 10. 阻断项与风险

### 当前阶段阻断项

无。阶段 A 可以开始。

### 下游阶段阻断项

- **进入阶段 B 前**：阶段 A 必须完成技术路线调研、比较、验收并由用户批准；
- **进入阶段 C 前**：阶段 B 必须冻结纵深阻挡、移位、缓冲位、指标、数据契约和实验协议。

这些下游阻断项是当前阶段要解决的问题，不阻止阶段 A 工作。

### 重要风险

- 真实时序数据不足，早期只能做仿真可行性验证；
- 利用率与移位、等待和出库效率可能冲突；
- 动态算法可能发生未来真值泄漏；
- 约 100 个车位可能需要复杂度控制；
- 旧方案与主算法必须在公平条件下比较。

## 11. 当前唯一下一步

等待用户审查阶段A产出，重点审查 `docs/research/05_最终路线决策.md`。

批准后：
1. 执行 `prompts/阶段验收与复核.md` 完成正式验收；
2. 合并 `stage-a-research` → `main`，打标签 `stage-a-approved`；
3. 创建 `stage-b-model` 分支；
4. 执行 `prompts/B_数学模型与工程设计.md` 进入阶段B。

## 12. 预计后续需要用户确认

- 是否允许临时缓冲位；
- 是否能获取预计离场或预约信息；
- 现实停车场允许哪些主动移位；
- 最终应用偏管理推荐还是自动执行调度命令；
- 阶段 D 是否继续采用暂定的 Streamlit 展示方案。

## 13. 最近重要变更

- 2026-08-04：完成阶段A全部6个里程碑：原方案审查（否定ARIMA/RF）、20条文献矩阵、8路线决策矩阵、最终路线决策（贪心+缓冲位主方法，四层架构）、数据缺口与三级验证方案、阶段B输入清单
- 2026-08-04：初始化Git，创建stage-a-research分支
- 2026-08-04：废弃 `docs/候选算法路线.md` 的权威性，最终路线决策迁移至 `docs/research/05_最终路线决策.md`
- 2026-07-13：自检脚本改为默认只读
