# M4 会话权威空位快照教学说明

## 1. 现实问题与核心思想

停车场初始数据只能说明演示场景刚加载时有多少空位。车主获得推荐后，车位会经历软锁、预留、
导航中、占用、取消、到期和离场；发现页若仍显示初始数量，就会与推荐结果矛盾。

本模块把浏览器的匿名 `X-Session-ID` 视为 synthetic driver 场景副本标识，在服务端同一把锁内
清理到期状态并读取有效声明和异常位，再用车位 ID 集合计算有效空位。请求头不是账号、密码或
权限凭证，未来真实系统应替换为正式鉴权和持久化会话。

## 2. 输入、输出与假设

输入：

- `session_id`：1–128 字符的匿名会话 ID；
- `namespace`：当前发现页固定为 `driver`；
- `scenario_id`、`parking_lot_id`：由服务端停车场 bundle 推导；
- `Layout.spaces`：包含每个物理车位的基础状态；
- 会话存储中的有效声明和异常位。

输出是保持 `ParkingLot 2.0.0` 结构不变的摘要，其中 `available_spaces` 是会话投影值，
`ParkingLot.updated_at` 是本次观察时间，`data_source.updated_at` 仍是底层数据源时间。

当前只保证单进程、内存存储和相互隔离的 synthetic 会话副本，不代表真实停车场并发能力。

## 3. 数学定义

对停车场 `l` 和会话作用域 `s`：

```text
B_l = {i | 车位 i 的基础状态为 available}
C_s,l = 当前有效声明的车位 ID 集合
U_s,l = 当前会话已知异常位 ID 集合
A_s,l = B_l − (C_s,l ∪ U_s,l)
有效空位数 = |A_s,l|
```

声明状态包括 `SOFT_HELD`、`SESSION_RESERVED`、`NAVIGATING` 和 `OCCUPIED`；`WAITING` 不持有
车位。集合并集可避免同一车位同时出现在声明和异常集合时被扣两次，也不会错误扣除基础已占用位。

## 4. 数据流与伪代码

```text
浏览器读取或创建稳定匿名 session_id
  → GET /api/v2/parking-lots，携带 X-Session-ID
  → 服务端固定 namespace=driver，并从 bundle 得到 scenario/lot
  → 在 SessionStore 的同一 RLock 内：
      处理当前 session+namespace 的精确到期
      回收当前作用域的闲置 Journey
      仅在无活动 Journey 且达到 TTL 时清理异常位
      同时复制 claims、unavailable 和 observed_at
  → projector 按车位 ID 集合计算 available_spaces
  → 返回 no-store 且 Vary: X-Session-ID 的响应
```

推荐、等待重试和外部占位替换也调用同一个原子快照，因此算法排除集合与发现页数字一致。

## 5. 极小例子

基础可用车位为 `{A-01, A-02, A-03}`。当前会话软锁 `A-02`，同时外部占位记录包含
`{A-02, A-03}`：

```text
有效空位 = {A-01, A-02, A-03} − ({A-02} ∪ {A-02, A-03})
         = {A-01}
有效空位数 = 1
```

若使用“3 − 1 − 2”，会得到 0，产生重复扣减；集合计算得到正确结果 1。

## 6. 代码入口与验证

- 原子快照：`src/parking_opt/api/sessions.py` 的 `availability_snapshot`；
- 集合投影：`src/parking_opt/api/availability.py`；
- 列表/单体 GET：`src/parking_opt/api/app.py`；
- 推荐共用快照：`src/parking_opt/api/services/journey.py`；
- 前端会话 ID：`apps/web/src/api/sessionIdentity.ts`；
- 测试：`tests/web_v2/test_availability.py`、`test_session_state.py`、`test_api.py` 与
  `apps/web/src/api/*.test.ts`。

从仓库根目录运行后端回归：

```powershell
.venv-m2\Scripts\python.exe -m pytest tests/web_v2 -q
```

前端在 `apps/web` 中运行 `npm test`、`npm run typecheck`、`npm run lint` 和
`npm run test:e2e`。

## 7. 常见错误

- 按数量连续相减，导致基础已占用或重叠异常位被重复扣除；
- 分别读取 claims 和 unavailable，在备选切换中看到撕裂状态；
- 读取时刷新软锁期限；
- 聚合其他 session、defense、scenario 或 lot 的状态；
- 只给带请求头的响应设置 `Vary`，导致缓存复用错误；
- 前端自行减一，刷新后与服务端分叉；
- 把 `X-Session-ID` 宣称为安全登录凭证。
