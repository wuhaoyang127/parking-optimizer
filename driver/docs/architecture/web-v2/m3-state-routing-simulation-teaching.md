# M3 状态、动态路线与多车仿真教学说明

## 1. 现实问题与核心思想

M2 只能回答“此刻推荐哪个车位”。M3 继续解决三个现实问题：同一车位不能被同一模拟场景中的
两辆车同时占用；车辆偏航或通道拥堵后路线必须更新；纵深内侧车辆出库时，外侧阻挡车必须先
移到缓冲位，再恢复原位。系统只模拟停车管理层状态，不模拟方向盘、碰撞规避或自动驾驶。

核心思想是把推荐、车位声明、路线和仿真事件都放在后端权威状态中。前端以后只读取结果和
事件日志并做动画插值，不能自行宣布“已停车”“已移位”。

## 2. 输入、输出与假设

- 会话输入：匿名会话、driver/defense 命名空间、场景、Journey、版本号和幂等键；
- 路由输入：完整布局、当前已观察的各通道占用和当前节点；未来时间快照被拒绝；
- 仿真输入：显式仿真时间、稳定优先级、车辆、事件类型和载荷；
- 输出：Journey 状态、完整成本快照、路线/警告/失败、带前后哈希的事件和最终摘要；
- 单位：距离米、耗时秒；业务期限使用单调时钟，UTC 只用于展示和审计。

首版是单进程 synthetic 原型。不同匿名会话和 driver/defense 拥有隔离的模拟场景副本；这不是
真实停车场的共享物理状态，也不构成生产并发承诺。

## 3. 状态与关键公式

主流程为：

```text
WAITING → SOFT_HELD → SESSION_RESERVED → NAVIGATING → OCCUPIED → DEPARTED
```

软锁为 30 秒。driver 确认后预留 300 秒，defense 为 60 秒；进入导航不续期。动态成本对一条
边采用当前通道的峰值占用率：

```text
边耗时 = 基础耗时 × (1 + 峰值占用率)
```

若任一关联通道的当前占用达到容量，该边标记为不可用。车主重规划警告条件为：

```text
当前路线 ETA + 60 秒安全余量 > 当前预留剩余秒数
```

触发警告不会延长原期限。全路径不可达时返回原路线、`DYNAMIC_ROUTE_UNREACHABLE` 和失败记录。

## 4. 伪代码与数据流

```text
推荐并占位(driver, 当前布局, 当前成本):
    在会话存储事务中读取有效声明和异常车位
    运行在线规则并排除不可用候选
    若有主位：先创建软锁，再返回推荐
    否则：创建 WAITING，不声明车位

重规划(journey, 当前节点, 当前通道占用):
    拒绝未来时间或不完整通道负载
    生成覆盖全部边的版本化成本快照
    计算到原目标的新路线
    保留原预留期限，记录成功、超窗警告或不可达失败

纵深出库(目标车):
    找出比目标更靠近通道的占用车辆
    若空闲缓冲位不足：记录失败，状态不做部分移动
    否则依次移入缓冲位
    目标车离场
    逆序恢复阻挡车辆
```

每个仿真事件携带规范化 `changes`、`before_sha256` 和 `after_sha256`。状态哈希还绑定停车场、
布局版本、随机种子和墙钟起点。重放器按顺序应用相同变化，并核对停车场、墙钟映射及前后
哈希；顺序、状态变化、运行身份或哈希被篡改都会失败。纯展示字段不属于密码学签名范围。

## 5. 可手算极小例

学校场景 `stack-B1` 有外侧 `B-01` 和内侧 `B-02`，`B-01` 已占用，只有一个缓冲位
`BUF-01`。新车停入 `B-02` 后请求离场：

1. `B-01 → BUF-01`，移位次数加 1；
2. `B-02` 车辆离场；
3. `BUF-01 → B-01`，阻挡车恢复。

因此本例移位车辆数/移位次数是 1，不是 2；恢复是同一次移位流程的后半段。若删除
`BUF-01`，系统记录 `BUFFER_CAPACITY_INSUFFICIENT`，不得先把 `B-01` 挪走再失败。

## 6. 代码入口与运行方法

- 状态存储：`src/parking_opt/api/sessions.py`；
- 推荐与异常恢复：`src/parking_opt/api/services/journey.py`；
- 动态成本：`src/parking_opt/api/dynamic_costs.py`；
- 重规划：`src/parking_opt/api/services/replanning.py`；
- 仿真与重放：`src/parking_opt/api/simulation.py`；
- FastAPI：`src/parking_opt/api/app.py`；
- 冻结参数：`configs/web-v2/m3.toml`。

无 UI 演示：

```powershell
.\.venv-m2\Scripts\python.exe scripts\run_web_v2_m3_demo.py
```

测试与静态检查：

```powershell
.\.venv-m2\Scripts\python.exe -m pytest tests\web_v2 -q
.\.venv-m2\Scripts\python.exe -m ruff check src\parking_opt\api tests\web_v2
.\.venv-m2\Scripts\python.exe -m mypy src\parking_opt\api
```

## 7. 常见错误与验证方法

- 页面刷新续期：错误。比较确认后与导航后的 `expires_at`，必须相同；
- 推荐响应后才锁位：错误。响应中的 `claim_status=soft_held` 必须对应已经存在的声明；
- 候选切换同时锁两个位：错误。失败保留原锁，成功后只有新位声明；
- 外部占位后复活旧 attempt：错误。旧 attempt 进入 `FAILED`，新推荐必须使用新 ID；
- 使用未来仿真事件做在线决策：错误。未来 `observed_at` 必须失败关闭；
- 把缓冲恢复算成第二辆移位：错误。指标口径需区分移位车辆、移位流程和动作段；
- 只验证成功例：错误。缓冲不足、无路、ETA 超窗、幂等冲突、过期和篡改重放都必须保留。
