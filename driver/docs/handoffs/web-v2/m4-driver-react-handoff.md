# M4 车主模式 React 唯一交接摘要

## 2026-10-18 新目标当前恢复点

- 用户要求改善路径演示/展示并交付组员两站对接包，明确研究算法最终发布到车主端使用。
  实际跨站连接由组员完成，发布/校验/启用/回滚指南及示例在 docs/integration/web-v2/。
- 当前状态 v51：M4 awaiting_review、实施授权false；用户尚未验收，未标approved。计划
  docs/plans/web-v2/m4-route-presentation-integration-handoff.md。M4展示层
  已形成：路线边界/起终点、当前转向与进度、手机密度、静态图层memo及稳定引用。保持路径、
  成本、算法/状态机/Schema/依赖不变；研究算法当前没有注册或执行，默认仍online-rule-v2。
- 类型/lint/87组件通过；真实Edge桌面/手机与Chrome共26功能用例通过。展示改动后production
  只跑一次原门并通过：gzip114707B、首屏206.27ms、推荐381.98ms、入位158.32ms、离场106.13ms、
  825帧/p95 6.2ms/长帧0。最后仅将共享SVG终点title改为中性文字，最终build/API漂移均0；
  最终JS为index-rVBs4Kqo.js。没有为字面量重复全套性能测试。
- 本轮5张新视觉及原始日志/源码恢复字节在 docs/audits/web-v2/2026-10-18-route-handoff/。
  前阶段所有性能失败、旧NO-GO及仿真例外保留；一次通过不宣称全部负载稳定或唯一根因确定。
- PERF-02按冻结受控门复验通过；历史波动保留为限制，不要求额外证明唯一根因/全负载稳定。
  新包为开发对接材料，不声称M4用户验收或M6离线发布。最终独立复核、清单/hash与解包运行
  见本轮development-review.json/package-receipt.json及运行回执。唯一下一步：用户验收M4；
  组员按发布/启用/回滚指南实施跨站连接。
- 开发源码包已实际解包运行：START-WEB-V2.cmd成功构建最终rVBs4Kqo并启动双服务，API模块来自
  解包src，健康200；最终中性title/桌面手机无横向溢出已复核。借用现有冻结依赖，非干净机安装。
  Ctrl+C后两回环端口ECONNREFUSED；最终分发包增加该回执/实拍，源码身份与运行版本相同。
- Git仍为codex/web-v2-m4-driver-react / 26a0399，上游0/1，暂存为空，无提交/推送/合并/tag；
  用户未跟踪资产未读取内容、修改或打包。

## 前切片恢复点（已由上方新目标取代，证据目录 2026-10-17）

- 分支 `codex/web-v2-m4-driver-react`；HEAD `26a0399f11d67211644887b840c361ba7d90e493`；
  上游同名，0 落后 / 1 领先；暂存区空。R6.1 和本轮修复均保留为工作区 Diff，未提交、推送、合并或 tag。
- 权威状态 v48：M4 `in_progress`，`implementation_authorized: true` 仅限当前受限修复与验证；
  计划 `docs/plans/web-v2/m4-driver-tandem-entry-exit-replay.md`，gate 不变；M5 未授权。
- NAV-01/UX-01 已获用户授权并修复：后端派生中文转向/到达指引，前端既有 GET 显示中文停车场名。
  路径、距离、ETA、排序、状态机、Schema 字段和关键依赖不变。失败/错配/取消守卫及退化有测试。
- 静态检查、87 组件、10 mock、53 份 Schema/OpenAPI 通过；Web v2 + contracts 为 241 passed /
  1 failed（仿真 2.006702 s）。用户重新确认接受仅限 M4 演示的 PERF-01 仿真例外，保留原 ≤2.0 s
  门和全部失败，不写“性能门已通过”，不构成 M3/M6 豁免。
- **PERF-02 仍阻断封存**：修复后真实矩阵 26 passed / 1 skipped / 1 failed；生产动画 6 次
  >100 ms 长帧。隔离复测又推荐 p95 3057.531 ms >1000 ms。HTTP 响应约 268–393 ms，未证明
  端到端等待异常根因；不归因游戏/电源，不套用仿真例外，不用历史通过覆盖本轮失败。
- 证据：`docs/audits/web-v2/2026-10-17/audit-report.md` 第 6 节、`real-fixed.log`、
  `performance-isolated.log`、各自 trace/截图、`visual-index.md`；27 张本轮新图含 4 张修复后
  名称/指引实拍和 1 张生产失败截图。当前构建 JS 为 `index-Bb1khuAY.js`。
- 用户已明确授权一个独立只读子代理终审；正式结论 NO-GO，未生成源码 ZIP、未转 awaiting_review。
  诊断运行仍推荐 p95 1059.538 ms 失败，未记录 LongTask 或页面隐藏，响应到 DOM 延迟尚未归因。
  最终诊断类型/lint 通过，首次失败保留。审查确认 NAV-01/UX-01、打包副本路径脱敏关闭；PERF-02 开放。
  拟打包白名单与逐文件 hash 在 `source-package-plan.json`；它只是候选计划。
- 开发复现准备、启动器模板、回滚原文件哈希验证和研究算法契约提案已形成；外部 Streamlit
  无法确认可访问，仅形成提案，未改变 M5 架构或接入接口。干净机安装/解包运行尚未执行。
- 用户未跟踪资产 `.codex-tmp/`、`data/parking-lots/`、`docs/business-plan/`、logo、`run.cmd`、
  旧 ZIP 未读取内容、修改、暂存或打包。无依赖安装、电源切换或未知进程终止。
- 唯一下一步：定位 PERF-02 的浏览器/调度耗时，再按原门验证并复核；不反复挑最佳样本。所有问题关闭且独立 GO 后才可关闭授权、等待用户 M4
  验收和生成白名单源码包。接收方须重新核验 Git 和权威文件。

## 2026-09-01 历史交接（以下各节已由上方当前恢复点取代）

### 历史交付结论

M4 R6.1 已完成纵深协同入位与离场闭环：推荐阶段不预知未来占用；用户导航到深层目标并明确触发
协同入位后，FastAPI 原子形成浅层 blocker，返回“blocker→buffer、当前车辆→深层位、blocker→
原位”的不可变证据；随后离场复用同一 blocker vehicle ID 和 buffer ID。React 只做服务端 Route
和 actor 的 UI 回放，不代表实时定位、车辆控制、自动驾驶或避碰。

M4 当前仍为 `in_progress`：功能完成，但冻结仿真门在用户活跃游戏高 CPU 负载下最新复跑失败，需
安静环境最终复跑并取得独立 GO。M5 未授权。

## Git 与权威状态

- 分支：`codex/web-v2-m4-driver-react`；上游同名；
- R6 离场安全恢复点：`26a0399f11d67211644887b840c361ba7d90e493`，仅本地、未推送；
- R6.1 没有 commit/push 授权，当前结果保留为精确工作区 Diff；
- 当前计划：`docs/plans/web-v2/m4-driver-tandem-entry-exit-replay.md`；
- gate：`M4_R6_entry_exit_completion_review`；
- 唯一下一步：安静环境按原 ≤2.0 s 门复跑冻结仿真用例并独立复核；不得自动进入 M5。

## R6.1 实现与边界

- 新增独立 `DriverTandemArrivalRequest/Replay 1.0.0` Schema、OpenAPI、生成类型和 synthetic-only
  端点；`DriverTripSnapshot` 仅增加 arrival 能力与可选 replay，既有 departure 资源和普通端点保持；
- FastAPI 在同一 `atomic()` 内校验 driver/session、PUBLIC synthetic、深层 `NAVIGATING` Journey、
  `tandem-focus`、lot/layout/scenario/state/cost、真实浅深关系、buffer 与三阶段 Route；成功后保存
  before/after 完整设施快照、哈希、最终 `OCCUPIED` Journey 和协调记录；
- 设施投影把协调 blocker 标为权威 `OCCUPIED`；目标和 blocker 最终均 occupied，buffer available；
  stale、buffer 忙、路线不可达、身份错配或持久化异常均在原子边界回滚；
- departure 存在协调记录时必须复用相同 blocker、vehicle ID 和 buffer；保留 `26a0399` 兼容路径，
  feature flag 关闭 arrival 后仍可走普通 `/occupy`；
- 共享 `TandemReplayPanel` 覆盖 arrival/departure；深层 eligible Journey 使用明确按钮“我已到达，
  开始协同入位”，完成后可重播、查看停车状态并继续离场；reduced motion 逐阶段静态查看；
- 没有新增/替换依赖，没有修改 `OnlineRuleServiceV2` 排序、v1、公共算法语义、真实数据语义、
  legacy、普通位流程或任何 M5 功能。

## 实际验证

- Ruff 通过；严格 Mypy：22 个 API 源文件通过；API 生成类型无漂移；
- R6.1/契约定向：62 passed；入位/离场/profile 定向：15 passed；
- Web v2 + contracts 组合曾为 226 passed；冻结仿真用例先隔离 1.83 s 通过，随后在用户活跃 GW2
  高 CPU 负载下 Web v2 全套 5.12 s、隔离 4.09 s 失败。最新失败尚未被覆盖，≤2.0 s 门待安静
  环境最终复跑；没有放宽阈值；
- 前端 Vitest：83 passed；TypeScript、ESLint、production build 通过；mock 双视口 10 passed；
- 真实 FastAPI + production preview：27 passed、1 个移动端性能项目按设计 skip。Edge 桌面、
  Pixel 7、系统 Chrome 的入位/离场闭环通过；四套 PUBLIC 停车场全流程与布局预览保持通过；
- 最终 production 性能门：JS+CSS gzip `113,419 B`；暖首屏 p95 `206.14 ms`；推荐 mutation p95
  `948.44 ms`；arrival replay p95 `342.71 ms`；departure replay p95 `159.93 ms`；动画帧间隔
  p95 `6.30 ms`，>100 ms 长帧 `0`；全部满足 production 门槛；
- arrival/departure 专项新增会话错配、buffer Route 不可达和双 blocker/双 buffer 顺序证据，合计
  13 passed；独立复审确认原测试矩阵超报已关闭；
- 当前 12 张双视口阶段证据位于 `docs/visual-qa/web-v2/m4-r6/`，覆盖入位/离场的 blocker→buffer、
  当前车辆移动和完成态；已人工检查文本、角色、buffer、滚动、横向溢出和真实性声明。

## 保留失败与环境限制

- 全仓 `pytest -q` 在收集历史 Streamlit `tests/application` 时因仓库 `.venv` 缺可选 `blinker`
  失败；AGENTS 明确旧 Streamlit 不参与 Web v2 完成判断，未擅自安装或替换依赖；
- 冻结仿真性能最新复跑受活跃 GW2 高 CPU 负载影响仍未通过；真实 production 性能门全部通过，
  但在仿真 ≤2.0 s 最终复跑成功前独立终审保持 NO-GO；
- Starlette TestClient 仍报告既有 httpx 弃用警告；不影响结果，未为消警告更换关键依赖；
- 每次真实 E2E 结束均确认 8000/4173 释放，不遗留旧服务。

## 运行、回滚与用户资产

- 一键运行：`npm --prefix apps/web run demo`；详情见
  `docs/delivery/web-v2-m4-driver-runbook.md`；
- 教学：`docs/architecture/web-v2/m4-driver-react-teaching.md`；
- 第一层回滚：关闭 `driver_demo.tandem_arrival_replay_enabled`，恢复普通 `/occupy`；第二层回滚到
  本地安全恢复点 `26a0399`；
- 用户未跟踪资产保持未跟踪、未修改、未删除、未暂存：`.codex-tmp/`、`data/parking-lots/`、
  `docs/business-plan/`、`docs/design/web-v2/logo/` 和 `run.cmd`；
- 接收方必须自行核验 Git、权威状态、计划、完整 Diff、测试与证据，不能只依赖本摘要。
