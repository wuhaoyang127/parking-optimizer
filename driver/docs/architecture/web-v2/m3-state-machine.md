# M3 会话状态机与资源不变量

## 1. 现实问题

M2 只能计算“现在推荐哪个车位”，但不能阻止同一会话中的两辆模拟车同时拿到同一车位，也
不能回答刷新页面后预留还剩多久。M3 将推荐结果放入服务端权威状态机：推荐成功必须先原子
声明主车位，前端只能看到已经声明成功的 `SOFT_HELD`，而不是尚未锁定的瞬时计算结果。

## 2. 状态与期限

| 状态 | 是否声明车位 | 合法后继 |
|---|---:|---|
| `IDLE` | 否 | `WAITING`, `SOFT_HELD` |
| `WAITING` | 否 | `SOFT_HELD`, `CANCELLED`, `FAILED` |
| `SOFT_HELD` | 是，30 秒 | `SESSION_RESERVED`, `CANCELLED`, `EXPIRED`, `FAILED` |
| `SESSION_RESERVED` | 是，driver 300 秒 / defense 60 秒 | `NAVIGATING`, `CANCELLED`, `EXPIRED`, `FAILED` |
| `NAVIGATING` | 是，沿用预留原期限 | `OCCUPIED`, `CANCELLED`, `EXPIRED`, `FAILED` |
| `OCCUPIED` | 是，无自动预留续期 | `DEPARTED`, `FAILED` |
| `DEPARTED` | 否 | 终态 |
| `CANCELLED` | 否 | 终态 |
| `EXPIRED` | 否 | 终态 |
| `FAILED` | 否 | 终态 |

`RECOMMENDED` 不保存为业务状态。终态不能重新激活；重新推荐必须创建新的 attempt。进入
`NAVIGATING` 不改变 `SESSION_RESERVED` 的原到期时刻。

## 3. 资源不变量

1. 资源所有者键为 `(session_id, namespace, scenario_id, parking_lot_id, space_id)`；
2. 同一场景副本内一个车位至多有一个有效应用声明；
3. 一个 driver 命名空间至多有一个活动 attempt；
4. `WAITING` 和终态不持有车位；`SOFT_HELD`、`SESSION_RESERVED`、`NAVIGATING`、`OCCUPIED`
   必须恰好持有一个与行程一致的车位；
5. 备选车位只是一份当时可行快照，不预先声明；切换成功前保留原锁，成功声明备选后才能释放
   原锁，任何时刻不得同时持有两个声明；
6. 软锁和预留由单调时钟判断到期，UTC 时间只用于 API 显示和审计；访问、刷新、断线或模式
   切换不能续期；
7. 会话 GC 使用最后活动时间：driver 1,800 秒、defense 7,200 秒。GC 释放资源并写入
   `DEMO_SESSION_GC`，不能静默删除占用证据；
8. driver 与 defense 使用不同可变场景副本，答辩倍速不能影响 driver 墙钟。

## 4. 幂等与并发

每个状态命令携带 `idempotency_key` 和 `expected_version`。相同会话、命令类型和幂等键：

- 输入规范哈希相同：返回第一次保存的结果，不重复产生事件；
- 输入规范哈希不同：返回幂等冲突；
- `expected_version` 落后：返回版本冲突并要求刷新；
- 声明竞争失败：保留权威状态，返回资源冲突，不静默改选未经解释的车位。

## 5. 极小例子

时刻 0，A 会话推荐 `A-01` 并原子进入 `SOFT_HELD`，到期时刻为 30。时刻 10，B 会话尝试
声明同一场景副本的 `A-01`，必须失败；如果 B 属于另一个匿名会话，它使用自己的 synthetic
场景副本，不与 A 共享声明。A 在时刻 20 确认后进入 `SESSION_RESERVED`，新到期时刻为 320；
时刻 30 原软锁到期不再生效。A 在时刻 100 开始导航，到期仍是 320，不变为 400。

## 6. ETA 规则

车主主推荐必须满足：

\[
\mathrm{ETA}_{route} + 60\ \mathrm{s} \le 300\ \mathrm{s}
\]

重规划时使用“当前 ETA + 60 秒 ≤ 当前预留剩余秒数”。不满足时记录 `ETA_EXCEEDS_RESERVATION`
并让用户选择继续到原期限或重新推荐，不能延长预留。

## 7. 代码与验证入口

- 冻结参数：`configs/web-v2/m3.toml`；
- v2 契约：`src/parking_opt/api/models.py` 与 `schemas/v2/`；
- 会话存储：`src/parking_opt/api/sessions.py`；
- 状态服务：M3 将在 `src/parking_opt/api/services/` 中实现；
- 回归：`tests/web_v2/`。
