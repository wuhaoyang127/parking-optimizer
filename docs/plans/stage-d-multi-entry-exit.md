# 阶段D 多入口多出口改造（entry/exit 随机种子分配）

> 变更类型：阶段 B 冻结定义变更（入口原定义为「唯一或主要节点」）。
> 本计划按 AGENTS.md 4.2 变更流程执行：变更说明已获用户批准（2026-08-28）。

## 目标与用户可见结果

停车场布局支持**多个入口（entry）与多个出口（exit）**：

- 布局 JSON 可出现任意多个 `type="entry"` / `type="exit"` 节点（旧单入口文件仍可用）；
- 需求生成时，为每辆车**独立随机分配入口与出口**（同一随机种子可复现，入口与出口可不同）；
- 需求序列 JSON 可选带 `entry_id` / `exit_id`（缺省时走默认口，旧文件兼容）；
- 仿真时车辆从指定入口入库、从指定出口离场；策略「距离」按该车入口计算；
- 网页布局图渲染全部入口与出口；导入校验放宽为「至少一个入口」。

## 当前状态

- 分支 `stage-d-deliver`，本地与远端同步于 `ccb7d1a`（验收记录提交）；
- 现状：`PathEngine.entry_id` 单值（多入口静默覆盖）；`NodeType.EXIT` 已定义但从未使用；
  离场路径回到入口；`Vehicle` 无入口/出口字段；`generate_demand` 不涉及口分配。
- 前置：算法二 risk_scoring 已验收；测试基线 91 passed。

## 范围

### 包含

- `Vehicle.entry_id` / `Vehicle.exit_id` 可选字段；
- `PathEngine` 多入口/多出口解析与默认口规则（向后兼容）；
- `generate_demand` 随机分配入口/出口（seed 派生独立随机流，等概率）；
- 需求序列 JSON 导出/导入 `entry_id` / `exit_id`（schema 仍 v1，字段可选）；
- 仿真引擎入库/离场按车辆口；策略距离按车辆入口；
- UI：导入校验、viz 渲染、动态路径、生成需求传口列表；
- 新增 `tests/test_multi_entry.py`；
- 文档：布局格式说明、模型文档、算法文档、PROJECT_STATUS。

### 不包含

- 离场动态选最近出口（出口固定由需求指定，用户已确认）；
- 入口/出口的分流权重配置（本次等概率，UI 无新增控件）；
- 历史实验重跑（默认单口布局行为不变，见「验证与验收」）；
- CP-SAT 离线基准的多口适配（该基准为小规模理论对照，继续用单口假设，文档标注）。

## 关键定义与假设

1. **默认入口**：优先取 `id == "ENTRY"` 的 entry 节点；不存在则取布局中第一个 entry 节点。车辆 `entry_id` 为空时用默认入口。
2. **默认出口**：优先取 `id == "EXIT"` 的 exit 节点；不存在则取第一个 exit 节点；布局**没有 exit 节点**时回退为默认入口（旧布局兼容，离场回入口）。
3. **随机分配**：`generate_demand(entry_ids=None, exit_ids=None, seed=42)`：
   - `entry_ids` / `exit_ids` 为 None 或长度 ≤1 时，全部车辆用默认口（**不消耗任何随机数**，保证旧实验完全可复现）；
   - 长度 ≥2 时，用独立派生随机流 `random.Random(seed + 100_003)` 分配入口、`random.Random(seed + 200_003)` 分配出口，等概率；主随机数流不变。
4. **信息边界**：`entry_id` / `exit_id` 是需求输入的已知属性，不是未来真值，在线策略可读。
5. **距离语义**：策略中的「距离」= 该车**入口**到候选车位的最短路径距离；入库行驶与该入口绑定；离场行驶到该车出口（离场距离不计入现有总行驶距离指标，口径不变）。
6. **导入校验**：至少一个 entry 节点（旧规则「必须有 ENTRY」放宽）；每个车位必须至少能从默认入口可达且能返回默认入口；exit 节点存在时不做强连通要求（仅用于离场路径，若某车出口不可达则该车离场回退默认入口，记 DEGRADATION）。

## 里程碑

- [x] M1 领域模型与 PathEngine（文件：`domain/spot.py`、`routing/path_engine.py`；验证：新单测 + 旧 91 项通过）
- [x] M2 需求生成与需求 IO（文件：`simulation/arrival.py`、`io/demand_io.py`；验证：同 seed 复现、旧文件导入、导出往返）
- [x] M3 仿真引擎按车辆口进出（文件：`simulation/engine.py`；验证：多口布局事件路径正确、不可达回退）
- [x] M4 策略距离按车辆入口（文件：`strategies/baselines.py`、`greedy.py`、`mosa.py`、`risk_scoring.py`；验证：回归 + 策略替身兼容）
- [x] M5 UI（文件：`ui/pages.py`、`ui/common.py`、`viz.py`；验证：AppTest 导入校验、布局图、动态路径）
- [x] M6 文档与全量验证（文档 5 件 + `tests/test_multi_entry.py` + 全套 pytest + 自检 + 提交推送）

## 详细实施步骤

### M1 领域模型与 PathEngine

1. `Vehicle` 增加字段 `entry_id: Optional[str] = None`、`exit_id: Optional[str] = None`（dataclass 尾部追加，无参兼容）。
2. `PathEngine.__init__` 收集 `self._entry_ids`、`self._exit_ids`（按节点遍历顺序）。
3. `PathEngine._default_entry_id()`：`"ENTRY" in entry_ids` → 取之，否则 `entry_ids[0]`（无入口抛 ValueError，保持原行为）。
4. `PathEngine._default_exit_id()`：`"EXIT" in exit_ids` → 取之，否则 `exit_ids[0]`；`exit_ids` 为空返回 `None`（调用方回退入口）。
5. 保留 `entry_id` property（返回默认入口）与 `distance_to_spot(node_id)` 单参签名；新增 `distance_to_spot(node_id, entry_id=None)` 默认参数。
6. 新增 `entry_ids` / `exit_ids` / `resolve_exit(exit_id)` 等只读接口；`shortest_distance`/`shortest_path` 不变。

### M2 需求生成与需求 IO

1. `generate_demand(..., entry_ids=None, exit_ids=None)`：按「关键定义 3」分配；Vehicle 构造带 `entry_id`/`exit_id`。
2. `demand_io.export_demand_json`：车辆对象带 `entry_id`/`exit_id` 时输出对应字段（None 不输出，保持文件最简）。
3. `demand_io.parse_demand_json`：读取可选 `entry_id`/`exit_id`（非空字符串，否则 None）；schema_version 不变。

### M3 仿真引擎

1. `_entry_for(vehicle)`：`vehicle.entry_id` 合法（在 `path_engine.entry_ids`）→ 用之，否则默认入口。
2. `_exit_for(vehicle)`：`vehicle.exit_id` 合法（在 `path_engine.exit_ids`）→ 用之；否则默认出口；无默认出口 → 默认入口（旧布局）。
3. 入库不可达检查与入库路径用 `_entry_for(vehicle)`；离场路径（无阻挡/有阻挡两处）用 `_exit_for(vehicle)`；
   `SPOT_ENTRY` 的 `drive_distance` 仍记入库距离（指标口径不变）。
4. 出口不可达回退：离场路径为空（不连通）时回退默认入口路径并记 `DEGRADATION` 事件（metadata 说明）。

### M4 策略距离

1. 各策略 `assign`/`prepare` 中取 `entry = getattr(vehicle, "entry_id", None) or path_engine.entry_id`，`distance_to_spot(s.node_id, entry)`。
2. `mosa.py` 的 `prepare` 逐车按其入口累计 f1/f2；`risk_scoring.py` 的 D 项同理。
3. 测试替身 `distance_to_spot(self, node_id)` 保持单参可用（新代码传第二参数会崩 → 替身需改为 `distance_to_spot(self, node_id, entry_id=None)`，同时更新 `tests/test_strategies_regression.py`、`tests/test_risk_scoring.py` 中的替身）。

### M5 UI

1. `ui/pages.py` 导入校验：`entry_nodes = [n for n in data["nodes"] if n["type"] == "entry"]`，空则报错；删掉「必须有 ENTRY」；连通性检查改用默认入口（`pe_check.entry_id` 已自动遵循默认规则）。
2. `ui/common.py`：`build_layout_from_json` 已通用（type→NodeType 映射含 entry/exit，无需改）；
   动态路径/时间线路径显示中 `pe.entry_id` 处改为「车辆入口优先，否则默认入口」；生成需求调用处传入当前布局的 entry/exit 列表（内置布局均为单 ENTRY，不新增 UI 控件）。
3. `viz.py`：入口改为遍历全部 entry 节点渲染；新增出口渲染（全部 exit 节点，用方块标记 + 「出口」文本）。

### M6 文档与验证

1. `docs/布局导入格式说明.md`：多入口/多出口示例 + 字段说明 + 默认口规则；
2. `docs/model/01_问题定义与假设.md`、`02_符号变量与数学模型.md`：入口/出口定义更新（≥1 个，默认 ENTRY/EXIT，车辆可指定）；
3. `docs/algorithms/risk_scoring.md`：D 项距离语义更新；`docs/algorithms/mosa.md`（如存在）同步；
4. `PROJECT_STATUS.md`：里程碑/唯一下一步/最近变更；
5. 新增 `tests/test_multi_entry.py`（目标 ≥8 项：多入口解析与默认口、多出口解析与回退、同 seed 分配复现、旧文件兼容、引擎多口进出、策略按车辆入口选位、离场到出口、不可达回退）；
6. 全套 `py -m pytest -q` + `py scripts/validate_starter_package.py` + AppTest（如环境可用）。

## 验证与验收

| 检查 | 命令 | 预期 |
|---|---|---|
| 新单测 | `py -m pytest tests/test_multi_entry.py -q` | 全部通过 |
| 全套回归 | `py -m pytest -q` | ≥91 项全部通过（不破坏旧行为） |
| 自检 | `py scripts/validate_starter_package.py` | 通过（只读） |
| 历史实验 | 不重跑 | 默认单口布局行为不变，结论不受影响 |

## 风险与降级

- **向后兼容**：所有旧布局/旧需求/旧测试必须原样通过；`distance_to_spot` 默认参数、默认口规则保证。
- **随机流污染**：入口/出口分配使用独立派生 Random 实例，主随机流不变；旧单口实验可复现。
- **出口不可达**：布局有 exit 但某车出口不连通 → 离场回退默认入口 + DEGRADATION，不崩溃。
- **CP-SAT 基准**：继续单口假设（理论对照），在文档中标注为已知限制。
- **回滚**：tag `backup-before-multi-entry-exit-20260828`，`git reset --hard` 即回退。

## 决策日志

- 日期：2026-08-28
- 决策：入口与出口都由随机种子在需求生成时独立分配（可不同），等概率；出口不做离场动态选择。
  - 备选：入口随机 + 离场动态最近出口；入口随机 + 出口固定。
  - 理由：用户明确要求「进入入口与出去出口不一定相同，可根据实际情况改变」，且要求可复现（种子驱动）。
  - 证据：用户 2026-08-28 会话确认；本计划「关键定义 3」。

## 进度记录

- 日期：2026-08-28
- 已完成：备份 tag、ExecPlan 建立。
- 实际验证：无。
- 问题：无。
- 下一步：M1 实施。

- 日期：2026-08-28
- 已完成：M1–M6 全部实施完毕并验证。
  - 代码：`domain/spot.py`（Vehicle.entry_id/exit_id）、`routing/path_engine.py`（多入口/出口+默认口）、
    `simulation/arrival.py`（seed 派生随机流分配口）、`simulation/engine.py`（按车辆口进出+出口不可达回退+DEGRADATION+事件元数据）、
    `io/demand_io.py`（entry_id/exit_id 可选字段）、策略 4 件（按车辆入口计距离）、
    `ui/pages.py`（导入校验放宽+生成传口列表）、`ui/common.py`（动画按车辆入口）、`viz.py`（多入口/出口渲染）。
  - 文档：布局格式说明（多口示例+规则）、模型 01/02（entry_v/exit_v）、risk_scoring（距离语义）、PROJECT_STATUS。
  - 测试：新增 `tests/test_multi_entry.py`（10 项）；全套 101 passed（原 91 + 新 10，无回归）。
- 实际验证：`py -m pytest -q` → 101 passed；`py scripts/validate_starter_package.py` → 通过（138 文件）。
- 问题：历史实验未重跑（默认单口布局行为不变，按计划不重跑）。
- 下一步：提交推送，待用户验收。
