# M4 R5 车主 synthetic 演示情景轮换 ExecPlan

## 1. 状态与边界

- 计划状态：`completed`（P0–P3 已完成并由用户验收，实施授权关闭）；
- 授权来源：用户在 M4 R4 验收时指出固定占用基态导致推荐重复，并于 2026-08-21 确认采用
  “确定性演示情景轮换”，授权 M4 R5 及向后兼容的 additive Schema/端点；
- 基线：`codex/web-v2-m4-driver-react` 的 R4 恢复点 `c579ca1`；
- 当前 handoff：`docs/handoffs/web-v2/m4-driver-react-handoff.md`（R4 历史交接，R5 完成后原位更新，
  不创建第二份 M4 handoff）；
- 非目标：M5 答辩页面、场景编辑器、导入、实验算法、算法比较、不可复现随机事件、真实停车场
  模拟补值、公共 Journey/Route/Recommendation 语义变化和关键依赖；
- Git：用户已验收并授权按精确白名单创建、备注及推送单一 R5 恢复点；恢复点以本计划所在提交为准。

## 2. 问题与目标

当前 PUBLIC 基态固定选择一组占用位，重置后仍恢复同一状态；确定性在线规则自然反复命中相近
车位。R5 必须在不操纵推荐答案的前提下，让车主模式稳定演示多种合法状况，同时保持推荐、设施
状态、停车场摘要、路线和画布同源。

目标矩阵：

| 情景类型 | 预期可见结果 |
|---|---|
| 平峰 | 近端普通独立位，存在合规备选 |
| 高峰 | 近端候选被占，推荐跨区或较远车位 |
| 充电紧张 | 充电请求进入无可行/等待，切换或确定性释放后恢复 |
| 纵深协同 | 严格可恢复纵深位成为主推荐，显示知情确认或拒绝替代 |
| 动态异常 | 推荐位被占或通道成本变化后由既有命令 replacement/replan |

每个停车场不必实现全部五类，但四套 PUBLIC 合计必须覆盖；每个 lot 至少三个 profile，且连续
profile 的普通请求结果不能全部落在同一车位/同一区域。

## 3. 冻结契约与数据语义

新增：

1. `DriverDemoProfile 1.0.0`：`profile_id`、中文 `label`、通俗 `description`、`ordinal`、`total`；
2. `DriverRecommendationContext.demo_profile` 和 `ParkingFacilityStateSnapshot.demo_profile`：仅
   synthetic PUBLIC 返回，真实源为 `null` 或省略；
3. `DriverDemoProfileAdvanceRequest 1.0.0`：期望 profile、期望 state version、幂等键；
4. `DriverDemoProfileAdvanceResponse 1.0.0`：新 profile、同源设施状态和停车场摘要；
5. `POST /api/v2/parking-lots/{parking_lot_id}/driver-demo-profile/advance`：只接受匹配
   `X-Session-ID` 的 synthetic driver 空闲态。

保持：公开停车场 ID、Layout 2.0.0、完整设施几何、Journey/Route/Recommendation、算法 ID/排序、
30 秒软锁和五分钟预留不变。profile 不包含推荐车位或未来事件；切换只在服务端原子提交。

## 4. 实施步骤

### P0：契约与治理

- [x] 同步状态、需求、决策和蓝图；
- [x] 建立本 ExecPlan，冻结字段、端点、错误、迁移和回滚；
- [x] 新增独立 JSON Schema、Pydantic 模型、OpenAPI 和生成 TypeScript 类型；
- [x] 增加旧客户端/旧 Schema 兼容与真实源失败关闭测试。

### P1：后端权威情景

- [x] 从不可变设施几何派生固定 profile 状态和成本；禁止请求时随机数；
- [x] `InMemorySessionStore` 按 session/driver/lot 保存当前序号、推进幂等和已处理终态；
- [x] 推荐上下文、停车场摘要、设施状态、Journey replacement/replan 使用同一 profile；
- [x] 活动行程切换、过期 expected profile/state、真实源和会话错配均在 mutation 前失败关闭；
- [x] 正常离场和 `DEMO_RESET` 只推进一次；取消、失败 attempt、刷新和重放不推进。

### P2：车主 React

- [x] synthetic 车主请求页显示当前 profile 标签和通俗说明；
- [x] 无活动行程时显示“换一组模拟状态”，切换后刷新 context、停车场摘要和布局状态；
- [x] 活动行程隐藏/禁用切换，不在前端推断 profile、推荐或状态；
- [x] 终态返回新一轮时读取服务端当前 profile；错误、409、离线和 reduced motion 保持可见。

### P3：验证与交付

- [x] 定向 Schema/模型/profile 生成与 session 状态测试；
- [x] 四 lot × profile 推荐矩阵、充电等待、纵深、动态异常、无未来信息泄漏；
- [x] Ruff、严格 Mypy、后端 Web v2 全量；TypeScript、ESLint、类型漂移、前端组件与构建；
- [x] mock 双视口快速门；真实 FastAPI + production preview Edge 桌面/Pixel 7 主流程和 Chrome smoke；
- [x] 冻结 R4 性能门不放宽：gzip 400 KiB、首屏 2 s、mutation 1 s、帧 p95 50 ms、长帧 0；
- [x] 更新教学、运行说明、唯一 M4 handoff、需求/决策/蓝图/状态和视觉证据；
- [x] 最终 Diff 审计后将 M4 设为 `awaiting_review`、关闭授权，唯一下一步为用户验收 M4。

## 5. 验收不变量

- profile 固定、版本化、可复现；同输入和相同 profile 结果一致；
- profile 只改变当时可见状态/成本，不能携带或硬编码推荐答案；
- 活动 Journey 的 profile、设施状态、Route 和 Recommendation 同源且不可切换；
- session A 的推进不影响 session B、其他停车场或 defense 命名空间；
- `unknown` 仍排除推荐，真实源仍失败关闭，buffer 仍不可推荐；
- React 不计算占用集合、候选排序或路线；M5 功能保持不存在。

## 6. 回滚

配置关闭轮换时，所有 synthetic driver 会话固定第一个默认 profile；新增响应字段保留但返回默认
摘要，推进端点返回明确禁用错误。无需迁移旧 Layout、Journey、Route、Recommendation 或 legacy
fixture。若 additive 契约本身需回滚，先恢复旧 OpenAPI/生成类型并保留后端默认 profile，不删除
用户数据或历史证据。

## 7. 实际执行记录

- 后端 Web v2：166 passed；新增定向 profile 测试 5 passed；Ruff、严格 Mypy 通过；
- 前端：79 passed；TypeScript、ESLint、API 类型漂移、production build、mock 双视口 10 passed；
- 真实 FastAPI + production preview：最终 24 passed、1 skipped；六张 R5 双视口证据人工通过；
- 性能：gzip 109,276 B；首屏 p95 159.05 ms；mutation p95 327.01 ms；动画 p95 7.40 ms；长帧 0；
- 首轮新增真实用例因宽松文本选择器出现 2 项失败，改为精确标题匹配后完整重跑通过；产品逻辑
  未因测试失败调整；
- 验收：用户已验收 R5 并批准 M4；当前无活动 ExecPlan，M5 未授权；
- Git：R5 恢复点以本计划所在提交为准，四类用户未跟踪资产未读未碰；唯一下一步为等待用户决定
  是否授权 M5。
