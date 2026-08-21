# 阶段D 反馈优化第二批：需求时序可视化 + 加权多指标排名

## 目标与用户可见结果

完成用户在 Streamlit Cloud 部署后提出的两条反馈：

1. **需求时序可视化与可复用**：
   - 指标分析页新增「需求时序分布」区块：到达/离开按时段（小时）分组条形图；
   - 同一区块新增「车辆明细表」：每辆车的到达时间、分配车位、进入车位时间、离场时间、等待时长、状态（正常/拒绝），可下载 CSV；
   - 需求序列可导出为 JSON 文件，下次仿真可导入复用（相同种子/相同序列结果可复现）。
2. **加权多指标排名**：
   - 指标分析页新增排序模式切换：字典序（现有，保留）/ 加权评分（新增）；
   - 加权评分模式提供 7 个指标的「权重百分条」，总和应为 100（不为 100 时自动按比例归一化并提示）；
   - 指标先 min-max 归一化（min 方向指标反向），再按权重加权求和，输出多算法综合排名表与推荐策略。

## 当前状态

- 分支 `stage-d-deliver`，工作区干净，测试 24 passed；
- 备份 tag：`backup-before-feedback-round2-20260821`（2026-08-21）；
- 已验证：相同种子三次运行指标完全一致（核心引擎可复现）；
- 现有相关代码：
  - `src/parking_opt/simulation/arrival.py::generate_demand`：按种子生成需求（双峰分布），种子复现已具备；
  - `src/ui/common.py`：`PRIORITY_METRICS`（7 指标）、`DEFAULT_PRIORITY`、`_plot_radar`（min-max 归一化+反向）、`run_single`、`build_timeline`；
  - `src/ui/pages.py::render_settings`：运行仿真、compare_all 循环、保存 `sim_events_raw`；
  - `src/ui/pages.py::render_metrics_page`：字典序排序 + 多策略对比表 + 雷达图 + CSV 下载；
  - `src/parking_opt/evaluation/metrics.py::compute_metrics`：指标计算。

## 范围

### 包含

- 新模块 `src/parking_opt/io/demand_io.py`：需求序列 JSON 导出/导入（schema_version=1，含元数据与车辆列表）；
- 新模块 `src/parking_opt/evaluation/ranking.py`：加权评分排名（纯函数，归一化+方向处理+权重归一化）；
- 仿真设置页：需求数据源切换（自动生成 / 导入 JSON），导入后摘要展示；
- 指标分析页：排序模式切换、权重百分条、加权排名表、需求时序条形图、车辆明细表、JSON/CSV 下载；
- 单元测试 `tests/test_demand_io.py`、`tests/test_ranking.py`；
- 更新 `PROJECT_STATUS.md`（计划链接、里程碑、唯一下一步、最近变更）。

### 不包含

- 不修改任何现有策略的 `assign` 逻辑与 PARAMS；
- 不修改核心指标定义（阶段 B 冻结口径）；
- 不引入新第三方依赖；
- 不改动登录/反馈/布局导入等其他页面；
- 不做真实停车场数据接入（真实数据仍待用户提供）。

## 关键定义与假设

### 需求序列 JSON 格式（schema_version=1）

```json
{
  "schema_version": 1,
  "generated_at": "2026-08-21T10:00:00",
  "source": "generated",
  "seed": 42,
  "generator_params": {
    "total_vehicles": 60, "sim_duration": 21600,
    "duration_min": 600, "duration_max": 7200,
    "peak_ratio": 0.6, "error_ratio": 0.3
  },
  "vehicles": [
    {"vehicle_id": "V0001", "arrival_time": 123.4,
     "parking_duration": 1800.0, "estimated_duration": 1700.0}
  ]
}
```

- 导入时校验：schema_version 为整数 1；vehicles 为非空数组；每辆车 `vehicle_id` 为非空字符串、`arrival_time`/`parking_duration`/`estimated_duration` 为有限非负数；错误信息指出具体字段。
- 导入后车辆按 `arrival_time` 排序，`Vehicle` 对象重建；`estimated_duration` 缺省时取 `parking_duration`。
- 导入序列在多种子（n_runs）循环中保持不变（只改变引擎/策略随机性），保证「同一需求序列」语义。

### 加权评分

- 指标集合与 `PRIORITY_METRICS` 一致（7 个）；
- 对每个指标在参与对比的策略集合内做 min-max 归一化到 [0,1]：max 方向 `(v-min)/(max-min)`，min 方向 `1-(v-min)/(max-min)`；当 max==min 时该指标所有策略记 0.5（无区分度）；
- 综合得分 = Σ(归一化值 × 归一化后权重)；权重总和>0 时按总和归一化（即总和≠100 也自动按比例归一，页面提示）；
- 排名按综合得分降序；得分保留 4 位小数。

### 车辆明细表字段（从事件日志提取）

车辆编号、到达时间、分配车位、进入车位时间、离场开始时间、等待时长(s)、状态（正常/拒绝）。离场时间取第一个 `departure` 事件时间；拒绝状态取 `rejected` 事件（无离场时间显示 "-"）。

## 里程碑

- [x] M0 打备份 tag + 建 ExecPlan + 更新 PROJECT_STATUS 指向新计划
  - 文件：git tag、`docs/plans/stage-d-feedback-round2.md`、`PROJECT_STATUS.md`
  - 验证：`git tag --list "backup-*"` 含新 tag；状态文件 front matter 解析正常
- [x] M1 `src/parking_opt/io/demand_io.py` 导出/导入
  - 验证：`py -c` 往返一致性冒烟（30 辆往返一致）
- [x] M2 `src/parking_opt/evaluation/ranking.py` 加权评分
  - 验证：手工构造小例子得分与排名正确
- [x] M3 单元测试 + 回归全绿
  - 验证：`py -m pytest -q` 全绿（49 passed）
- [x] M4 仿真设置页导入数据源 + 导出 JSON
  - 验证：AppTest 设置页导入模式无异常，file_uploader 出现
- [x] M5 指标分析页排序模式切换 + 权重百分条 + 加权排名表
  - 验证：AppTest 字典序/加权评分两种模式渲染无异常
- [x] M6 指标分析页需求时序条形图 + 车辆明细表 + 下载
  - 验证：AppTest 渲染无异常，3 个下载按钮（明细 CSV/需求 JSON/排名 CSV）
- [x] M7 全量验证 + 状态收尾
  - 验证：`py -m pytest` 全绿；`py scripts/validate_starter_package.py` 只读自检通过；更新 PROJECT_STATUS 与 ExecPlan

## 详细实施步骤

1. `src/parking_opt/io/demand_io.py`：
   - `export_demand_json(vehicles, seed=None, source="generated", generator_params=None, generated_at=None) -> str`
   - `parse_demand_json(text: str) -> tuple[list[Vehicle], dict]`（返回 (vehicles, metadata)，校验失败抛 `ValueError` 并指明字段）
2. `src/parking_opt/evaluation/ranking.py`：
   - `weighted_rank(metrics_list, weights: dict[str, float]) -> list[dict]`：返回带 `weighted_score` 和 `rank` 的列表（降序）；
   - `normalize_weights(weights) -> dict[str, float]`；
   - 内部使用与 `PRIORITY_METRICS` 等价的指标方向表（本模块不依赖 UI，用字段名+方向）。
3. `src/ui/common.py`：
   - 新增 `DEMAND_DEFAULT_WEIGHTS`（7 指标默认权重，总和 100）；
   - 新增 `build_demand_histogram(events_raw)`（返回 plotly fig：按小时分桶的到达/离场分组柱状图）；
   - 新增 `build_vehicle_detail_rows(events_raw)`（返回 list[dict]）；
   - 新增 `weighted_rank_df(all_m, weights)`（封装 ranking.weighted_rank 成 DataFrame）。
4. `src/ui/pages.py`：
   - `render_settings`：新增「需求数据源」radio（自动生成/导入 JSON）；导入 `file_uploader` + `parse_demand_json` 解析摘要；运行仿真时按数据源取 vehicles；`session_state.sim_vehicles` 保存本次 vehicles；`sim_demand_meta` 保存元数据；提供示例 JSON 下载；
   - `render_metrics_page`：多策略对比区新增「排序模式」radio（字典序/加权评分）；加权模式渲染 7 个权重 `number_input`（0-100 step 5），总和提示与自动归一化；排名表列加「综合得分」；新增「需求时序分布」与「车辆明细」两个 expander；JSON/CSV 下载按钮。
5. 测试：
   - `tests/test_demand_io.py`：往返一致；非法 JSON/缺字段/负值报错；estimated_duration 缺省回退；排序。
   - `tests/test_ranking.py`：权重归一化（总和≠100）；min 指标反向；max==min 记 0.5；排名顺序；空输入。
6. 收尾：`py -m pytest`、启动自检、`git commit`、更新 `PROJECT_STATUS.md`。

## 验证与验收

- `py -m pytest -q`（全部通过，含新增测试）；
- `py scripts/validate_starter_package.py`（只读自检）；
- 本地 `py -m streamlit run app.py` 启动无异常；手动冒烟：仿真设置→导入示例 JSON→运行→指标分析页查看排序切换/权重/条形图/明细表/下载。
- 用户验收确认后进入 Streamlit Cloud 重新部署。

## 风险与降级

- 导入 JSON 不合法：页面报错并拒绝运行，提示具体字段；不静默回退到自动生成。
- 权重全为 0：视为无效配置，回退默认权重并提示。
- 事件日志为空（未运行仿真）：时序图/明细表区块显示提示，不报错。
- compare_all 模式仅保存主方法（duration_greedy）事件日志：明细表/时序图标注「按主方法事件日志」，避免误读。

## 决策日志

- 2026-08-21：排序方式采用「并存切换」，保留字典序；用户已确认。
- 2026-08-21：需求序列导出/导入采用 JSON 单文件（含元数据）；用户已确认。
- 2026-08-21：时序图与车辆明细放在指标分析页新增区块；用户已确认。
- 2026-08-21：权重总和≠100 时自动按比例归一化并提示（最友好、不阻塞）。

## 进度记录

- 2026-08-21：M0 完成（备份 tag `backup-before-feedback-round2-20260821`、本计划、PROJECT_STATUS 指向）。
- 2026-08-21：M1-M3 完成。新增 `demand_io.py`（JSON 往返/校验）、`ranking.py`（归一化+方向+权重归一化）；新增 25 个单元测试，pytest 49 passed。
- 2026-08-21：M4-M6 完成。仿真设置页新增需求数据源（自动生成/导入 JSON + 示例下载）；指标分析页新增排序模式切换（字典序/加权评分）、权重百分条（自动归一化）、加权排名表、需求时序条形图、车辆明细表与 JSON/CSV 下载；顺带修复 `_plot_radar` 在策略数少于雷达维度时的索引越界。
- 2026-08-21：M7 完成。AppTest 全页面/两种排序模式/运行仿真数据流均无异常；本地 Streamlit HTTP 200；`validate_starter_package.py` 只读自检通过。

## 最终回顾

两条反馈全部落地：需求时序可视化 + 明细表 + 需求序列 JSON 导出/导入（同种子/同序列可复现），以及指标权重百分条（总和=100、自动归一化）+ 多算法加权排名，与原有字典序并存切换。未改动任何策略逻辑与指标定义；新增依赖为零。等待用户验收后更新 PROJECT_STATUS 状态并部署。
