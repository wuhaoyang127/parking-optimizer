# M4 R6 车主纵深协同离场权威回放 ExecPlan

## 1. 状态、授权与基线

- 计划状态：`awaiting_review`（实现与终审门完成，等待用户验收）；
- 授权来源：用户于 2026-08-21 确认“服务端权威纵深离场事务 + 前端事件回放”方案；
- Git 基线：分支 `codex/web-v2-m4-driver-react`，R5 恢复点 `cc7d508`；
- 授权范围：additive replay Schema/API、synthetic `tandem-focus` fixture、driver Journey/设施状态
  衔接、双车辆画布、双视口验证与交付文档；
- 非范围：M5 答辩页面、自由仿真、场景编辑、实验算法/指标/导出、关键依赖、算法排序、真实车辆
  控制、公共既有必填字段或数据语义替换；
- Git：用户未授权本轮 commit/push；完成后保留精确 Diff 等待决定。

## 2. 问题与验收目标

当前车主画布只能显示一辆沿当前 Route 移动的车辆；普通离场直接把 Journey 置为 `DEPARTED`。
M3 已冻结纵深离场规范顺序，但现有公开 simulation run 与 driver Journey/完整设施画布相互独立，
事件也没有可直接渲染的三段 Route。R6 必须在不伪造业务状态、不进入通用多车仿真的前提下，稳定
演示深层车辆被阻挡时的完整协同移位过程。

验收流程固定为：

```text
真实 OnlineRuleServiceV2 产生可恢复深层候选
→ 用户知情确认、导航并明确停入
→ synthetic 权威事件形成实际浅层 blocker
→ blocker 沿服务端 Route 移至专用 buffer
→ 当前车辆沿服务端 Route 驶向出口
→ blocker 沿服务端 Route 返回原位
→ Journey 权威 DEPARTED，回放可恢复/重播
```

## 3. 冻结契约与事务边界

计划新增独立 `DriverTandemDepartureReplay 1.0.0` 及请求资源，不改变旧 `/depart` 响应。additive
synthetic-only 命令返回：replay ID、停车场/布局/场景/状态/Journey 版本、blocker 与 buffer 映射、
规范阶段、每段 `Route 2.0.0`、相对起点和时长、before/after SHA-256 和最终 Journey。React 用
replay 的停车场/布局/场景/状态身份夹读同一权威设施快照；幂等重放返回字节语义一致的既有
replay，同 Journey 只产生一个成功 replay。

FastAPI 在同一原子边界验证：

- driver 会话、PUBLIC synthetic 数据源、Journey 为 `OCCUPIED` 且目标属于深层纵深位；
- blocker 是同一 `stack_group_id` 中实际更浅成员，顺序由 `space_ids_near_to_deep` 决定；
- 每个 blocker 独占一个已启用且空闲的专用 buffer；原位、buffer、目标和事务无冲突；
- blocker→buffer、buffer→原位、目标→exit 全部按当前 `CostSnapshot` 可达且有向连续；
- expected Journey/state/layout/profile 版本和幂等键匹配。

任一条件失败返回 409/503 并保持 Journey、声明、设施状态和 profile 不变。真实源一律拒绝演示命令。

事务可先在服务端原子完成，再把不可变权威事件作为“过程回放”呈现；前端不得根据动画结束提交
移位或离场完成。页面和文档必须明确回放不代表实时定位或车辆控制。

## 4. 实施阶段

### P0 治理、契约和回滚

- [x] 同步状态、需求、决策和蓝图，重新打开 M4 并冻结边界；
- [x] 建立本 ExecPlan，冻结验证矩阵和性能门；
- [x] 新增 additive JSON Schema/OpenAPI/生成类型和契约守卫；
- [x] 增加 `driver_demo.tandem_departure_replay_enabled` 回滚开关；关闭时保留旧普通离场。

### P1 服务端权威 replay

- [x] 调整 `tandem-focus` 合法可见状态，使固定矩阵实际产生深层可恢复候选，不硬编码答案；
- [x] 生成确定性 blocker、buffer assignment、三段 Route、阶段时长和状态哈希；
- [x] 原子执行并记录 replay，覆盖幂等、重放、刷新恢复和 profile 单次推进；
- [x] 保持旧 `/depart`、非纵深离场和 real/legacy 行为不变。

### P2 React 双车辆过程回放

- [x] 扩展共享画布接受小型 actor 列表，不在前端写死 ID 或路径；
- [x] 当前车辆绿色、blocker 橙色，显示三阶段进度、通俗文字、buffer/原位高亮和重播；
- [x] 桌面/手机功能一致；后台、离线、reduced motion 和刷新使用静态/恢复路径；
- [x] 失败响应不启动动画，保留 `OCCUPIED` 和可操作错误。

### P3 验证与证据

- [x] Schema/模型/路由引用、固定矩阵、事务不变量和失败关闭定向测试；
- [x] Web v2 后端全量、Ruff、严格 Mypy；
- [x] 前端组件全量、TypeScript、ESLint、生成 API 漂移、production build；
- [x] mock 双视口快速门；
- [x] 真实 FastAPI + production preview：学校深层纵深完整流程，Edge 桌面/Pixel 7 与 Chrome；
- [x] 人工检查遮挡、文本、横向溢出、触控、缩放、reduced motion、离线/错误和重播；
- [x] 保存视觉与性能证据到 `docs/visual-qa/web-v2/m4-r6/`。

### P4 文档、终审和停止

- [x] 更新教学、runbook、唯一 M4 handoff、需求/决策/蓝图/状态；
- [x] 最终 Diff、用户资产、Schema/算法/M5 边界审计；
- [x] 关闭全部 P1/P2/P3 并完成独立只读终审；
- [x] 将 M4 置为 `awaiting_review`、关闭授权，唯一下一步为用户验收 M4 R6。

## 5. 冻结验证矩阵

- 成功：一个/多个 blocker 的规范次序、buffer 注入映射、三段 Route、最终恢复和 Journey 离场；
- 失败：buffer 不足/占用、任一方向不可达、浅深关系错误、状态过期、会话错配、真实源、功能关闭；
- 一致性：推荐/Journey/facility/replay 同停车场、布局、场景、profile、state/cost 版本；
- 幂等：POST 重放不重复生成事务、不重复 profile 推进；GET/刷新恢复同一 replay；
- 前端：不计算 blocker、buffer、Route、事务阶段或完成状态；只消费服务端 replay；
- 回归：普通位、浅层纵深、旧 `/depart`、R5 profile 轮换、外部占位/replan、legacy 全部保持。

性能门沿用 R5 测量前阈值，不因结果放宽：生产 JS+CSS gzip ≤ 400 KiB；暖首屏 p95 ≤ 2 s；关键
mutation p95 ≤ 1 s；动画帧间隔 p95 ≤ 50 ms；>100 ms 长帧为 0。新增 replay mutation 纳入同一
1 秒门，三段动画至少采样 5 秒并覆盖双 actor 同时存在的最重阶段。

## 6. 回滚

优先关闭 `driver_demo.tandem_departure_replay_enabled`，页面恢复既有普通 `/depart`；保留 additive
Schema、历史 replay 证据和旧客户端兼容。若需代码回滚，删除新端点/可选渲染能力并恢复旧
`tandem-focus` fixture，不修改 Journey/Route/Layout 既有资源，不删除用户资产或历史视觉证据。

## 7. 实际结果与保留失败

- 后端 Web v2：172 passed；Ruff 通过；严格 Mypy 21 个源文件通过；
- 前端：82 passed；TypeScript、ESLint、OpenAPI 生成类型漂移和 production build 通过；mock
  双视口 10 passed；
- 真实联调：27 passed、1 个移动端性能项目按设计 skip；R6 在 Edge 1440×1000、Edge Pixel 7 和
  系统 Chrome 均完成；四张 R6 截图人工复核通过；
- 最终性能：JS+CSS gzip 112,590 B；暖首屏 p95 154.49 ms；推荐 mutation p95 368.21 ms；
  replay mutation p95 92.67 ms；5 秒双 actor 动画 823 帧、帧间隔 p95 6.20 ms、长帧 0；
- 保留失败：首次真实门因 8000/4173 被本仓库旧服务占用而按设计拒绝，核验 PID 后停止旧服务并
  用当前代码重跑；一次从仓库根误调用 Vitest 未加载 jsdom，改用 `apps/web` 正确配置后 32/32；
  前端全量首轮发现 `App.test.tsx` 空行程 fixture 缺新增能力字段，修正后 82/82；最终审计发现
  `atomic()` 未快照 R6 新表，补齐 replay/幂等表回滚并以内部失败注入验证。未降低任何门槛。
- 独立终审发现 replay 创建后 profile 自动推进，刷新会把旧 replay 叠加到下一轮设施状态的 P2；
  replay 现内嵌离场当刻权威设施快照，服务端/前端严格核对身份后渲染，并新增错配失败关闭与三端
  真实回归。该问题关闭并保留记录。
