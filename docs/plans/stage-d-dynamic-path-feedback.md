# 阶段D 动态路径页反馈修复（多口路径/离场/移位动画）

> 用户验收多入口多出口改造后反馈（2026-08-28），其余内容已验收，本计划只修动态路径页三处问题。

## 目标与用户可见结果

动态路径页（页面4）修正并增强：

1. 黄色虚线路径按**该车实际入口**绘制（此前写死默认入口）；
2. 新增**离场动画**：可单独回放车辆从车位到出口的离场过程；
3. 新增**移位动画**：车辆作为移位车时可见其移位轨迹；离场让行时可见让行外层车的移位轨迹（辅助虚线）。

## 当前状态

- `src/ui/pages.py` 的 `render_path_page` / `_draw_charts`：只做入库段（分配→入位）20 帧回放；`hl_path` 用 `sim_pe.entry_id`（默认入口）。
- 引擎事件已带元数据：`spot_entry.entry`、`departure.exit`（无阻挡）；`shift_start` 带 `from_spot/to_spot/reason`。
- 有阻挡的 `departure` 事件未带 `exit`（本次补）。

## 范围

### 包含
- `simulation/engine.py`：有阻挡 DEPARTURE 事件补 `exit` 元数据；
- `ui/common.py`：新增 `build_vehicle_phases`（提取入库/离场/移位路径段）与 `interp_path_segment`；
- `ui/pages.py`：动态路径页阶段选择与按阶段回放；`_draw_charts` 按阶段画路径/插值；
- `viz.py`：`highlight_path_color` 与 `extra_paths` 参数；
- 测试：`tests/test_multi_entry.py` 追加路径段提取/插值单测。

### 不包含
- 多车同时动画、全事件回放；
- 离场等待期间（移位让行）的精确时序动画（按路径匀速插值近似，页面如实标注）。

## 关键定义与假设

- 阶段定义（针对高亮车）：
  - **入库**：`parking_assigned` → `spot_entry`；路径 = `spot_entry.metadata.entry`（缺省默认入口）→ 车位；
  - **离场**：`departure` 事件时刻起；出口 = `departure.metadata.exit`（缺省默认出口/入口）；路径 = 车位 → 出口；
  - **移位**：`shift_start`（该车为移位车）→ 同车最近 `shift_end`；路径 = `from_spot` → `to_spot`；
  - **让行轨迹**（离场阶段的辅助虚线）：`shift_start` 中 `blocked_vehicle == 高亮车` 的移位路径。
- 动画时长：有事件对时用事件时间差；缺结束事件时按路径长度 ×0.5 s/m（≥3s）估算，与现有入库估算一致。
- 颜色约定：入库黄（#FFEB3B）、离场橙（#FF9800）、移位/让行紫（#9C27B0）。

## 里程碑

- [x] M1 引擎补 exit 元数据（`engine.py`）
- [x] M2 路径段提取与插值（`common.py` + 单测）
- [x] M3 页面阶段回放与按阶段绘图（`pages.py`、`viz.py`）
- [x] M4 验证（pytest 全套 + 自检）与提交推送

## 详细实施步骤

1. `engine.py`：有阻挡 DEPARTURE 日志处先 `exit_node = self._exit_for(vehicle)` 并写入 metadata。
2. `common.py`：
   - `build_vehicle_phases(net, pe, events, vid) -> dict`：
     `{"enter": {...}|None, "leave": {...}|None, "shifts": [{...}], "helper_shifts": [{...}]}`
     每段含 `path/t_start/t_end/spot_id/label`。
   - `interp_path_segment(net, path, t_start, t_end, t)`：线性插值，复用 `_interp_path`。
3. `pages.py`：
   - `render_path_page`：选车后构建 phases；`st.radio` 选阶段（只显示可用阶段）；
     按阶段时间窗生成 20 帧；把阶段信息存 `st.session_state.path_phase` 等。
   - `_draw_charts`：高亮路径/颜色按阶段；高亮车位置——入库用 `interp_vehicle_pos`，
     离场/移位用 `interp_path_segment`；把 helper_shifts 作为 `extra_paths` 传给绘图。
4. `viz.py`：`draw_parking_layout(..., highlight_path_color=None, extra_paths=None)`。
5. 测试：在 `tests/test_multi_entry.py` 追加 2 项（build_vehicle_phases 提取 enter/leave/shift；
   interp_path_segment 端点与中点）。

## 验证与验收

| 检查 | 命令 | 预期 |
|---|---|---|
| 单测 | `py -m pytest tests/test_multi_entry.py -q` | 通过（含新增） |
| 全套回归 | `py -m pytest -q` | 101 + 新增全部通过 |
| 自检 | `py scripts/validate_starter_package.py` | 通过 |
| 手工 | 网页动态路径页 | 入库黄虚线按实际入口；离场动画到出口；移位车可见移位动画；让行轨迹可见 |

## 风险与降级

- 无事件对时用估算时长（≥3s），不崩溃；
- 出口元数据缺失时回退默认口（与引擎一致）；
- 回滚：tag `backup-before-dynamic-path-feedback-20260828`。

## 决策日志

- 日期：2026-08-28
- 决策：动态路径页按「阶段」组织（入库/离场/移位），不做全生命周期连续回放。
  - 理由：停车时长远大于行驶时长，连续回放会长时间停在车位；分阶段更直观。
  - 证据：用户反馈「出去的没有，能不能单独做一个」。

## 进度记录

- 日期：2026-08-28
- 已完成：备份 tag、ExecPlan。
- 下一步：M1 实施。

- 日期：2026-08-28
- 已完成：M1–M4 全部实施并验证。
  - `engine.py`：有阻挡 DEPARTURE 事件补 `exit` 元数据；
  - `common.py`：新增 `build_vehicle_phases`（入库/离场/移位/让行轨迹提取）与
    `interp_path_segment`（路径段线性插值）；
  - `pages.py`：动态路径页新增「③ 选择回放阶段」（入库/离场/移位，只显示存在事件阶段），
    入库黄色虚线改为按该车实际入口（`spot_entry.entry`），离场/移位动画按路径段插值，
    让行移位轨迹作为辅助虚线绘制；
  - `viz.py`：`draw_parking_layout` 新增 `highlight_path_color` 与 `extra_paths` 参数。
- 实际验证：`py -m pytest -q` → 103 passed（新增 2 项路径段/插值单测）；
  `py scripts/validate_starter_package.py` → 通过（139 文件）；UI 模块 import 正常。
- 问题：离场等待（移位让行）期间的精确时序为路径匀速插值近似，页面如实标注。
- 下一步：提交推送，待用户验收。
