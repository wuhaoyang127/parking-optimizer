---
milestone: M2
status: awaiting_review
handoff_date: 2026-08-13
branch: codex/web-v2-m2-contract-api
next_milestone: M3
---

# Web v2 M2 契约、API 与在线规则交接

## 验收结论

M2 已完成实现和开发侧验证，等待用户验收。当前后端可列出学校、医院、商场和交通枢纽四个
明确标注为 synthetic 的停车场，读取布局与算法状态，并提交在线规则推荐请求。M2 不创建
软锁、预约或会话状态，也没有进入 React 或多车仿真。

## 已冻结口径

- API 前缀为 `/api/v2`，Schema 版本为 `2.0.0`；
- 所有资源用 `parking_lot_id` 隔离，距离单位米、耗时单位秒、时间戳带时区；
- v1 只读适配负责既有可行性与纵深阻挡检查，v2 负责充电硬条件和当前成本快照排序；
- 可行候选按不可恢复风险、动态 ETA、距离、深度、稳定 ID 的词典序排序；
- 真实数据源未配置时返回 503，不隐式使用 synthetic 数据；
- M2 推荐固定返回 `claim_status=not_created_m2`，不创建资源声明；
- 推荐响应携带 `DataSourceStatus`；失败响应用 `failure_code` 区分超时与适配失败；
- 外部时间必须带时区，非有限数值、跨作用域引用、未知通道/缓冲位及纵深深度断层均失败关闭；
- 只有 `online-rule-v2` 可选择；模拟退火与随机森林明确为待接入。

## 关键文件

- 契约源：`src/parking_opt/api/models.py`；
- JSON Schema 与 OpenAPI：`schemas/v2/`；
- 场景：`data/synthetic/web-v2/`；
- 路径：`src/parking_opt/api/routing.py`；
- v1 适配：`src/parking_opt/api/adapters/v1.py`；
- 推荐服务：`src/parking_opt/api/services/online_rule.py`；
- FastAPI：`src/parking_opt/api/app.py`；
- 教学说明：`docs/architecture/web-v2/m2-contract-and-online-rule-teaching.md`；
- 测试：`tests/web_v2/`。

## 实际验证

- M2 专项：32 passed；
- Ruff：通过；
- Mypy 严格检查：12 个 API 源文件通过；
- v1 只读基线：17 个关键文件 SHA-256 一致；
- 全仓库回归：临时副本中规范化历史 D2/D3 换行后 257 passed；
- 当前工作树直接全回归：239 passed、5 failed、12 errors，均由已有 D2/D3 artifact-index 的
  LF 哈希与 Git blob 中 CRLF 字节不一致引起，M2 专项和 v1 哈希均不受影响；
- 唯一警告：FastAPI 0.139.2 的 TestClient 提示未来由 `httpx` 迁移到 `httpx2`，当前行为正常。

## 失败案例与限制

- 真实数据模式没有连接器，按设计失败关闭；
- v1 评估不完整会显式返回 `V1_ASSESSMENT_TIMEOUT`；M2 不在超时后静默选择备用车位，后续若
  引入新求解器仍须为各算法单独设计可审计降级策略；
- `SessionStore` 只有协议，实际会话、幂等、软锁和预留属于 M3；
- 四个场景是契约与算法边界用的小型模拟数据，不代表真实停车场容量或性能；
- 历史 D2/D3 换行哈希问题应作为独立维护任务处理，不应与 M2 契约审批混在一起。

## 恢复与下一步

M2 验收前不进入 M3。用户验收后，应创建独立 M3 ExecPlan，先冻结会话 TTL、30 秒软锁、
确认后预留、ETA 安全余量和仿真性能预算，再实现共享状态机与多车仿真。
