# M4 R6.1 车主纵深协同入位与离场闭环 ExecPlan

## 1. 状态、授权与基线

- 计划状态：`in_progress`，功能完成，最终验证缺口关闭中；
- 用户授权：2026-08-31 确认“推荐后形成 blocker、服务端原子协同入位、离场复用同一 blocker”；
- Git 基线：分支 `codex/web-v2-m4-driver-react`，仅本地安全恢复点 `26a0399`，不得推送；
- 范围：additive arrival replay、权威协调记录、设施状态前后快照、共享双 actor 回放、真实联调、
  视觉/性能、文档与独立终审；
- 非范围：M5、算法排序/v1、预先占用浅层位、真实数据语义、关键依赖、main、tag、远程推送；
- 用户资产：`.codex-tmp/`、`data/parking-lots/`、`docs/business-plan/`、logo 和 `run.cmd` 不读取、不改、
  不暂存。

## 2. 目标流程与真实性边界

```text
OnlineRuleServiceV2 在入口畅通时真实推荐深层位
→ 用户确认并导航
→ 用户明确点击“我已到达，开始协同入位”
→ FastAPI 原子形成本轮浅层 blocker 并完成入位事务
→ blocker 到 buffer
→ 当前车辆进入深层位
→ blocker 恢复原位
→ Journey OCCUPIED，协调记录可恢复
→ 离场复用同一 blocker 完成既有三阶段 replay
```

推荐阶段不得读取未来 blocker；React 不推断 blocker、buffer、Route 或状态完成。用户点击入位命令
即是明确停车确认，服务端先完成权威事务再返回不可变过程证据，动画结束不提交占用。

## 3. 契约与状态冻结

- 新增 `DriverTandemArrivalRequest/Replay 1.0.0`，端点
  `POST /api/v2/journeys/{journey_id}/tandem-arrival-replay`；
- arrival step 独立使用 `relocate_to_buffer | direct_entry | restore_original`，不扩写既有 departure
  step 枚举；
- replay 携带 before/after 完整 `ParkingFacilityStateSnapshot`、三段 Route、actor、相对时长、
  前后哈希和最终 `OCCUPIED` Journey；
- `DriverTripSnapshot` 只增加可选 arrival replay 能力/结果字段；旧字段和端点保持；
- session store 新增按 Journey 保存的协调记录和 arrival replay/idempotency 表，全部纳入 `atomic()`；
- 成功后 blocker 和目标均 occupied、buffer available；departure 必须读取同一协调记录；
- arrival feature flag 独立关闭后前端恢复普通 `/occupy`，departure flag 和旧 Schema 不受影响。

## 4. 实施阶段

### P0 治理和恢复

- [x] 精确白名单创建仅本地 R6 离场安全恢复点 `26a0399`；
- [x] 更新状态、需求、决策、蓝图并建立本计划；
- [x] 冻结 Schema 差异、错误码、验证矩阵与性能门。

### P1 FastAPI 权威入位事务

- [x] 新增 arrival 模型、Schema、OpenAPI、生成类型和 feature flag；
- [x] 原子校验 Journey/session/lot/layout/state/cost/profile、浅深关系、buffer 与三段 Route；
- [x] 形成本轮 authoritative blocker，生成 before/after snapshot、哈希和协调记录；
- [x] 原子完成 `NAVIGATING → OCCUPIED`，覆盖幂等、刷新恢复和异常全量回滚；
- [x] 修改 departure 只在存在协调记录时复用同一 blocker，同时保留安全恢复点兼容路径；
- [x] 保持 OnlineRuleServiceV2、v1、普通位、旧 `/occupy`/`/depart`、legacy/real 不变。

### P2 React 入位/离场闭环

- [x] 将共享回放面板局部泛化为 arrival/departure 联合视图，不新增依赖；
- [x] 深层 eligible Journey 将“我已停入”替换为“我已到达，开始协同入位”；
- [x] 按 before snapshot 回放 blocker→buffer、driver→target、blocker→origin；完成态使用 after snapshot；
- [x] 入位完成后可重播，并继续触发既有协同离场；刷新和断线恢复同一 replay；
- [x] reduced motion、后台、离线和错误路径保持静态可操作且不产生前端状态真值。

### P3 验证与证据

- [x] Schema/模型/固定结果/状态守恒/未来信息/幂等/回滚定向测试（含路线不可达、会话错配、多 blocker）；
- [x] Web v2 后端范围回归、Ruff、严格 Mypy；
- [x] 前端全量、TypeScript、ESLint、API 漂移、production build；
- [x] mock 双视口快速门；
- [x] 真实 FastAPI + production preview：Edge 桌面、Pixel 7、系统 Chrome 完整入位/离场；
- [x] 十二张桌面/手机入位/离场三阶段证据人工复核；
- [ ] 冻结性能门全部通过（历史 production 曾通过；当前复验 PERF-02 失败，仿真按用户已接受例外保留失败）。

### P4 文档、终审和停止

- [x] 更新 runbook、教学、唯一 M4 handoff、需求/决策/蓝图/状态；
- [x] 最终 Diff、用户资产、依赖、算法/v1/real/M5 边界审计；
- [ ] 关闭全部 P1/P2/P3，取得独立只读终审 GO；
- [ ] M4 置为 `awaiting_review`、关闭授权，唯一下一步为用户验收；不提交/推送，除非用户授权。

## 5. 冻结验证矩阵

- 成功：单/多 blocker 入位顺序、前后设施状态、同 blocker 离场、最终 Journey/claim 一致；
- 失败：buffer 不足/占用、任一路线不可达、浅深错误、版本 stale、会话错配、real/legacy、功能关闭；
- 一致性：推荐时无未来 blocker；arrival/departure 的 lot/layout/scenario/profile/state/cost 全同源；
- 幂等：重复 POST 返回同一 replay，不重复占用、不重复事件、不重复 profile 推进；
- 回滚：Journey、claim、协调记录、arrival/departure replay、幂等表、设施投影和事件全部恢复；
- 前端：不计算 actor/resource/Route/事务完成，只消费服务端 replay；
- 回归：普通位、浅层纵深、R5 profile、replan/external occupancy、旧端点、legacy、real 全部保持。

性能阈值沿用 R6 冻结值：JS+CSS gzip ≤ 400 KiB；暖首屏 p95 ≤ 2 s；推荐、arrival replay、
departure replay mutation p95 各 ≤ 1 s；动画帧间隔 p95 ≤ 50 ms；>100 ms 长帧为 0。

## 6. 回滚

第一层关闭 `driver_demo.tandem_arrival_replay_enabled`，恢复普通 `/occupy`；既有 departure replay
继续可用。第二层回滚到本地安全恢复点 `26a0399`。不删除 additive Schema，不修改用户资产、v1、
legacy、真实数据或历史视觉证据。

## 7. 实际结果

- FastAPI 原子入位、设施协调投影、arrival replay/idempotency/coordination 表及 departure 复用完成；
- 前端共享面板完成 blocker→buffer、当前车辆→目标/出口、blocker→原位的双事务回放；
- Ruff、严格 Mypy、API 漂移、TypeScript、ESLint、build 通过；前端 83 passed，mock 10 passed；
- 真实矩阵 27 passed、1 个移动端性能用例按设计 skip，覆盖四类 PUBLIC 布局、Edge 双视口和 Chrome；
- production 冻结性能为 gzip 113,419 B、暖首屏 p95 206.14 ms、推荐 p95 948.44 ms、arrival p95
  342.71 ms、departure p95 159.93 ms、动画帧 p95 6.30 ms、长帧 0；
- Web v2 + contracts 组合曾为 226 passed；仿真门先隔离 1.83 s 通过，随后在活跃 GW2 高 CPU
  负载下全套 5.12 s、隔离 4.09 s 失败，最终安静环境复跑待完成；全仓历史 Streamlit 收集仍受
  缺少 `blinker` 限制；
- 12 张当前双视口阶段证据已人工复核；用户资产未读取、未修改、未暂存；R6.1 未提交、未推送。
- 独立复审确认路线不可达、会话错配和双 blocker/双 buffer 测试关闭原 P3 超报；当前唯一 NO-GO
  是用户活跃 GW2 高 CPU 负载结束后的仿真 ≤2.0 s 最终复跑。

## 8. 2026-10-17 接手修复切片（当前）

上节“唯一 NO-GO”和静态性能复跑叙述是历史恢复点。当前授权以状态文件 version 48 为准：用户
批准 NAV-01 中文转向/到达和 UX-01 停车场名称修复；重新确认接受仅限 M4 演示的性能例外，原
≤2.0 s 门和 2.7115064 s 失败保留，补充 1.982145 s 通过不覆盖失败。不得切换电源或改算法。

目标文件：routing.py、PublicFacilityDataSource 的入口朝向只读注册、RecommendationPage、相称
测试及治理/交接文档。仅显示文字变化；Route 字段、路径/成本、数据/fixture、v1、依赖、M5 不变。
方向规则见需求 6.1，未知/零长段中性提示；停车场名称使用既有 GET，错配/失败不显示伪名称。

- [x] 同步本轮明确授权、规则和风险例外。
- [x] 后端人工转角、入口朝向、退化和不改变路线结果测试，routing 14 passed。
- [x] 停车场名称加载、失败、错配和取消守卫，名称组件 11 passed。
- [x] 定向 → 静态 → 后端 → 组件 → mock → 当前真实双服务 → 新视觉/性能证据已运行并保留失败。
- [ ] 全 P1/P2/P3 关闭（PERF-01 按已接受例外记录），独立只读终审 GO。
- [ ] 同步权威文档、唯一 handoff，awaiting_review 并关闭实施授权；不提交/推送。
- [ ] 白名单生成新源码交接包、精确清单/hash、解包复验；排除用户资产和旧 ZIP，不冒充 M6。

修复后组件 87、mock 10、Schema 53、静态检查通过；后端 241 passed/1 failed（仿真 2.006702 s）。
真实矩阵 26 passed/1 skipped/1 failed，production 有 6 次 >100 ms 长帧；隔离生产性能复测推荐
p95 3057.531 ms，新增 PERF-02 未关闭。不得把 PERF-01 仿真例外用于该项。当前没有 ZIP；用户
已明确授权一个独立只读子代理终审。详细日志与新视觉在 docs/audits/web-v2/2026-10-17/。

2026-10-18：可选时序诊断仍推荐 p95 1059.538 ms 失败，未确定根因；诊断最终类型/lint 通过。
独立终审正式 NO-GO，确认 NAV-01/UX-01 及打包脱敏关闭，PERF-02 开放。当前停止封存，不为
追逐最佳样本继续重跑；只保留白名单候选、复现/回滚准备与算法契约提案，不生成源码 ZIP。
