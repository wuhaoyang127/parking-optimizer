# 阶段D 新算法接入：算法一 MOSA（多目标智能分配）

## 目标与用户可见结果

把用户提供的「算法一」MOSA（Multi-Objective Smart Allocation，NSGA-II 离线全信息多目标优化）接入系统：

- 网页策略下拉框出现「MOSA 多目标优化（离线）」，参数控件自动渲染（种群规模/进化代数/场景模式/评估等待上限）；
- 与在线策略一起参与「全部对比」与加权/字典序排名；
- 明确标注为「离线全信息对照基准」（与 CP-SAT 定位一致），对比时作为上界参考。

## 算法来源

- `D:\罚函数\停车场\新算法接入\算法一\mosa_full.py`（原算法代码）
- `D:\罚函数\停车场\新算法接入\算法一\新算法接入文档1.txt`（接入说明：场景A/B 移位、时间片碰撞硬约束、f1 总行驶时间/f2 总行驶距离/f3 利用率均衡、NSGA-II、支持拒绝 -1、场景权重）

## 接入方式

离线预分配策略（prepare 钩子）：

1. `BaseStrategy` 新增可选 `prepare(vehicles, parking_lot, path_engine)` 钩子（默认空实现）；
2. `SimulationEngine.run()` 开头自动调用（未实现自动跳过，向后兼容）；
3. `MosaStrategy` 重写 `prepare`：NSGA-II 对完整需求做三目标优化，缓存 `{vehicle_id: spot_id}` 计划；
4. `assign` 查表执行：计划车位可用→分配，被占→waiting（引擎重试），无计划→回退贪心；
5. 规模保护：车位数 > 60 或车辆数 > 120 时跳过优化回退贪心，保证网页交互不卡死。

## 范围

### 包含

- `src/parking_opt/strategies/mosa.py`：MosaStrategy（NSGA-II 轻量实现：非支配排序/拥挤距离/锦标赛/均匀交叉/修复变异 + 轻量时间轴评估器含纵深移位估计 + 场景权重选解）；
- `src/parking_opt/strategies/baselines.py`：BaseStrategy.prepare 钩子；
- `src/parking_opt/simulation/engine.py`：run() 调用 prepare；
- `src/parking_opt/strategies/__init__.py`：登记 MosaStrategy；
- `tests/test_mosa.py`：注册/无参构造/查表分配/规模保护/prepare 钩子/端到端对比；
- `docs/新算法接入说明.md`：补充 prepare 钩子接入说明；
- `PROJECT_STATUS.md`：里程碑与最近变更。

### 不包含

- 原 MOSA 的时间片路口碰撞检测（项目引擎已用 SimPy 事件时序 + 缓冲位移位建模，效果等价）；
- 融合语义变更（仍按离线基准接入，不参与在线信息边界内的公平对比）；
- UI 页面代码改动（新算法经注册表自动出现，无需改页面）。

## 验收

- pytest 62 passed（原有 51 + 新增 11）；
- 启动包自检通过（126 个关键文件）；
- 端到端对比：MOSA 满足率显著高于在线策略（离线全信息上界参考）。
