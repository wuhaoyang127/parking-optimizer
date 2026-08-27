---
stage: D
status: awaiting_review
completed_date: 2026-08-27
source_exec_plan: docs/plans/stage-d-risk-scoring.md
verified_commit: dc1a7f8
next_stage: none
---

# 阶段D 里程碑交接摘要：risk_scoring（风险感知多准则评分，在线）

## 1. 阶段目标

为系统新增一个**在线可部署**的车位分配策略 `risk_scoring`：对每个空位打综合代价分
`C = w_d·距离 + w_r·阻挡风险 + w_p·结构惩罚`（候选集内 min–max 归一化后加权），argmin 选位。
补齐在线评分策略生态位（对照 MOSA 的离线全信息上界），并保持在线信息边界合法。

## 2. 已完成并验证

- 策略实现 `RiskScoringStrategy` + 注册表登记，网页/CLI 经注册表自动发现；
- 18 项单元测试（契约 / 风险语义 / 信息边界 / tie-break 确定性 / 退化性质 / 注册），全绿；
- 全套 91 passed（原 89 + 新 2 竞态回归），**无回归**；
- 第一版实验（3 档需求 × 5 seed，同 seed 同需求序列公平对比）在当前引擎下**重跑产出新 outputs**；
- 教学文档 15 节（含缺点 §13、后续改进 §14）+ 文献 bib + 文献矩阵。

## 3. 已批准或冻结的决定

| 决定 | 结论 | 证据/权威文件 |
|---|---|---|
| 算法定位 | 在线单算法，不重写 `prepare`、不改融合框架 | ExecPlan 决策日志；`risk_scoring.py` docstring |
| 信息边界 | 只读当前状态 + `estimated_duration`，绝不读 `parking_duration` | `test_does_not_read_real_parking_duration` |
| 默认权重 | `(w_d,w_r,w_p)=(1.0,1.5,0.5)`，当前引擎下均值移位 0.2 次、行驶 5588m（比严格零移位组合少 92m），按 5 seed 均值未挑 seed | `outputs/exp_risk_scoring_summary.md` |
| 文献边界 | R 三因子为项目自定义，非文献原式，已如实标注适配 | `docs/algorithms/risk_scoring.md` §4 |

> 以上为本里程碑内的实现级决定；是否纳入项目级冻结基线由用户在验收时确认。

## 4. 关键文件与运行入口

| 文件或命令 | 用途 |
|---|---|
| `src/parking_opt/strategies/risk_scoring.py` | 策略实现（评分 + 归一化 + tie-break） |
| `src/parking_opt/strategies/__init__.py` | 登记 `RiskScoringStrategy` |
| `tests/test_risk_scoring.py` | 18 项单元测试 |
| `docs/algorithms/risk_scoring.md` | 教学文档（数学定义/伪代码/信息边界/实验/优缺点） |
| `scripts/exp_risk_scoring.py` | 第一版实验，产出 `outputs/exp_risk_scoring_{summary.md,raw.csv}` |
| `py -m pytest -q` | 全套回归（91 passed） |
| `py scripts/exp_risk_scoring.py` | 重跑实验，产出 `outputs/exp_risk_scoring_{summary.md,raw.csv}` |

## 5. 实际验证

| 命令/检查 | 结果 | 证据 |
|---|---|---|
| `py -m pytest tests/test_risk_scoring.py -q` | 18 passed | 本会话 2026-08-27 |
| `py -m pytest -q`（全套） | 91 passed（无回归） | 本会话 |
| `py scripts/exp_risk_scoring.py` | 输出与 `outputs/` 汇总一致 | 高需求 shifts `27.2/0/0/1.8`、drive `7769/13322/13220/10043` 等与文档 §11 一致 |
| `py scripts/validate_starter_package.py` | 通过（只读，未修改文件） | 本会话 |

> 说明：本机为 Windows Python 3.9（`py` 启动），依赖见 `requirements.txt`；
> 测试与实验**不需要** streamlit/ortools/plotly/supabase（应用层与 CP-SAT 才需要）。

## 6. 失败案例与已知限制

- **四项主指标无区分度**：100 车位对 60–140 辆需求容量充裕，满足率/利用率/等待/拒绝对四策略
  全同（满足率 1.000）；区分需更高需求强度或更小车位（后续实验，**未完成**）。
- **一步前瞻**：R 不预测后续到达车的连锁阻挡；中需求下均值 0.2 次、高需求下 1.8 次移位，如实保留。
- **候选集内相对归一化**：车位得分依赖当前候选集（min–max 固有性质）。
- 以上均已如实写入文档 §11 结论 / §13 缺点，未美化。

## 7. 未解决问题和风险

- 阻断：无。
- 重要：区分性实验缺失（当前无法用四项主指标证明在线策略间差异）。
- 一般：默认权重未做敏感性分析的正式冻结；多步前瞻风险模型待研究（文档 §14）。

## 8. 下一阶段进入条件

- 用户验收本里程碑（网页确认下拉出现「风险感知多准则评分」、3 权重滑杆可调、对比可信）；
- 若批准，可选：①（已并入 `stage-d-deliver`，无需再合并）；②补区分性实验。

## 9. 需要用户决定

1. 是否验收 risk_scoring 里程碑（已并入 `stage-d-deliver`）；
2. 是否补跑更高需求强度 / 更小车位的区分性实验。

## 10. `PROJECT_STATUS.md` 更新摘要

- `current_milestone`：`stage-d-mosa-integration` → `stage-d-risk-scoring`；
- `current_branch`：保持 `stage-d-deliver`（算法二已并入该分支）；
- `current_exec_plan` → 本里程碑 ExecPlan；`latest_handoff` → 本文件；
- 测试计数 71 → 91，新增测试文件与关键文件登记；
- 新增回滚 tag `backup-before-risk-scoring-20260827`；
- 阶段状态仍 `in_progress`（stage D 未结束，本里程碑 `awaiting_review`）。
