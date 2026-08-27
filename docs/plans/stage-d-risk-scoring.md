# 阶段D 新算法：risk_scoring（风险感知多准则评分，在线）

> 说明：本 ExecPlan 为算法二接入的设计与实施记录。算法最初在外部快照
> `新算法接入/算法二/parking-optimizer-20260827` 中实现；本会话将其并入
> `stage-d-deliver`（策略/测试/文档/实验/文献，主干其它内容全部保留），并修复了
> 实验中暴露的引擎移位让行并发竞态。本文件如实记录目标、设计、决策与验证。

## 目标与用户可见结果

新增一个**在线**车位分配策略 `risk_scoring`（风险感知多准则评分），完成后：

- 网页仿真设置页「策略」下拉框出现「风险感知多准则评分」，自动渲染 3 个权重滑杆
  （距离权重 `w_d` / 阻挡风险权重 `w_r` / 结构惩罚权重 `w_p`，范围 0–3，步长 0.1）；
- 可单策略运行，也可参与「全部对比」与加权/字典序排名；
- 与 MOSA（离线全信息上界）不同，本策略是**可部署的在线算法**：只读当前停车场状态
  与车辆预估离场时间，不读未来真值（真实停车时长）。

## 当前状态

- 已并入 `stage-d-deliver`（本次接入提交见 Git 历史，分支与远端同步）；
- 本会话已复跑验证：`tests/test_risk_scoring.py` 18 passed、全套 91 passed（无回归）、
  实验脚本在当前引擎下重跑产出新 `outputs/`（与文档 §11 数字一致）；
- 另修复实验中暴露的引擎移位让行并发竞态，并新增 2 项回归测试；
- **待用户验收**；`PROJECT_STATUS.md`、ExecPlan、交接摘要已同步。

## 范围

### 包含
- `src/parking_opt/strategies/risk_scoring.py`：`RiskScoringStrategy`（评分式在线分配）；
- `src/parking_opt/strategies/__init__.py`：登记 `RiskScoringStrategy`（保留既有注册）；
- `tests/test_risk_scoring.py`：18 项单元测试；
- `docs/algorithms/risk_scoring.md`：教学文档（15 节，含缺点与后续改进）；
- `scripts/exp_risk_scoring.py` + `outputs/exp_risk_scoring_{summary.md,raw.csv}`：第一版实验；
- `references/bibliography.bib` + `docs/research/03_文献矩阵.md`：文献依据。

### 不包含
- 融合语义变更（本策略是单算法，不改 `fusion.py` 框架）；
- `prepare()` 离线预分配钩子（本策略纯在线，不重写 `prepare`）；
- UI 页面代码改动（经 `StrategyRegistry` 自动出现，无需改页面）；
- 更高需求强度 / 更小车位的区分性实验（见「风险与降级」与后续实验）。

## 关键定义与假设

对每个空闲候选车位 `s` 计算综合代价，选最小者：

```
C(s | v, t) = w_d · D̂(s) + w_r · R̂(s, v, t) + w_p · P̂(s)
s* = argmin_s C(s | v, t)
```

三项均“越小越好”，在**当前候选集内** min–max 归一化到 [0,1] 后加权：

- **D(s) 距离**：入口到车位的最短路距离 `path_engine.distance_to_spot(s.node_id)`；
- **R(s,v,t) 阻挡风险 = 预期移位次数**：
  - v 会挡住的**已占内层车**数量（`edep(v) > edep(内层车)` → 内层车离场需为 v 移位）；
  - 会挡住 v 的**已占外层车**数量（`edep(外层车) > edep(v)` → v 离场需为它们移位）；
  - 预估离场时刻 `edep(x) = x.arrival_time + max(estimated_duration, 0)`，**在线可得**；
- **P(s) 结构惩罚**：`len(get_inner_spots(s))`，车位后方更深车位数（静态，反映阻挡潜力）。

tie-break：`(综合代价, 原始距离, depth, spot_id)` 升序，**完全确定、可复现**。
归一化对非有限值（不可达 inf 距离）记 1.0（最差），有限值全相等记 0.0，防 NaN/inf。

**信息边界（在线合法性）**：绝不读取 `vehicle.parking_duration`（仿真未来真值）；
占用车也只用其 `estimated_duration`（该车到达时系统即可知，`duration_greedy` 已采用同一量）。

## 里程碑

- [x] M1 策略实现 + 注册（文件：`risk_scoring.py`、`__init__.py`；可观察：注册表 `get("risk_scoring")` 命中）
- [x] M2 单元测试（文件：`test_risk_scoring.py`；验证：`pytest tests/test_risk_scoring.py` → 18 passed）
- [x] M3 教学文档 + 文献（文件：`docs/algorithms/risk_scoring.md`、`bibliography.bib`、`03_文献矩阵.md`）
- [x] M4 第一版实验（文件：`scripts/exp_risk_scoring.py`；验证：脚本输出与 `outputs/` 汇总一致）
- [x] M5 回归验证（验证：全套 `pytest` → 91 passed，无回归；启动包自检通过）
- [ ] M6 用户验收（停止条件：等待用户在网页确认下拉出现、权重可调、对比结果可信）

## 详细实施步骤

1. `RiskScoringStrategy(BaseStrategy)`，`name="risk_scoring"`，`__init__(w_distance=1.0, w_risk=1.5, w_depth=0.5)` 无参可构造（回归兼容）；
2. `assign()`：取 `get_available_spots()`，无空位返回 `(None,"waiting")`；一趟收集三项原始代价 → 分别 min–max 归一化 → 加权求和 → tie-break 选最小；
3. `_risk_cost()`：遍历 `get_inner_spots(s)` 与 `get_outer_spots(s)`，按 `edep` 比较计数；
4. `_depth_cost()`：`len(get_inner_spots(s))`；
5. `PARAMS` 暴露 3 个权重（网页控件契约，key 与构造参数一一对应）；
6. `strategies/__init__.py` 追加 `StrategyRegistry.register(RiskScoringStrategy)`。

## 验证与验收

| 检查 | 命令 | 结果 |
|---|---|---|
| 单元测试 | `py -m pytest tests/test_risk_scoring.py -q` | 18 passed |
| 全套回归 | `py -m pytest -q` | 91 passed（原 89 + 新 2 竞态回归，无回归） |
| 实验重跑 | `py scripts/exp_risk_scoring.py` | 当前引擎下产出新 `outputs/`，与文档 §11 数字一致（确定性） |
| 启动包自检 | `py scripts/validate_starter_package.py` | 通过（只读，未修改文件） |

极小人工例：见 `test_risk_scoring.py` 的 `test_risk_vs_distance_conflict`（近处高风险纵深位
vs 远处安全独立位）、`test_does_not_read_real_parking_duration`（固定预估、变动真实时长 → 决策不变）。

## 风险与降级

- **区分度不足**：100 车位对 60–140 辆需求容量充裕，满足率/利用率/等待/拒绝四项对四策略
  无区分度（均满足率 1.000）。**如实记录**，非算法缺陷；区分需更高需求强度 / 更小车位
  （列入后续实验，未完成）。
- **一步前瞻**：R 只估计“当前占用 + 本车”一步引发的移位，不预测后续到达车的连锁阻挡；
  中需求下出现均值 0.2 次、高需求下 1.8 次移位，如实保留（见文档 §11/§13/§14）。
- **候选集内相对归一化**：某车位得分依赖当前候选集（min–max 的固有性质），如实记录于文档 §13。
- **降级**：无空位 → `waiting`（引擎排队重试）；不可达车位 inf 距离归一化记 1.0，不产生 NaN。

## 决策日志

- 日期：2026-08-27
- 决策：定位为**在线单算法**，不重写 `prepare()`、不改融合框架。
  - 备选：接入为离线 `prepare` 预分配（同 MOSA）。
  - 理由：项目缺在线可部署评分策略；MOSA 已占“离线全信息上界”生态位，二者信息条件不同、不重复。
  - 证据：文档 §10 与 MOSA 定位对照；信息边界测试 `test_does_not_read_real_parking_duration`。
- 日期：2026-08-27
- 决策：默认权重取 `(1.0, 1.5, 0.5)`。
  - 备选：`(1,2,1)`、`(0.5,2,0.5)` 等（严格零移位，行驶 5680m）。
  - 理由：当前引擎下 `(1,1.5,0.5)` 均值移位 0.2 次、行驶 5588m；与严格零移位组合移位
    几乎相同但行驶少 92m，故保留默认。按 5 seed 均值选取，未挑特定 seed。
  - 证据：`outputs/exp_risk_scoring_summary.md` 权重扫描表（当前引擎重跑版）。
- 日期：2026-08-27
- 决策：R 的三因子表达式为**本项目自定义**，非文献原式。
  - 理由：文献（Abdeen 2021 为 inter-lot 选停车场、无纵深阻挡）不含移位；如实标注适配与自定义边界，不伪造文献支持。
  - 证据：文档 §4、`risk_scoring.py` 顶部 docstring。

## 进度记录

- 日期：2026-08-27
- 已完成：M1–M5（实现/测试/文档/实验/回归）。
- 实际验证：`pytest` 91 passed；实验在当前引擎下重跑并同步文档；自检通过。
- 问题：区分性实验未做；一步前瞻在中/高需求下留有 0.2/1.8 次移位。
- 下一步：M6 用户验收。

## 最终回顾

risk_scoring 作为**在线可部署**评分策略补齐了在线生态位（对照 MOSA 离线上界）。相对 nearest
显著降低移位（12.0/20.0/27.2 → 0/0.2/1.8），相对 greedy/duration_greedy 在同为（近）零移位下
行驶距离低约 25–30%。偏离计划之处：实验产物按当前引擎重跑，默认权重选取理由相应改写；
接入过程中修复引擎移位让行并发竞态。未解决问题：区分性实验、多步前瞻风险模型（见文档 §14）。
后续阶段入口：用户验收（已并入 `stage-d-deliver`）。
