# M4 车主端 React 教学说明

## 1. 现实问题与核心思想

车主需要完成三个连续问题：附近哪里能停、哪个车位适合、进场后怎样到达。网页只负责展示和收集
明确操作；推荐、锁位、预留、路线、占用和异常恢复全部由 FastAPI 权威决定。这样刷新、多标签和断线
恢复时不会出现“页面说有位、服务端却已释放”的分叉。

本版本使用明确标记的 synthetic 场景，不是实测停车场、真实地图、车辆感知或自动驾驶系统。

## 2. 输入、输出与关键假设

- 输入：匿名会话 ID、停车场、服务端 synthetic profile、入口、是否需要充电，以及用户明确执行的
  切换/确认/异常/停车/离场动作；
- 输出：停车场快照、推荐与最多一个备选、30 秒软锁、当前 Journey、权威 Route 和终态原因；
- 时间单位为秒，距离单位为米；匿名 ID 只隔离本地 synthetic 会话，不是登录凭证；
- 页面动画只是根据 Route 中每段 `travel_time_s` 做 UI 插值，不推进后端状态；
- 纵深协同入位和离场都由 FastAPI 先完成权威事务并返回不可变三阶段 replay，React 只回放 actor
  与 Route；动画结束不会再提交业务事件。

## 3. 状态与时间

```text
WAITING → SOFT_HELD → SESSION_RESERVED → NAVIGATING → OCCUPIED → DEPARTED
                 ↘ EXPIRED / CANCELLED / FAILED
```

软锁剩余时间的直观公式是：

```text
remaining = max(0, expires_at - authoritative_server_now)
```

页面用响应 `observed_at` 加浏览器单调时钟推进显示；刷新只重新读取，不延长期限。归零后停止危险操作，
立即读取权威状态。

### 3.1 为什么不是随机占用

四套 PUBLIC 停车场各有平峰、高峰远端、充电紧张和纵深协同四个固定 profile。profile 只描述
当前可观察的占用/可用状态和成本，不指定推荐答案；FastAPI 仍调用同一个在线规则真实计算。这样
既能展示不同状况，又能用固定输入复现问题。

profile 按匿名会话和停车场隔离。活动 Journey 内禁止切换；空闲时“换一组模拟状态”原子推进，
正常离场或演示重置后只推进一次。刷新、重放和 replacement 不会偷偷换场景。配置关闭轮换时固定
第一个 profile，真实数据源从不接受该命令。

### 3.2 深层车辆怎样安全入位和离场

学校“纵深协同”仍由未修改的 `OnlineRuleServiceV2` 真实推荐严格可恢复的深层位。推荐时浅层位
只是协调预留，不伪造未来占用；用户导航到位并明确点击协同入位后，FastAPI 才在原子事务内形成本轮
权威 blocker。服务端根据 `stack_group_id` 和 `space_ids_near_to_deep` 选择浅层 blocker 和专用
buffer，并生成 blocker→buffer、当前车辆 approach→深层位、buffer→原位三阶段证据。成功后深层
目标和浅层 blocker 都是 occupied，buffer 恢复 available，Journey 进入 `OCCUPIED`。

随后离场读取入位保存的协调记录，复用相同 blocker vehicle ID 和 buffer ID，再计算 blocker→buffer、
目标→exit、buffer→原位三段 Route。buffer 忙、任一路线不可达、状态过期或协调身份不一致时，
服务端在任何车辆移动前失败关闭：入位前 Journey 保持 `NAVIGATING`，离场前保持 `OCCUPIED`。

入位响应带 replay ID、actor、起终资源、Route、相对回放时长、before/after 完整设施快照、前后
状态哈希和最终 Journey；离场响应保存离场当刻设施快照。正常离场会为下一轮推进 profile，但旧
replay 始终使用自身快照；浏览器必须核对 parking lot、layout、scenario、state、profile 与 cost
身份，不能把旧事件叠在新状态上。
事务已经在服务端完成，所以刷新只恢复同一 replay；“重新播放过程”只重置浏览器时间轴。
`prefers-reduced-motion` 下不连续移动，用户逐段查看静态阶段。回放时长是压缩后的展示节奏，Route
自身的距离和真实预计时间仍原样保留，两者不能混为业务 ETA。

## 4. 最小例子

学校场景中，车主选择入口且不要求充电。服务端推荐 A-02 并锁 30 秒；车主确认后得到 5 分钟预留和
Route。页面按 Route 的各段时间移动小车。车主点击“推荐位被占”时，服务端将原位记为当前场景的
外部异常，并创建新的推荐 attempt；页面回到推荐页恢复新状态。普通位只有车主点击“我已停入”才
改变状态；深层纵深位则由车主明确点击“我已到达，开始协同入位”，服务端完成协同事务后 Journey
才从 `NAVIGATING` 变成 `OCCUPIED`。

## 5. 数据流与伪代码

```text
读取停车场(session + profile) → 空闲时可原子推进 profile → 提交需求(session + context)
→ 服务端原子推荐并锁位
→ 用户确认 → Trip T1 → FacilityLayout/FacilityState/ParkingLot → Trip T2
→ 用户命令(expected_version + idempotency_key)
→ mutation 完成后强制 fresh recovery → 按权威状态渲染
```

```text
recover():
  前后夹读 TripSnapshot，中间读取完整设施布局、session-aware 状态和停车场
  比较 Journey、Driver、Route、重规划和生命周期身份；冲突只重试一次
  校验 lot/layout/scenario、目标 claim、Route 节点/边/方向/终点
  全部合法后一次性替换页面快照；持续变化时失败关闭

mutate(command):
  提交当前 expected_version 和新的幂等键
  成功或 409 后都重新 recover
  网络失败时保留上次只读画面并禁用不可逆操作
```

## 6. 代码入口与运行

- React 路由：`apps/web/src/App.tsx`；
- 发现页：`apps/web/src/parking/ParkingDiscoveryPage.tsx`；
- 推荐页：`apps/web/src/parking/RecommendationPage.tsx`；
- 当前行程：`apps/web/src/parking/JourneyPage.tsx`；
- 纵深回放面板/时间轴：`apps/web/src/parking/TandemReplayPanel.tsx`、
  `apps/web/src/parking/tandemReplay.ts`；
- 共享完整画布：`apps/web/src/parking/facility/`；
- API 运行时守卫：`apps/web/src/api/`；
- FastAPI 组合根：`src/parking_opt/api/app.py`。

在仓库根目录执行 `npm --prefix apps/web run demo`，访问 `http://127.0.0.1:4173`；执行
`npm --prefix apps/web run test:e2e:real` 可重跑 production build + FastAPI 的真实浏览器验收。
完整命令、端口失败关闭和停止方式见 `docs/delivery/web-v2-m4-driver-runbook.md`。

## 7. 常见错误与验证

- 不要在前端减空位、选车位或寻路；应重新读取权威 API；
- 不要在前端随机占用车位或推断下一个 profile；切换只接受服务端结果；
- 不要用 `Date.now()` 单独判断服务端期限；系统墙钟可能偏移；
- 不要把动画到终点当成已停车；必须由用户明确提交；
- 不要由前端选择 blocker、buffer、Route 或宣布事务成功；只能消费服务端 replay；
- 不要把“无法停入”写成物理外部占位，两者审计语义不同；
- 不要把 synthetic 页面称为真实实时数据或实车导航；
- 不要把旧 `Layout 2.0.0` 或前端 ID 映射当完整设施几何；画布只消费版本化 Facility 资源；
- 不要让布局、设施状态和 Trip 的不同恢复代次混搭；夹读持续冲突时应失败关闭；
- Uvicorn 在本机自动选择不兼容 `httptools` 时会启动失败，固定 `--http h11`；
- 验证顺序采用漏斗：定向单测 → 类型/lint/build → mock 双视口 → 真实双服务全链 → 视觉/性能。
