# RHO 滚动时域动态修正（rho_rolling，算法三）

## 1. 算法名称

- 英文标识：`rho_rolling`
- 中文名：RHO 滚动时域动态修正
- 来源：`新算法接入/算法三/SARIMA+RHO 滚动时域 实时动态修正完整解决方案.docx`

## 2. 研究问题

普通独立车位与纵深车位混合场景下的**在线动态分配**。核心矛盾：基于预测的
前置规划能提前削峰，但预测与现场实际车流总有偏差；纯实时分配响应快，但
缺乏全局预见性。算法三要解决的是「预测失准怎么办」——用滚动时域控制
（Receding Horizon Optimization, RHO）把预测、纠偏、降级兜底串成闭环。

## 3. 设计动机

- 预测前置规划 + 滚动窗口动态纠偏 + 实时事件兜底，三者互补而非互斥；
- 计算开销分层：轻微偏差增量更新、中度偏差全局重优化、重度偏差轻量兜底，
  避免高峰系统计算卡顿；
- 兼容项目既有分层架构：静态 Dijkstra 粗筛车位、TDD 动态路线精算、
  MOSA 多目标帕累托优化、事件移位调度。

## 4. 数学定义

设滚动校验步长 `T_step`（默认 10min）、预测窗口 `T_win`（默认 60min）。

- `F_t`：t 时段 SARIMA 预测到场车辆数；
- `A_t`：t 时段实际到场车辆数；
- 相对偏差：

```
E_t = |A_t - F_t| / F_t        (F_t ≠ 0；F_t = 0 时 E_t = A_t)
```

三级修正（RHO 内置阈值）：

| 等级 | 判定 | 动作 |
|---|---|---|
| 一级轻微 | `E_t ≤ 20%` | 保持基准方案，增量更新预测 |
| 二级中度 | `20% < E_t ≤ 50%` | 重训预测 + 切换重优化方案（实际偏高重吞吐、偏低重距离） |
| 三级重度 | `E_t > 50%` 或事件触发 | 停用前置规划，降级纯实时兜底 |

事件触发（无需等待定时窗口）：5 分钟内进场车辆数超过阈值（默认 10 台）。
恢复机制：连续 2 个滚动步长偏差回归轻微后自动切回基准方案。

## 5. 仿真包内的 SARIMA-lite 预测器

生产环境可直接使用 statsmodels SARIMA；仿真包为保持 worker 依赖精简
（免 statsmodels），采用等价轻量近似 `SarimaLite`（Holt 水平/趋势 +
AR(1) 误差修正，相当于 ARIMA(1,1,1) 的在线近似）：

```
初始化：level = None, trend = 0, last_err = 0
update(actual):
    if level is None: level = actual; return
    one_step = level + trend + phi * last_err
    last_err = actual - one_step
    prev = level
    level = alpha * actual + (1 - alpha) * (level + trend)
    trend = beta * (level - prev) + (1 - beta) * trend
predict(k): f_k = level + k * trend + phi^k * last_err  （clamp ≥ 0）
```

默认 `alpha=0.5, beta=0.15, phi=0.5`（较灵敏，便于从突发中恢复）。

## 6. 伪代码

```
策略状态: mode ∈ {plan, adjust, fallback}; 每 10min 一个 bucket 的到场计数
assign(vehicle, time, lot, path_engine):
    记录该车到达（按 vehicle.arrival_time 入 bucket，每车只计一次）
    滚动检查(time):
        对每个已完成且未处理的 bucket: 用其实际到场数更新 SARIMA-lite
        按整个预测窗口(60min)累计偏差分级:
            A = Σ 窗口内各 bucket 实际到场数
            F = Σ 窗口内各 bucket 预测值（无预测的时段跳过）
            E = |A-F|/F -> 更新 mode
        向前预测下一窗口各 bucket 的 F
    事件检查(time): 5 分钟内到场数 > 阈值 -> mode = fallback
    if mode == fallback: return fallback_strategy.assign(...)   # 兜底A=就近
    if mode == adjust:   return (high 或 low 子策略).assign(...) # 按 A-F 方向
    return plan_strategy.assign(...)                            # 基准方案
```

## 7. 输入信息边界（在线合法性自审）

- **只读**：已到达车辆的到达时刻（`vehicle.arrival_time`）、当前车位占用状态、
  `vehicle.estimated_duration`（预估时长，在线可得）、路网距离；
- **不读**：未来需求（不实现 `prepare`）、`vehicle.parking_duration`（真实停车
  时长，未来真值）；
- 与 nearest / duration_greedy / risk_scoring 同属在线信息条件，公平可比；
  与 MOSA / CP-SAT（离线全信息）不可同口径对比。

## 8. 参数

| key | 默认 | 含义 |
|---|---|---|
| `roll_step` | 10 | 滚动校验步长（分钟） |
| `window_min` | 60 | 车流预测窗口（分钟） |
| `mild_threshold` | 0.2 | 一级轻微偏差阈值 |
| `severe_threshold` | 0.5 | 三级重度偏差阈值 |
| `burst_threshold` | 10 | 5 分钟突发进场阈值（台） |
| `plan_strategy` | duration_greedy | 基准方案算法 |
| `high_load_strategy` | greedy | 中度偏高算法（重吞吐） |
| `low_load_strategy` | nearest | 中度偏低算法（重距离） |
| `fallback_strategy` | nearest | 重度兜底算法（兜底A=就近） |

## 9. 时间复杂度

每次分配 O(1)（滚动检查为增量更新，分摊常数级）；预测器更新与预测均为
O(window_buckets)。整体与所选子策略同阶（默认 duration_greedy / nearest
均为 O(n_spots)）。

## 10. 与现有算法的区别

- 对 `duration_greedy`：后者是单一在线规则，无预测与模式切换；RHO 是
  「预测 + 分级修正」的控制框架，可把 duration_greedy 作为基准方案包进来；
- 对 `risk_scoring`：后者是评分式单步决策；RHO 是时序滚动决策，按预测偏差
  切换决策逻辑；
- 对 `mosa`：MOSA 是离线全信息预分配（可读未来），RHO 在线只做滚动预测，
  且重度偏差时可用 nearest 等轻量算法兜底（兜底B可配置为 mosa，但子策略
  在无 prepare 时自动退化为其贪心回退，属纯在线执行）。

## 11. 第一版实验结果

（实验脚本 `scripts/exp_rho.py`，产出 `outputs/exp_rho_summary.md`；
三档需求 × 5 seed，同一 seed 下四策略喂相同需求序列，RHO 用默认参数。）

### 第一版结论（如实记录，含不占优处）

| 强度 | nearest 移位 | duration_greedy 移位 | risk_scoring 移位 | rho_rolling 移位 |
|---|---|---|---|---|
| 低（60 辆） | 17.2 | 0.0 | 0.0 | 16.4 |
| 中（100 辆） | 27.2 | 0.0 | 0.2 | 25.2 |
| 高（140 辆） | 41.6 | 0.0 | 1.4 | 36.4 |

- 默认配置下 RHO 的实验结果**接近 nearest**：需求生成器为双峰分布，在线
  SARIMA-lite 在高峰来临时预测显著偏低，RHO 按设计判定「三级重度偏差」并
  切到兜底（nearest），随后预测在高峰/低谷间来回追赶，恢复窗口较少；
- 这说明**分级修正机制本身工作正常**（偏差一大就降级、不硬撑全局方案），
  但在「无历史数据的在线预测 + 双峰冲击」条件下，RHO 的长期表现受限于
  预测器强度，接近其兜底算法；与文档设计一致——RHO 的价值依赖一个较好的
  SARIMA（有历史月度数据训练），而非预测器失效时的兜底性能；
- 阈值扫描显示默认 (0.2, 0.5) 在中强度下是平稳点（微调阈值不显著改变结果），
  默认参数可保留；
- 不占优处：仿真为平稳双峰、无节假日/活动冲击，RHO 的纠偏能力被低估；真实
  道闸流水的非平稳冲击 + 有历史训练的 SARIMA 才是其主战场，需后续验证。

## 12. 优点

- 在线合法：不读未来需求与真实停车时长，与在线基线公平可比；
- 分层计算开销：轻微增量、中度重优化、重度降级，高峰不卡顿；
- 容错闭环：自动降级 + 连续 2 步长回归后自动恢复；
- 免依赖：SARIMA-lite 无 statsmodels，worker 精简依赖即可运行；
- 子策略可插拔：基准/偏高/偏低/兜底四种算法均可在网页下拉切换。

## 13. 缺点

- 预测器为轻量近似，非完整 SARIMA（季节项未建模，长周期规律学不到）；
- 滚动修正由车辆到达事件驱动，无车到达时不推进窗口（仿真内等价、真实系统
  应由定时器驱动）；
- 事件触发只覆盖「进场突发」，通道拥堵、集中离场等触发源未在仿真中建模；
- 兜底B（局部 MOSA）在纯在线子策略执行时退化为贪心回退，与原文案的
  「局部寻优」有差距。

## 14. 后续可能改进

- 生产环境替换为 statsmodels SARIMA（季节项 + 节假日哑变量）；
- 增加定时器驱动滚动（不依赖到达事件）；
- 接入真实道闸流水，验证非平稳冲击下的三级切换；
- 为兜底B实现真正的局部重优化（对当前排队车辆小规模 MOSA）。
