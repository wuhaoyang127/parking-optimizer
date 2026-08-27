# 风险感知多准则评分分配（risk_scoring）

> 第一版新算法说明。本算法是**单算法**（继承 `BaseStrategy`，不切换/组合子策略、不改动融合框架），
> 因此无需向组长报备"新融合类型"。接入后网站算法下拉框自动出现「风险感知多准则评分」，并渲染 3 个权重滑杆。

## 1. 算法名称

- 英文标识（注册键）：`risk_scoring`
- 网页显示名：**风险感知多准则评分**
- 类：`RiskScoringStrategy`（`src/parking_opt/strategies/risk_scoring.py`）

## 2. 研究问题

普通独立车位与纵深车位混合、车辆实时到达的停车场中，在**有限在线信息**下为每辆车选车位，
兼顾：入口到车位的行驶距离、纵深阻挡导致的移位风险、以及车位结构本身的阻挡潜力。
核心难点：如何在**一次连续评分**里权衡这些相互冲突的目标，而不是用硬性优先级把某一目标绝对化。

## 3. 设计动机

现有算法要么单准则（`nearest` 只看距离），要么硬优先级分层（`greedy`/`duration_greedy`：独立位永远
压过纵深位，再按二值短/长停分流）。硬分层的问题是：**一个很远的独立位也会永远优先于一个近在咫尺、
且几乎不会造成阻挡的纵深外层位**，牺牲了行驶距离。本算法改用**多准则加权评分**做连续权衡，
让"距离/风险/结构"三者按可调权重折中，得到一个可解释、可调、机制清晰的在线分配器。

## 4. 文献来源

| 论文 | 年份 | 期刊/会议 | DOI / 链接 | 与本算法关系 |
|---|---|---|---|---|
| Abdeen M.A.R., Nemer I.A., Sheltami T.R. — *A Balanced Algorithm for In-City Parking Allocation: A Case Study of Al Madinah City* | 2021 | Sensors 21(9):3148 (MDPI) | [10.3390/s21093148](https://doi.org/10.3390/s21093148) · 开放全文 [PMC8125470](https://pmc.ncbi.nlm.nih.gov/articles/PMC8125470/) | **主依据**。提出停车分配的多准则加权和评分 `U_i=Σ_j w_j·d̄_ij`（Eq.5–6），配 min–max 归一化（Eq.3–4）。 |
| Kim K.H., Hong G.-P. — *A heuristic rule for relocating blocks* | 2006 | Computers & Operations Research 33(4):940–954 | [10.1016/j.cor.2004.08.005](https://doi.org/10.1016/j.cor.2004.08.005) | **风险项依据**。用"某堆栈预期额外移位次数"的估计量做放置决策，正是本算法 R 项的思想。 |
| Lehnfeld J., Knust S. — *Loading, unloading and premarshalling of stacks in storage areas: Survey and classification* | 2014 | European Journal of Operational Research 239(2):297–312 | [10.1016/j.ejor.2014.03.011](https://doi.org/10.1016/j.ejor.2014.03.011) | 辅助。堆栈阻挡/移位问题的理论分类，佐证"外层挡内层→移位"建模。 |
| Zhang C. 等 — *A Simulation-Based Multiple-Objective Optimization for Designing K-Stacks Autonomous Valet Parking Lots* | 2025 | Journal of Advanced Transportation | [10.1155/atr/9322602](https://doi.org/10.1155/atr/9322602) | 辅助。纵深(k-stacks)停车必然产生 relocation，佐证本项目"纵深移位"问题真实且当前。 |

**文献已有 vs. 本项目适配（务必区分，不冒充）**：
- **文献已有**：多准则加权和评分 + min–max 归一化的选点框架（Abdeen 2021）；"按预期移位次数决策"的思路（Kim & Hong 2006）。
- **本项目适配/新增**：Abdeen 的算法是**在城市里选哪个停车场（inter-lot），五因子是交通拥堵/门口排队/到场距离/可用性/停车费，且完全不含纵深阻挡**；我们把同一"加权归一化评分"机制**搬到场内单个停车场的车位选择（intra-lot）**，并把因子替换为**与纵深阻挡直接相关**的三项（距离 / 预期移位风险 / 结构惩罚）。R 项的"预期移位次数"表达式是我们为本仿真模型定义的，非文献原式。

## 5. 数学定义

设当前空闲候选车位集合为 `A`。对车辆 `v`、时刻 `t`、候选车位 `s∈A`：

**（1）三项原始代价（均"越小越好"）**

- 距离：`D(s) = path_engine.distance_to_spot(s.node_id)`（入口到车位最短路，米）。
- 预期移位风险：

$$
R(s,v,t)=\underbrace{\big|\{u\in \text{inner}(s):\ \text{occupied}(u),\ \widehat{dep}(v)>\widehat{dep}(u)\}\big|}_{v\text{ 挡住的已占内层车}}
+\underbrace{\big|\{o\in \text{outer}(s):\ \text{occupied}(o),\ \widehat{dep}(o)>\widehat{dep}(v)\}\big|}_{\text{挡住 }v\text{ 的已占外层车}}
$$

其中 `inner(s)/outer(s)` 为同纵深组中比 `s` 深 / 浅的车位，预估离场时刻

$$
\widehat{dep}(x)=x.\text{arrival\_time}+\max(x.\text{estimated\_duration},0).
$$

- 结构惩罚：`P(s) = |inner(s)|`（该车位后方更深车位数，静态）。

**（2）候选集内 min–max 归一化**（对应 Abdeen 2021 "the smaller the better"，Eq.4）

对每一项 `X∈{D,R,P}`，令 `lo=min_{s∈A}X(s)`、`hi=max_{s∈A}X(s)`：

$$
\hat X(s)=\begin{cases}0,& hi=lo\ \text{（该项不区分候选）}\\[2pt] \dfrac{X(s)-lo}{hi-lo}\in[0,1],& \text{否则}\end{cases}
$$

非有限值（如不可达车位的 `inf` 距离）记 `\hat X(s)=1`（最差），避免 NaN/inf 传播。

**（3）加权求和与选择**

$$
C(s\mid v,t)=w_d\,\hat D(s)+w_r\,\hat R(s,v,t)+w_p\,\hat P(s),\qquad
s^\*=\arg\min_{s\in A} C(s\mid v,t).
$$

平手判定（tie-break）按 `(C, 原始距离 D, s.depth, s.spot_id)` 升序取第一个，完全确定。
权重 `w_d,w_r,w_p≥0`（沿用 Abdeen 2021"权重表偏好、不强制归一"的设定，仅比值有意义）。

## 6. 伪代码

```
assign(v, t, lot, path_engine):
    A = lot.get_available_spots()
    if A 为空: return (None, "waiting")

    for s in A:
        D[s] = path_engine.distance_to_spot(s.node_id)
        R[s] = 0
        for u in lot.get_inner_spots(s) 且被占:               # v 会挡住的内层车
            if edep(v) > edep(occupant(u)): R[s] += 1
        for o in lot.get_outer_spots(s) 且被占:               # 会挡住 v 的外层车
            if edep(occupant(o)) > edep(v): R[s] += 1
        P[s] = len(lot.get_inner_spots(s))

    D^, R^, P^ = minmax_normalize(D), minmax_normalize(R), minmax_normalize(P)

    best = argmin_{s in A} ( w_d*D^[s] + w_r*R^[s] + w_p*P^[s] )
           以 (代价, D[s], s.depth, s.spot_id) 升序打破平手
    return (best, "assigned")

edep(x) = x.arrival_time + max(x.estimated_duration, 0)     # 预估离场，绝不用真实时长
```

## 7. 输入信息边界（在线合法性自审）

**读取**：`lot.get_available_spots()`、候选与已占车位的 `depth/node_id/spot_type/stack_group_id`、
`lot.get_inner_spots/get_outer_spots`、`lot.vehicles`（取占用车 `arrival_time` 与 `estimated_duration`）、
`path_engine.distance_to_spot`、到达车 `vehicle.estimated_duration`。

**绝不读取** `vehicle.parking_duration`（仿真未来真值）。占用车也只用其 `estimated_duration`
（该车到达时系统即可知的预估，`duration_greedy` 已采用同一量），不构成未来信息泄漏。
测试 `test_does_not_read_real_parking_duration` 固定预估、改变真实停车时长，验证决策不变。

## 8. 参数

| key | 含义 | 类型 | 范围/步长 | 默认 |
|---|---|---|---|---|
| `w_distance` | 距离权重 `w_d` | float | 0.0–3.0 / 0.1 | 1.0 |
| `w_risk` | 阻挡风险权重 `w_r` | float | 0.0–3.0 / 0.1 | 1.5 |
| `w_depth` | 结构惩罚权重 `w_p` | float | 0.0–3.0 / 0.1 | 0.5 |

默认值由中强度权重扫描按多 seed 均值选取（见 §11，不挑单一 seed）。

## 9. 时间复杂度

单次 `assign`：两趟遍历候选集（≤N），每候选做同组内层/外层扫描 O(g)（g=纵深组深度，常数，通常 2–3）。
故单次 `O(N·g)≈O(N)`，归一化与选优各 `O(N)`。N≈100 时每次分配为微秒级，整场仿真开销可忽略。

## 10. 与现有算法的区别

| 算法 | 机制 | 与 risk_scoring 的区别 |
|---|---|---|
| `nearest` | 只选最近 | risk_scoring 在 `w_r=w_p=0` 时**退化为它**（见 §12 性质）；否则额外权衡风险与结构。 |
| `greedy` | 硬优先级 tier（独立→外层→里层），组内最近 | greedy 是离散分层、无"距离↔风险"折中；risk_scoring 连续权衡，近纵深位可胜过远独立位。 |
| `duration_greedy`（主方法） | 硬 tier + 预估时长二值短/长分流 + 自适应中位数阈值 | 二者都用预估时长，但 duration_greedy 用**硬阈值分层**决定内外层；risk_scoring 用**连续的预期移位次数**作为一项代价，与距离/结构同台加权，无优先级绝对化。 |
| `departure_greedy` | 最近可用（忽略阻挡） | 同 nearest 类，无风险项。 |
| `peak_offpeak_fusion` | 融合示例：按占用率切换两个子算法 | 那是**融合类型**（切换子策略）；risk_scoring 是**单算法单评分函数**，不切换、不组合。 |
| `mosa`（算法一，离线） | NSGA-II 离线全信息多目标优化，`prepare()` 阶段对完整需求求 Pareto 前沿，`assign()` 查表 | **信息条件不同，不构成重复**：mosa 读未来到达与真实 `parking_duration`，自我定位为"离线上界参考基准"；risk_scoring 是**在线**算法，只用当前状态与预估离场，单次 `O(N)` argmin，无迭代无种群。二者一个是上界参照、一个是可部署在线策略。 |

> 两者都含"多目标"字样，但机制与信息类别完全不同：mosa = 离线 + 元启发式(NSGA-II) + 种群迭代求 Pareto 前沿；
> risk_scoring = 在线 + 单次贪心 argmin + 加权归一化评分。另注：mosa 有规模保护 `MAX_SPOTS=60`，
> 在本项目约 100 车位的目标规模下会跳过 NSGA-II 回退为贪心规则，故未纳入 §11 的 100 车位对比实验。

结论：risk_scoring 与网站现有 8 个算法**均不等价**（既非改名重复，机制也不同），符合"新增且不重复"的硬约束。
其中与 `mosa` 尤需区分：二者名称都涉及"多目标"，但 mosa 属**离线全信息上界基准**，risk_scoring 属**在线可部署策略**，
二者应分栏比较而非同栏竞争。

## 11. 第一版实验结果

**设置**：100 车位（50 独立 + 25 个 2 深纵深组）；低/中/高需求 = 60/100/140 辆；
每档 5 个 seed（42–46）取均值；**同一 seed 下四个策略喂完全相同的需求序列**（公平对比）。
复现：`python scripts/exp_risk_scoring.py`。原始数据 `outputs/exp_risk_scoring_raw.csv`，
汇总 `outputs/exp_risk_scoring_summary.md`。

### 低需求（60 辆）

| 策略 | 满足率 | 利用率 | 移位次数 | 移位距离(m) | 行驶距离(m) | 平均等待(s) | 拒绝数 |
|---|---|---|---|---|---|---|---|
| nearest | 1.000 | 0.088 | 12.0 | 228 | 1779 | 0.0 | 0.0 |
| greedy | 1.000 | 0.089 | 0.0 | 0 | 2989 | 0.0 | 0.0 |
| duration_greedy | 1.000 | 0.089 | 0.0 | 0 | 2989 | 0.0 | 0.0 |
| **risk_scoring** | 1.000 | 0.088 | **0.0** | **0** | **2226** | 0.0 | 0.0 |

### 中需求（100 辆）

| 策略 | 满足率 | 利用率 | 移位次数 | 移位距离(m) | 行驶距离(m) | 平均等待(s) | 拒绝数 |
|---|---|---|---|---|---|---|---|
| nearest | 1.000 | 0.148 | 20.0 | 403 | 4339 | 0.0 | 0.0 |
| greedy | 1.000 | 0.149 | 0.0 | 0 | 7949 | 0.0 | 0.0 |
| duration_greedy | 1.000 | 0.149 | 0.0 | 0 | 7949 | 0.0 | 0.0 |
| **risk_scoring** | 1.000 | 0.148 | **0.2** | **4** | **5588** | 0.0 | 0.0 |

### 高需求（140 辆）

| 策略 | 满足率 | 利用率 | 移位次数 | 移位距离(m) | 行驶距离(m) | 平均等待(s) | 拒绝数 |
|---|---|---|---|---|---|---|---|
| nearest | 1.000 | 0.208 | 27.2 | 673 | 7769 | 0.0 | 0.0 |
| greedy | 1.000 | 0.210 | 0.0 | 0 | 13322 | 0.0 | 0.0 |
| duration_greedy | 1.000 | 0.210 | 0.0 | 0 | 13220 | 0.0 | 0.0 |
| **risk_scoring** | 1.000 | 0.209 | 1.8 | 49 | **10043** | 0.0 | 0.0 |

### 结论（如实记录，含不占优处）

1. **满足率/利用率/等待/拒绝四项在本设置下无法区分策略**：100 车位对 60–140 辆车（6 小时、
   停车 10 分钟–2 小时）容量始终充裕，四策略均为满足率 1.000、利用率相同、零等待零拒绝。
   要让这些指标产生区分，需提高需求强度或缩小车位数（列入后续实验）。
   **因此本版有效区分指标是「移位次数/移位距离」与「行驶距离」。**
2. **risk_scoring 取得了 nearest 与 greedy 族之间的帕累托折中**：
   - 对比 `nearest`：移位次数从 12.0/20.0/27.2 降到 **0/0.2/1.8**，移位距离从 228/403/673 m 降到 **0/4/49 m**；代价是行驶距离更高。
   - 对比 `greedy` / `duration_greedy`：在同为零（或近零）移位的前提下，行驶距离**低约 25–30%**
     （低 2226 vs 2989，中 5588 vs 7949，高 10043 vs 13322/13220）。
   这正是加权多准则法期望的效果——不把任一目标绝对化，而是在冲突目标间取折中。
3. **不占优之处（如实保留）**：中需求下 risk_scoring 出现 0.2 次、高需求下 1.8 次移位（greedy 族为 0）。
   原因是占用率升高后候选集变小，有时**所有**候选都带风险，归一化后风险项无法区分，选择被距离项主导。
   这是 min–max 归一化"候选集内相对比较"的固有性质（见 §13 缺点 2）。
4. **行驶距离绝不低于 nearest**（1779/4339/7769），符合预期：nearest 是距离项的下界。

### 权重扫描（中需求，5 seed 均值）

| (w_d, w_r, w_p) | 满足率 | 利用率 | 移位次数 | 移位距离(m) | 行驶距离(m) |
|---|---|---|---|---|---|
| (1, 0, 0) | 1.000 | 0.148 | 19.6 | 386 | 4357 |
| (1, 1, 0) | 1.000 | 0.148 | 18.4 | 490 | 4500 |
| **(1, 1.5, 0.5) ← 默认** | 1.000 | 0.148 | **0.2** | **4** | **5588** |
| (1, 2, 1) | 1.000 | 0.148 | 0.0 | 0 | 5680 |
| (0.5, 2, 0.5) | 1.000 | 0.148 | 0.0 | 0 | 5680 |
| (1, 3, 1) | 1.000 | 0.148 | 0.0 | 0 | 5680 |
| (0, 1, 0) | 1.000 | 0.148 | 18.4 | 490 | 4500 |

**两点验证**：

- **退化性质得到实证**：`(1,0,0)`（即 `w_r=w_p=0`）得到 19.6 次移位 / 行驶 4357 m，与 `nearest`
  的 20.0 次 / 4339 m 实质一致 —— 与 §12 的理论退化性质吻合（微小差异来自 tie-break 细节）。
- **默认权重的选取依据（当前引擎下如实记录）**：`(1, 1.5, 0.5)` 平均移位 0.2 次、移位距离 4 m、
  行驶 5588 m；严格零移位的 `(1, 2, 1)` 行驶 5680 m。二者移位几乎相同，`(1, 1.5, 0.5)` 行驶
  少 92 m，故**保留为默认值**（原快照在旧引擎下该组合为零移位；接入当前引擎后为近零移位，
  本版如实改写选取理由）。该选择基于 5 个 seed 的均值，**未挑选特定 seed**。

## 12. 优点

1. **机制可解释**：每个候选位的代价可拆成"距离/风险/结构"三项，答辩/综述都讲得清。
2. **可调**：三个自然权重覆盖从"纯最近"到"纯避阻挡"的连续谱，便于做敏感性分析。
3. **有明确退化性质**（易验证、好写论文）：
   - `w_r=w_p=0` → 等价 `nearest`；
   - `w_d=w_p=0` → 纯预期移位最小；
   - 三权相等 → 三目标均衡折中。
4. **在线合法**：只用当前状态与预估离场，无未来信息泄漏。
5. **轻量**：O(N)，无重依赖，不改仿真器与网页框架，注册即用。
6. **有文献根**：加权归一化评分（Abdeen 2021）+ 预期移位估计（Kim & Hong 2006）。

## 13. 缺点

1. **权重需调**：默认权重来自单一仿真布局与分布的均值，换场景可能需重调（多准则法通病）。
2. **min–max 依赖候选集**：归一化尺度随当前空闲集变化，跨时刻的绝对代价不可直接比较（本算法只需同一时刻内比较，不受影响，但解释时需说明）。
3. **风险项为一步前瞻**：R 只估计"当前占用 + 本车"这一步引发的移位，不预测后续到达车的连锁阻挡（可作后续改进）。
4. **平手退化**：当三项在候选集内都不可区分时，退化为按距离的确定性选择（合理但非"最优"）。

## 14. 后续可能改进

1. **权重自适应/学习**：按占用率或时段动态调 `w_r`（高峰更避阻挡），或用离线 CP-SAT 结果拟合权重。
2. **多步前瞻的风险**：用到达率的排队模型（Abdeen 2021 的 M/M/c 可用性思路）估计未来阻挡概率，替换一步 R。
3. **纳入更多因子**：加入"车位类型匹配""缓冲位可用性"等项，向 Abdeen 五因子对齐。
4. **与融合框架结合**（需先向组长报备"新融合类型"）：把 risk_scoring 作为高峰子算法接入 `CompositeStrategy`。

## 15. 参考链接

- Abdeen, Nemer & Sheltami (2021), Sensors 21(9):3148 — https://doi.org/10.3390/s21093148 ；开放全文 https://pmc.ncbi.nlm.nih.gov/articles/PMC8125470/
- Kim & Hong (2006), Comput. Oper. Res. 33(4):940–954 — https://doi.org/10.1016/j.cor.2004.08.005
- Lehnfeld & Knust (2014), EJOR 239(2):297–312 — https://doi.org/10.1016/j.ejor.2014.03.011
- Zhang et al. (2025), J. Adv. Transportation — https://doi.org/10.1155/atr/9322602
