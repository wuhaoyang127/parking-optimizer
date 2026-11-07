# M2 契约、路径与在线规则说明

## 1. 现实问题

网页不能只展示“某个车位空闲”，还要回答三个问题：该车位在当前停车场内是否真的可分配，
纵深结构会不会导致不可恢复的阻挡，以及从当前入口走过去需要多久。M2 将这三类信息分开，
因此后续接入真实停车场数据或新算法时，不需要重写整个网页。

## 2. 输入、输出与边界

输入为 `DriverRequest + Layout + CostSnapshot + DataSourceStatus`。`DriverRequest` 只含用户在决策时已提供的信息；
`Layout` 描述停车场、车位、纵深组和通道；`CostSnapshot` 是调用方提供的当前边成本快照。
输出为 `Recommendation`，包含主车位、备选车位、解释、路线、算法版本、数据源状态和明确失败码。

M2 只推荐，不创建预约、软锁或占位。输出中的 `claim_status` 固定为
`not_created_m2`，`soft_lock_expires_at` 固定为空。真实数据源未配置或字段缺失时失败关闭，
不会暗中切换到模拟数据。

所有外部时间必须是带时区的 RFC 3339 时间，所有距离、价格和耗时必须是有限数值。布局会
同时检查节点、边、通道区、车位、缓冲位和纵深组的 ID 唯一性、作用域与引用完整性；纵深
深度必须从 1 连续递增。这样错误数据会在进入算法前失败，而不是在运行时变成 `KeyError`。

## 3. 规则与排序

先通过 v1 只读适配器执行既有的占用、纵深入口、缓冲位可恢复性和通路检查。充电要求在 v2
作为新增硬约束。只在全部硬约束通过后按以下词典序选择：

\[
(r_i,\; t_i,\; d_i,\; h_i,\; id_i)
\]

其中 `r_i` 是新增不可恢复风险，`t_i` 是当前动态预计行驶秒数，`d_i` 是距离（米），
`h_i` 是纵深深度，最后用稳定车位 ID 消除并列。词典序意味着先比较前一项，只有相等才比较
后一项，避免不同单位随意加权。

## 4. 路径计算

`RouteCostService` 对当前边成本运行确定性 Dijkstra。队列键依次为 ETA、距离、边 ID 序列和
节点 ID 序列，因此相同输入会得到相同路径。成本快照必须与停车场和布局版本一致，并完整覆盖
全部边；少边、多边或版本不符都会报错。

## 5. 极小例子

入口到 A 位需要 30 秒、到 B 位需要 12 秒。两者均为空闲且可恢复，A 深度 1，B 深度 2。
因为动态 ETA 在深度之前比较，系统选 B。若 B 的入口被前排车辆挡住，则 B 在硬约束阶段淘汰，
系统选择 A，而不是用“更短时间”覆盖不可行事实。

若 v1 在 8 个车位中只完成 3 个评估就到达截止时间，v2 返回
`solver_status=failed` 和 `failure_code=V1_ASSESSMENT_TIMEOUT`，不会把它伪装成“停车场没有
可行车位”。只有完整评估全部车位且确实没有候选时，才返回 `no_feasible_space`。

## 6. 代码入口与验证

- 契约：`src/parking_opt/api/models.py` 与 `schemas/v2/`；
- 模拟数据：`src/parking_opt/api/scenarios.py` 与 `data/synthetic/web-v2/`；
- v1 适配：`src/parking_opt/api/adapters/v1.py`；
- 路径：`src/parking_opt/api/routing.py`；
- 推荐：`src/parking_opt/api/services/online_rule.py`；
- API：`src/parking_opt/api/app.py`；
- 测试：`tests/web_v2/`。

生成契约与固定场景：`python scripts/export_web_v2_contracts.py`。运行 M2 测试：
`python -m pytest tests/web_v2 -q`。
