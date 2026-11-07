---
milestone: M3
status: approved
handoff_date: 2026-08-13
branch: codex/web-v2-m3-state-simulation
next_milestone: M4
---

# Web v2 M3 状态、动态路线与确定性多车仿真交接

## 验收结论

M3 已由用户于 2026-08-13 验收批准。后端现可在单进程 synthetic 条件下完成推荐与原子
软锁、确认预留、导航、动态重规划、占用、离场和异常换位；答辩仿真可稳定重放纵深移位与失败
案例。M3 没有创建 React 页面、没有进入 M4，也没有修改 v1 受保护资产。

## 已冻结口径

- driver/defense 可变状态隔离，闲置 TTL 分别为 1,800 秒和 7,200 秒；
- 软锁 30 秒，driver 确认预留 300 秒，defense 预留 60 秒；刷新、导航和重规划不续期；
- 备选切换先原子声明新位，成功后释放旧位，并保留原软锁期限；
- `WAITING` 只由显式重试恢复，不能通过查询或刷新暗中改变；
- 动态边耗时为基础耗时乘以 `1 + 峰值占用率`，满载通道关闭对应边；
- 重规划保留原路线、原期限与失败审计；ETA 加 60 秒超过剩余期限时明确警告；
- 外部占位原子终止旧 attempt、持久排除异常位并创建新 attempt，失败时完整回滚；
- 仿真使用显式时间和稳定排序；状态哈希绑定停车场、布局版本、种子、墙钟起点及完整管理状态；
- 仿真只覆盖管理层可达性、占用和移位，不模拟车辆动力学、碰撞规避或自动驾驶控制。

## 关键文件

- 会话与声明：`src/parking_opt/api/sessions.py`；
- 行程编排：`src/parking_opt/api/services/journey.py`；
- 动态成本：`src/parking_opt/api/dynamic_costs.py`；
- 重规划：`src/parking_opt/api/services/replanning.py`；
- 多车仿真与重放：`src/parking_opt/api/simulation.py`；
- FastAPI 与契约：`src/parking_opt/api/app.py`、`src/parking_opt/api/models.py`；
- Schema/OpenAPI：`schemas/v2/`；
- 冻结参数：`configs/web-v2/m3.toml`；
- 无 UI 演示：`scripts/run_web_v2_m3_demo.py`；
- 教学说明：`docs/architecture/web-v2/m3-state-routing-simulation-teaching.md`；
- 测试：`tests/web_v2/`。

## 实际验证

- Web v2 专项：81 passed，其中新增三项自动化 p95 性能门；
- 100 辆、10,000 事件：重放低于 2 秒、增量峰值内存低于 256 MB；
- Ruff：通过；
- Mypy 严格检查：18 个源/验收测试文件通过；
- v2 契约与 OpenAPI：36 个导出产物前后 SHA-256 一致；
- v1 只读基线：17 个关键文件 SHA-256 一致；
- 无 UI 演示：推荐软锁、期限不续期、偏航重规划、占用离场、纵深移位和重放全部通过；
- 隔离全仓回归：仅规范化历史 D2/D3 换行后 306 passed；
- 正式工作树全回归：286 passed、5 failed、12 errors，失败均由既有 D2/D3
  `D1_HASH_MISMATCH` 连锁触发；
- 唯一警告：FastAPI TestClient 的 `httpx` 到 `httpx2` 迁移弃用提示，当前行为正常。

## 失败案例与限制

- 缓冲位不足会记录 `BUFFER_CAPACITY_INSUFFICIENT`，不做部分移位；
- 未来通道负载、不可达路线、错误版本、幂等载荷冲突和篡改重放均失败关闭；
- 单进程内存存储不支持多 worker 生产一致性；M4 只能将其作为答辩原型后端使用；
- 事件前后哈希保护管理状态和运行身份，纯展示字段并非密码学签名；
- 四个停车场仍是 synthetic 演示数据，不能声称为真实运营性能；
- 历史 D2/D3 换行哈希问题继续独立维护，不能通过改写旧证据掩盖。

## 恢复与下一步

M3 已获批准。下一步建立 M4 ExecPlan，复核已批准的 C 融合视觉原型，冻结 React 信息架构、
响应式断点、API 状态映射与视觉验收清单，再实现车主模式 React 前端。M4 不得擅自加入答辩
自由实验台、真实数据连接器或新推荐算法。
