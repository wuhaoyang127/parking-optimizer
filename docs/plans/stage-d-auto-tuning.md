# 自动调参（Auto Tuning）ExecPlan

## 目标与用户可见结果

- 单策略模式：选中算法后点「🎯 自动调参」→ 系统按 PARAMS 声明随机采样 K=10 组参数，每组用当前种子跑 1 次仿真，按当前「算法排名设置」（加权评分或字典序）选出最优参数 → 自动回填到参数控件并展示调参摘要。
- 全部对比模式：勾选「全部对比时自动调参」后，每个算法先各自调出最优参数，再产出**两组对比**：默认参数组 + 最优参数组，指标页分别展示。
- 计算位置：☁️ 云端在 Streamlit 进程内跑；💻 本地计算下发调参任务到本机 worker，口径一致。

## 当前状态

- 策略注册表已有 `PARAMS` 声明（int/float/choice/bool/strategy + locked）。
- 云/本机两套仿真执行路径：`src/ui/pages/cloud_run.py`（云端进程内）与 `worker_compute.py`（本地 worker）。
- 排名口径已有 `parking_opt/evaluation/ranking.py`（加权）与指标页字典序排序逻辑。
- 指标页 `metrics_compare.py` 只支持一组对比数据。

## 范围

### 包含

- 纯函数调参模块（采样/单种子评估/选最优）+ 多种子分组运行模块（云/本机共用）。
- 单策略「自动调参」按钮（云端 + 本地任务）。
- 全部对比「默认参数 + 最优参数」两组对比（云端 + 本地任务）。
- 指标页两组对比展示；调参结果回填参数控件 + 摘要展示。

### 不包含

- 不做贝叶斯优化/网格搜索等更复杂搜索策略（先随机采样，够用且可解释）。
- 不改 sim_runs 历史表结构（最优参数组只存 session，刷新后需重跑）。
- 不引入新第三方依赖。

## 关键定义与假设

- K=10（每算法随机采样组数），常量 `TUNE_TRIALS_DEFAULT=10`。
- 调参只用 1 个种子（当前 seed），正式对比仍用 n_runs 多种子（防过拟合）。
- 最优判定跟随当前排名设置：加权评分用 `weighted_rank`；字典序按 `PRIORITY_METRICS` 方向逐字段比较。
- `locked` 参数不采样；`strategy`/`choice` 均匀随机抽；`int` 按 step 粒度采样；RHO 的 mild_threshold ≤ severe_threshold 做修复。
- 无参数算法跳过调参（最优参组用默认参数）。

## 里程碑

- [x] M1 核心纯函数：`src/local_compute/_tuning.py`（采样/修复/选优/单算法调参）与 `src/local_compute/_groups.py`（多种子分组运行），并导出；pytest 通过
- [x] M2 worker 支持：`worker_compute.py` 支持单策略 auto_tune 任务与 compare_all tune_compare 两组对比；端到端小任务验证
- [x] M3 云端 UI：`auto_tune.py`/`compare_all_run.py` 拆分，`cloud_run.py` 委托；单策略调参按钮 + compare_all 复选框
- [x] M4 本地任务 UI：`local_task_ops.py`/`local_task_actions.py` 支持调参任务与 tuned 结果载入
- [x] M5 指标页两组对比 + 调参摘要展示
- [x] M6 测试补齐（tests/test_auto_tune.py）+ 全量 pytest + 行数/启动包自检 + 状态文档更新

每个里程碑验证命令：`py -m pytest tests/test_auto_tune.py -q`（增量）、`py -m pytest -q`、`py scripts/check_file_lines.py`。

## 风险与降级

- MOSA 每次仿真自带 NSGA-II，调参慢 → 沿用 60 秒仅标记，不阻断；用户可取消 compare_all 调参复选框。
- 公网云端大参数调参易超时 → 提示切「💻 本地计算」。
- 调参过拟合单种子 → 正式对比仍多种子，结果页如实展示（可能最优参不如默认参）。

## 决策日志

- 2026-09-14：用户确认 K=10；全部对比 = 默认 + 最优两组；支持本地计算。
