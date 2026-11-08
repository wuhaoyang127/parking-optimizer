---
project: 智能停车优化与调度系统 Web v2
status_version: 51
last_updated: 2026-10-18
governance: AGENTS.md
requirements: docs/product/web-v2-requirements.md
decision_log: docs/product/web-v2-decision-log.md
implementation_blueprint: docs/product/web-v2-implementation-blueprint.md
current_milestone: M4
milestone_status: awaiting_review
current_exec_plan: docs/plans/web-v2/m4-route-presentation-integration-handoff.md
latest_handoff: docs/handoffs/web-v2/m4-driver-react-handoff.md
current_blockers: []
downstream_prerequisites: ["M6: 提供真实 Safari/iPhone 验证设备或在进入 M6 前调整兼容性承诺", "M6: 免费公网平台可用；不满足时由用户决定更换免费方案或取消公网验收"]
next_approval_gate: M4_R6_entry_exit_completion_review
implementation_authorized: false
---

> 2026-10-30 整合交付说明：下文保留原包历史阶段状态。本次用户另行授权的两站本地对接已实施；当前范围、验证和限制以仓库上一级 README-INTEGRATED.md / VALIDATION.json 为准，不代表历史里程碑或公网部署获验收。

# Web v2 当前状态

> 本文件是 Web v2 的独立状态入口。旧项目的 `PROJECT_STATUS.md` 不记录 Web v2 进度，也不
> 决定 Web v2 的阶段、阻断项或唯一下一步。

## 1. 一句话目标

构建面向普通车主、兼顾大创答辩的高质量停车商业化演示原型，采用 React + TypeScript +
FastAPI，复用但不改写现有 Python 算法证据，并为真实停车场数据和后续算法接入预留接口。

## 2. 当前快照

- **当前里程碑**：M4；
- **当前状态**：`awaiting_review`（路径展示/渲染改进及原门复验完成；用户尚未验收M4，开发对接包按清单/回执交付）；
- **需求访谈**：已完成；
- **需求规格**：已记录；
- **决策日志**：已记录；
- **一致性消歧蓝图**：用户已整体接受；
- **视觉方向**：C 融合方案已选定；
- **实施授权**：已关闭；本轮实现完成，允许按用户既定目标收口文档/白名单打包与解包复验；跨站部署及 M5 界面未实施；
- **当前 ExecPlan**：`docs/plans/web-v2/m4-route-presentation-integration-handoff.md`；
- **最近交接**：`docs/handoffs/web-v2/m4-driver-react-handoff.md`；
- **当前分支**：`codex/web-v2-m4-driver-react`；
- **高保真原型**：已完成并通过本地浏览器、11 项交互和响应式验证；
- **FastAPI 与 Schema v2**：M2、M3 已批准；状态、重规划、确定性多车仿真、运行/重放 API 与全部 p95 性能门已通过 81 项 Web v2 测试；
- **React 基线**：提交 `07226cd` 已完成找停车场、推荐/软锁、纵深确认、抽象路线、异常恢复、
  停车与离场；用户未接受当前简化路线图，要求完整停车场布局；
- **唯一下一步**：用户验收M4新版展示；组员依据开发交接包实施研究算法发布对接，不自动进入M5；

需求已经记录不代表可以自动创建分支、ExecPlan、视觉稿、React、FastAPI、v2 Schema 或安装
依赖。

## 3. 已确认的产品方向

- 默认车主模式，另有口令保护的答辩模式；
- 车主模式：找停车场、智能停车、当前行程；
- 答辩模式：项目总览、算法演示、纵深停车专题、研究证据、数据与扩展；
- 四个完整 synthetic 停车场：商场、学校、医院、交通枢纽；
- 车主命名空间唯一可运行的推荐算法是 `OnlineRuleServiceV2`（后端 ID `online-rule-v2`），车主
  界面统一称“智能推荐”；M5 答辩界面才显示“在线规则”和经验证的实验基线；
- 保留纵深车位、严格可恢复规则、缓冲移位和普通位备选；
- 30 秒软锁、确认后会话预留、动态路线和异常重规划；
- 多车管理层仿真，二维为完整基线，伪 3D 为性能允许下的增强；
- React + TypeScript + Vite 前端，FastAPI 应用层；
- v1 历史研究契约保持只读，Web v2 新建 v2 契约；
- 本地断网一键演示与免费公网部署并存；
- 现有 Streamlit 暂时保留，不作为新版技术限制。

完整需求见 `docs/product/web-v2-requirements.md`。

## 4. 独立里程碑

| 里程碑 | 内容 | 状态 |
|---|---|---|
| M1 | 两套视觉方向板与高保真交互原型 | `approved` |
| M2 | v2 契约、适配器、在线规则 v2 服务与 FastAPI 基础 | `approved` |
| M3 | 共享会话状态机、路由与确定性多车仿真核心 | `approved` |
| M4 | 车主模式 React 前端 | `in_progress`（R6.1 功能完成，最终验证未封存） |
| M5 | 答辩模式、自由实验台与条件增强 | `not_started` |
| M6 | 本地离线交付、公网部署与全端验收 | `not_started` |

M1 包含两个审批门：

1. 城市智慧出行 / 未来停车舱两套电脑与手机视觉方向板；
2. 方向获批后的 HTML/CSS 可交互高保真原型与 PNG。

## 5. 与旧项目的关系

- Web v2 是同仓库内独立管理的子项目；
- 旧 A-D 阶段进度和旧页面冻结不适用于 Web v2；
- Web v2 可以使用新的页面结构、React/FastAPI 技术和独立 M1-M6 流程；
- v1 算法、实验和证据是只读复用资产，不是 Web v2 的进度记录；
- 如需改变旧核心算法语义，必须通过显式适配或单独变更，而不是静默修改历史结论；
- Web v2 进度只更新本文件。

## 6. 当前阻断与开放项

当前实现门无开放阻断；M4 awaiting_review，待用户验收。开发源码包已按白名单生成并实际解包
运行：包内启动器、API健康、最终中性终点及桌面/手机可见行为通过；借用原冻结依赖，未做干净机
安装。Ctrl+C后8000/4173均ECONNREFUSED。最终带回执分发包身份以本轮package-receipt.json为准。
原production失败属于下方历史证据，当前展示构建已按冻结受控门复验通过；不扩大仿真例外。

### 前切片历史（已由当前展示改进与受控复验结果取代）

M4 R0a–R5 已实现并验收；R6 离场回放安全恢复点 `26a0399` 仅本地保留。R6.1 已完成“推荐阶段无
未来 blocker → 用户明确触发 → blocker 移至 buffer → 当前车辆进入深层位 → blocker 恢复 → 离场
复用同一协调记录”的闭环，并曾通过真实三端、四类 PUBLIC 布局、视觉与 production 性能门。R6.1 工作区未
提交、未推送；算法排序、v1、真实数据语义、关键依赖和 M5 均未改变。arrival 失败矩阵已补证。
上述游戏/电源叙述为历史记录。2026-10-17 接手实测仿真 pytest 2.7115064 s 失败，补充同负载
测量 1.982145 s 通过，存在波动；本轮未归因于特定进程。用户在重新询问后明确接受仅限 M4 演示
的性能例外：≤2.0 s 原门和所有失败保留，不宣称性能门通过，不扩张为 M3/M6 完成。独立审计另
发现 Route 缺中文转向/到达指引，以及需求表单显示内部 lot ID；用户已授权受限修复，其他范围不变。

受限修复已形成并验证：Ruff/Mypy/TS/lint/API/build、87 组件、10 mock、53 份 Schema/OpenAPI
通过；Web v2 + contracts 为 241 passed/1 failed，仿真 2.006702 s 仍按 PERF-01 例外保留失败。
当前构建真实矩阵 26 passed/1 skipped/1 failed：production 出现 6 个 >100 ms 长帧；独立隔离
复测又在推荐 p95 3057.531 ms >1000 ms 失败。新增 PERF-02 不在用户已接受的仿真例外范围内，
根因尚未证实。修复后桌面、393px 手机及 360px 名称/中文转向/到达指引已实拍。独立只读终审已
获用户明确授权。可选时序诊断仍推荐 p95 1059.538 ms 失败：超限样本 HTTP 约 292.4 ms、
响应结束至结果 DOM 出现约 482.4 ms，未记录 LongTask，页面始终可见；不据此断言外部负载。
诊断默认关闭，原样本数/断言未改；最终类型/lint 通过，首次类型/lint 失败也保留。独立终审已
给出 NO-GO，NAV-01/UX-01 和打包副本路径脱敏问题关闭，PERF-02 仍开放；未生成源码 ZIP。

### 后续里程碑前置条件

以下是后续前置条件，必须在目标里程碑前解决：

- M6：提供真实 Safari/iPhone 验证设备；若无法提供，必须在进入 M6 前由用户批准缩小 Safari
  兼容性声明，不能把自动化 WebKit 冒充实机验证；
- M6：免费公网托管平台仍可用且满足最低能力；如不可用，先报告并由用户决定更换免费方案或
  取消公网验收，不自动产生付费资源。

后续里程碑再决定：

- 免费公网托管平台；
- WebSocket 降级阈值；
- M6 的最终 `rc1` 验收清单。

## 7. 唯一下一步

用户验收 M4 新版路径展示。研究算法最终发布到车主端的实际跨站接入由组员按
docs/integration/web-v2/research-to-driver-handoff.md 和开发源码包实施；该包不是已完成对接或
M6 离线发布。打包身份、解包运行和清理结果以 docs/audits/web-v2/2026-10-18-route-handoff/
的 source-package-plan.json、development-review.json、package-receipt.json 和运行回执为准。
不得自动实现 M5 界面、创建 M5 分支、提交、合并 main、推送或打 tag。

## 8. 重要变更

- 2026-11-08（拆分与回归修复 + trial 生命周期）：用户另行授权的 driver 单文件 ≤200 行拆分已完成（48 个超限文件全部按功能拆分，`scripts/check_file_lines.py` 全绿）；拆分引入的状态机/路由/编码回归已修复，`tests/web_v2` 235 passed、`tests/test_driver_bridge.py` 4 passed；trial 生命周期（发布→校验→启用→试用（按比例分流）→决策→回滚）四阶段收口（数据层 / driver 逐请求 trial-ratio 分发 + trial 回执 / research 站试用控制面板 / 转正·备选·删除二次确认），新增 `tests/web_v2/test_research_trial.py` 8 项。以上属 trial-lifecycle 开发工作，不改变 M4 `awaiting_review`、`implementation_authorized: false`、M5 未授权边界，也未合并 main、未打 tag。

- 2026-10-18（展示完成）：共享静态图层memo/稳定引用、清晰路线/起终点、当前指引/演示进度和
  手机密度已完成；类型/lint/87组件与26真实功能通过。实质渲染改动后原production预算只跑一次
  通过（DT7Sgkzm构建）：推荐p95 381.98ms、入位158.32ms、离场106.13ms、长帧0；随后仅中性
  title文字修正（rVBs4Kqo），最终build/API漂移通过。PERF-02按原受控门复验通过，历史失败及
  未归因波动保留为限制，不另设“全负载稳定/唯一根因”门。仅PERF-01仍为已接受仿真例外。
  M4 awaiting_review、实施授权关闭，未标approved，用户未验收；开发对接包和运行回执另记。

- 2026-10-18（新目标）：用户要求尝试修复问题、改善路径演示展示、以双站对接为目标交付组员
  交接包，避免反复测试；明确选择研究站算法最终发布到车主端使用。本轮授权 M4 展示层及开发
  候选包准备，实际跨站连接由组员完成。正式封存的旧 NO-GO/性能失败保留，不伪装通过。

- 2026-10-18：完成受限指引/名称修复及相称回归。独立只读终审确认 NAV-01/UX-01 和打包副本
  路径脱敏已关闭，但 PERF-02 生产长帧及推荐 p95 失败未关闭，正式 NO-GO。诊断未确定原因，
  不继续挑最佳重跑；保持 M4 in_progress、原门及全部失败，不生成新源码 ZIP，不提交/推送。

- 2026-10-17：接手审计功能/契约 226、组件 83、mock 10、真实联调 27 passed/1 skipped；53 份
  Schema/OpenAPI 一致。发现 NAV-01（内部 ID 拼接指引，缺转向/到达）和 UX-01（表单显示 lot ID），
  用户明确授权仅修复中文方向指引和停车场名称，保持路径/距离/ETA/排序/状态机/Schema 字段不变。
  仿真原 pytest 2.7115064 s 失败，补充测量 1.982145 s、108,559 B、hash 一致；用户重新确认接受
  仅限 M4 演示的性能例外，原 ≤2.0 s 门及失败保留。审计证据在 docs/audits/web-v2/2026-10-17/。
  M4 保持 in_progress；M5、提交/推送和权威研究端架构变更未授权。

- 2026-09-01：R6.1 功能与真实全端验收完成，但独立终审暂为 NO-GO。FastAPI 原子形成入位 blocker，保存 before/after 设施快照、协调记录、
  replay/幂等/哈希，并由后续离场复用同一 blocker vehicle ID 和 buffer；React 共享面板完整回放
  入位与离场。Ruff、严格 Mypy、API 漂移、TypeScript、ESLint、build、前端 83、mock 10 均通过；
  真实 FastAPI + production preview 为 27 passed/1 skipped，Edge 桌面、Pixel 7、Chrome、四类
  PUBLIC 布局和 12 张阶段证据通过。冻结性能为 gzip 113,419 B、暖首屏 p95 206.14 ms、推荐 p95
  948.44 ms、arrival p95 342.71 ms、departure p95 159.93 ms、动画帧 p95 6.30 ms、长帧 0。
  Web v2 + contracts 组合曾为 226 passed；仿真性能门先隔离 1.83 s 通过，随后在活跃 GW2 高 CPU
  负载下全套 5.12 s、隔离 4.09 s 失败，不能用旧通过覆盖新失败。独立终审同时指出 arrival 专项
  需直接补齐路线不可达、会话错配和多 blocker 证据；三项已新增并以 arrival/departure 13 passed、
  Ruff 通过关闭。M4 保持 `in_progress`，授权仅限最终仿真性能复跑与文档同步；
  R6.1 未提交、未推送，M5 未授权。
- 2026-08-31：用户确认“推荐后形成 blocker、服务端原子协同入位、离场复用同一 blocker”的方案，
  并授权创建仅本地、不推送的 R6 离场安全恢复点。恢复点 `26a0399` 已按精确白名单创建；用户未跟踪
  资产和 `run.cmd` 未纳入。M4 重新置为 `in_progress`，实施授权仅限 additive 入位 replay、权威协调
  状态、前端回放、验证与交付文档；M5、算法排序、v1、真实数据语义和关键依赖仍未授权。
- 2026-08-21：完成 M4 R6。FastAPI 原子校验深层 Journey、真实浅深关系、专用 buffer、状态版本
  和三段同版本 Route，返回可幂等恢复的 additive replay；React 在共享完整画布上只回放权威事件，
  绿色当前车辆与橙色 blocker 分角色显示，并明确不代表实时定位或车辆控制。后端 172 项、前端
  82 项、mock 10 项、真实联调 27 passed/1 skipped 及全部静态/构建门通过；系统 Edge 桌面、Pixel 7
  与 Chrome 均完成 R6。最终 gzip 112,590 B、首屏 p95 154.49 ms、推荐 mutation p95 368.21 ms、
  replay mutation p95 92.67 ms、双车动画帧间隔 p95 6.20 ms、长帧 0；四张证据人工复核通过。
  M4 置为 `awaiting_review`，实施授权关闭，唯一下一步为用户验收 M4 R6；M5 未授权。
- 2026-08-21：用户批准 M4 R6 纵深协同离场回放。R6 仅在 synthetic 车主当前行程中复用既有
  纵深恢复顺序，以服务端计算的 blocker、buffer、Route、事件和状态哈希驱动双车辆过程回放；
  允许 additive Schema/API 与 `tandem-focus` fixture 调整。M4 重新置为 `in_progress` 并开启受限
  实施授权；M5 仍未授权，算法排序、真实数据语义、关键依赖和通用答辩仿真不变。
- 2026-08-21：用户验收 M4 R5，批准 M4，并授权按精确白名单创建、备注及推送单一 R5 恢复点。
  M4 状态改为 `approved`，当前 ExecPlan 清空，实施授权保持关闭；M5 仍未授权，未创建 M5 分支、
  未合并 main、未打 tag。R5 恢复点以本文件所在提交为准。
- 2026-08-21：完成 M4 R5。四套 PUBLIC 停车场各提供平峰、高峰远端、充电紧张和纵深协同四个
  固定 profile；FastAPI 按 driver 会话/停车场隔离，活动 Journey 固定，空闲态可原子切换，正常
  离场或 `DEMO_RESET` 后只为下一轮推进一次。新增三个独立 additive Schema、可选 profile 元数据
  和切换端点；算法排序、Journey/Route、Layout、legacy、真实源和 M5 边界未改。后端 166 项、前端
  79 项、mock 10 项、真实联调 24 passed/1 skipped 及全部静态/构建门通过；最终 gzip 109,276 B、
  首屏 p95 159.05 ms、mutation p95 327.01 ms、帧间隔 p95 7.40 ms、长帧 0。六张双视口证据人工
  复核通过。实现完成时 M4 置为 `awaiting_review` 并关闭授权，随后由用户验收；M5 未授权。
- 2026-08-21：用户确认并授权 M4 R5“确定性演示情景轮换”。R5 可为 synthetic 车主上下文和设施
  状态增加向后兼容的演示情景元数据及空闲态切换命令；FastAPI 按匿名会话和停车场持有固定情景，
  活跃行程内不切换，正常离场或演示重置后下一轮自动轮换。情景只改变当时合法可见的状态和成本，
  不强制推荐结果、不修改 `OnlineRuleServiceV2` 排序、不使用不可复现随机事件、不进入 M5。
- 2026-08-21：完成 M4 R4。四套 PUBLIC 布局在真实 FastAPI + production preview 下完成 Edge
  桌面/Pixel 7 推荐、确认、完整路线、偏航、显式停入和离场，四布局只读预览、纵深 replacement、
  Pixel 7 Fullscreen API 与 Chrome smoke 通过；最终 23 项为 22 passed、1 个按设计 skip。生产
  JS+CSS gzip 108,580 B，暖首屏 p95 152.60 ms，mutation p95 394.49 ms，动画帧间隔 p95 7.40 ms，
  >100 ms 长帧 0。后端 161 项、前端 78 项、mock 10 项及全部静态/构建/编排门通过；29 张证据
  人工复核通过，唯一 M4 handoff 已更新，独立终审 GO。实施授权关闭，等待用户验收 M4；M5 未授权。
- 2026-08-21：用户验收 M4 R3 恢复点 `2420c3a`，明确授权 R4 全端验收；授权限于四套 PUBLIC
  布局的真实 FastAPI + production preview 桌面/手机全流程、Chrome smoke、视觉证据、冻结性能门、
  必要缺陷修复、运行与交付文档、唯一 M4 handoff 和独立终审。M5、公共 Schema、算法语义、数据
  契约、关键依赖、main 合并和 tag 均未授权。
- 2026-08-20：完成 M4 R3 并通过独立终审。当前行程复用共享完整设施画布；Trip 与 session-aware 设施快照采用
  前后夹读和组合守卫，持续变化失败关闭。画布、步骤、距离、ETA 和车辆只消费同一权威 Route，
  车辆沿 edge centerline 做 UI 投影，时间仍仅由逐段 `travel_time_s` 决定。hidden/reduced-motion
  停止连续运动，其他车位仅本地只读查看，failed/终态不显示旧路线。夹读请求共享取消信号，
  StrictMode 重放会开启新恢复代次。前端 78 项、mock 双视口
  10 项、真实 FastAPI 22 passed/1 skipped、Web v2 后端 161 项及全部静态/构建门通过；两张 R3
  桌面/Pixel 7 视觉证据通过。实施授权关闭，等待用户验收 R3；R4/M5 未授权。
- 2026-08-20：用户验收 R2 恢复点 `f82cf34`，授权 R3 将当前行程迁移到共享完整画布；R4/M5
  未授权。
- 2026-08-20：完成 M4 R2。新增共享原生 SVG 画布与 `/parking/:parkingLotId/layout` 只读页，
  覆盖楼层筛选、车位/纵深/缓冲/方向/占用图层、鼠标/触控/键盘缩放平移、URL 引用失败关闭、
  约 3 秒可见页单飞轮询和无 claim/journey 副作用的同版本路线预览。前端 65 项、mock 双视口
  10 项、真实 FastAPI + production preview 22 项通过且 1 项按设计跳过，后端 161 项通过；
  八张四布局桌面/Pixel 7 视觉证据与独立只读复核通过。授权关闭，等待用户验收 R2；R3/M5 未授权。
- 2026-08-20：用户验收 R1 恢复点 `99a20d5` 并授权 R2 共享 SVG 布局画布与只读预览页；
  R3 当前行程迁移与 M5 未授权。
- 2026-08-20：完成 M4 R1。新增四套确定性完整设施资源与独立导出目录，容量为 48/28/32/52，
  PUBLIC 成为网站默认，legacy 仍仅内部显式选择；设施状态按 active claim 精确关联 Journey，
  状态/版本/占用同源。每列接入节点、真实单向停车巷、道路与车位不相交、全入口/目标/出口可达、
  纵深成功和缓冲不足失败均有回归。Python 3.11.15 下 Web v2 共 161 项通过；Ruff、严格 Mypy、
  TypeScript、ESLint、API 类型漂移及两名只读终审通过。实施授权关闭，等待 R2 用户决定。
- 2026-08-20：用户批准 R0b 恢复点并授权 R1 四套完整 synthetic 大布局、默认状态、PUBLIC catalog
  和权威兼容投影。R2 前端画布与 M5 未授权。
- 2026-08-20：完成 M4 R0b。新增三个 additive 资源、三个端点、独立 Schema/OpenAPI/TS 类型及
  public/legacy 构造边界；PUBLIC 在 R1 数据发布前稳定 503，不回退 legacy。Python 3.11.15 下
  Web v2 共 146 项通过，Ruff、严格 Mypy 定向、TypeScript、生成类型漂移、17 项 v1 哈希、旧
  OpenAPI 对象和四个 legacy fixture 均通过；两名只读终审 GO。授权关闭，等待 R1 用户决定。
- 2026-08-20：用户批准 M4 R0a 公共契约提案并授权 R0b。冻结三个 additive 资源及
  `/facility-layout`、`/facility-state`、`/route-previews` 端点；完整布局为未来唯一车主默认，
  legacy 仅允许内部显式选择。R0b 不生成四套大布局或绘制前端。
- 2026-08-20：用户未接受 M4 当前行程的抽象路线骨架，完成逐项需求访谈并重新打开 M4。已冻结
  四套大布局容量/纵深/充电/缓冲、共享 SVG 画布、车主布局预览、当前行程完整布局及兼容资源原则；
  M5 导入、编辑、实验基线和算法对比只记录接口，不提前实现。治理已精简，当前计划切换为完整
  布局 ExecPlan，实施授权关闭，等待新对话从 R0a 开始。
- 2026-08-13：完成 M4 P4 并进入 `awaiting_review`。后端 126 项、前端 54 项、严格类型、Ruff、
  Mypy、ESLint、OpenAPI 漂移、生产构建和 mock 双视口 8 项通过；真实 FastAPI + production preview
  14 passed、1 skipped，覆盖四停车场 Edge 桌面/Pixel 7 完整链、真实纵深 replacement 与 Chrome
  smoke。10 张视觉证据及冻结性能门全部通过；教学与唯一 M4 交接已生成，M5 未授权。
- 2026-08-13：完成 M4 P3.2。React 按服务端 legal operations 接入偏航、通道繁忙、外部占位、
  无法停入、ETA 两选项、显式停入、正常离场和 synthetic 重置；失败重规划停止旧路线动画，
  replacement、409 与离线均恢复权威快照。前端全量 53 项、P3.2 定向 21 项、TypeScript、ESLint、
  构建及桌面/Pixel 7 八项 E2E 通过；后端全量 126 项、Ruff、Mypy 通过。下一步 P4 全端验收。
- 2026-08-13：完成 M4 P3.2 后端兼容恢复点。新增 additive `DriverDemoReplanRequest` 与服务端
  确定性演示重规划命令；浏览器不再提交通道负载、任意节点或观察时间。命令及 reset-demo 仅允许
  synthetic driver，一致性错配在 mutation 前失败关闭；幂等重放绑定 expected version 与布局，
  stale/过期不计算新路线。定向后端 40 项、Web v2 全量 126 项、Ruff、严格 Mypy、生成类型漂移、
  TypeScript、ESLint 与独立只读终审通过；下一步实现 UI。
- 2026-08-13：完成 M4 P3.1 当前行程基础界面。场内 SVG、距离/ETA、文字步骤与车辆插值均消费
  同一权威 Route，动画按逐段 travel_time 推进且不会自动占用；预留期限采用服务端观察时间和
  单调时钟，到期立即恢复。前端 39 项、TypeScript、ESLint、生产构建与桌面/Pixel 7 八项 E2E
  通过；下一步 P3.2，成本更新仍须后端权威负载输入。
- 2026-08-13：完成 M4 P3.0 后端/契约恢复切片。新增 `DriverTripSnapshot 1.0.0`，恢复最新路线、
  位置和最近重规划；补齐车主命令会话守卫、期限失败关闭、无法停入/ETA 超窗原子重推及
  `DEPARTED + DEMO_RESET`。后端 119 项、前端 30 项、Ruff、严格 Mypy、生成类型、TypeScript、
  ESLint 和生产构建通过；冻结 Journey/Route/四场景零差异，下一步 P3.1 当前行程界面。
- 2026-08-13：完成 M4 P2 推荐/软锁的代码与单元/契约门禁。新增 server-derived driver context、
  按匿名会话恢复完整推荐、纵深拒绝后新 attempt、历史拒绝排除和至多一个合规备选；React 完成
  普通/充电、WAITING、服务端校时倒计时、纵深知情确认、原子备选与断线恢复。后端 107 项、
  前端 30 项、Ruff、严格 Mypy、TypeScript、ESLint 和生产构建通过。复用系统 Microsoft Edge
  完成桌面/Pixel 7 六项 Playwright 验收，包含真实 P2 软锁纵深推荐与无横向溢出；P2 完成。
- 2026-08-13：完成 M4 P2 第一恢复点。停车场列表/单体 GET 接受可选 `X-Session-ID`，在同一锁
  内清理当前 driver 会话期限并按基础可用 ID 减声明/异常位并集；推荐路径复用同一快照，前端
  稳定保存匿名会话 ID。后端 98 项、前端 24 项、Ruff、严格 Mypy、OpenAPI 漂移、TypeScript、
  ESLint、构建和双视口 4 项 E2E 通过；冻结 M3 Schema/四场景与 v1 边界不变。P2 推荐 UI 尚未开始。
- 2026-08-13：完成 M4 P1。新增兼容的 `DiscoveryArea 1.0.0` 独立资源，不修改已批准的
  `ParkingLot 2.0.0`；完成搜索、区域参考点、场外摘要、桌面三栏、手机详情抽屉、异常和真实性
  状态。后端 89 项、前端 22 项、Ruff、严格 Mypy、TypeScript、ESLint、构建和双视口 4 项 E2E
  通过；旧 M3 Schema/四场景与批准标签零差异，v1 哈希通过。P2 尚未开始。
- 2026-08-13：完成 M4 P0；Node 24 LTS 便携运行时通过官方 SHA-256，前端依赖精确锁定且 0 漏洞、0 缺失许可证；OpenAPI 类型漂移、单元测试、严格类型、ESLint、生产构建及桌面/手机 Playwright 通过，进入 P1。
- 2026-08-13：从 `web-v2-m3-approved` 基线创建 `codex/web-v2-m4-driver-react` 分支与 M4 ExecPlan；M4 仅覆盖车主模式 React 前端，先执行 P0 工程与契约基线，M5 未授权。
- 2026-08-13：用户要求确认 M3 完成后进入下一阶段；补齐状态命令、推荐并软锁、动态重规划三项 p95 自动化门，Web v2 81 项、Ruff、严格 Mypy、v1 保护哈希与隔离全仓 306 项通过；M3 正式批准。
- 2026-08-13：完成 M3 P4 与阶段交接；新增仿真运行/重放 API、无 UI 演示和教学说明，状态哈希绑定运行身份；78 项 Web v2、Ruff、严格 Mypy、v1 保护哈希及隔离副本全仓 303 项通过，状态进入 `awaiting_review`，M4 未授权。
- 2026-08-13：完成 M3 P3；确定性二维管理层事件引擎覆盖纵深移位、缓冲不足、重放哈希和篡改检测，100 辆/10,000 事件性能门通过；76 项 Web v2 测试、Ruff 和严格 Mypy 通过。
- 2026-08-13：完成 M3 P2；外部占位原子终止旧 attempt、持久排除异常位并创建新 attempt，事务失败完整回滚；未来负载失败关闭；70 项 Web v2 测试、Ruff 和严格 Mypy 通过。
- 2026-08-13：完成 M3 P2 第一恢复点；完整通道负载生成版本化成本快照，偏航/成本更新、ETA 超窗和不可达重规划均不续期并可审计；66 项 Web v2 测试、Ruff 和严格 Mypy 通过。
- 2026-08-13：完成 M3 P1；原子备选切换保留原软锁期限并同步新路线，`WAITING` 仅由显式重试触发恢复；独立 Schema、OpenAPI、59 项 Web v2 测试、Ruff 和严格 Mypy 通过，进入 P2。
- 2026-08-13：用户验收 M2 并授权 M3；创建 `web-v2-m2-approved` 标签与 `codex/web-v2-m3-state-simulation` 分支，冻结 driver/defense TTL 为 30 分钟/2 小时、ETA 余量 60 秒及单进程 synthetic 性能预算，M4 未授权。
- 2026-08-13：修复 M2 时区/有限数值、布局引用与纵深连续性、v1 超时误报、推荐数据源/失败码、真实源 503 一致性及结构化 500；M2 专项 32 项、规范化历史夹具的临时全仓 257 项、Ruff、Mypy 与 v1 保护哈希通过，状态恢复 `awaiting_review`。
- 2026-08-12：用户授权修复 M2 验收复核问题；状态退回 `in_progress`，范围限于契约边界、超时/失败语义、数据源错误分类、结构化 500 与对应回归，不修改 v1、不进入 M3。
- 2026-08-12：完成 M2 v2 契约、四个 synthetic 场景、动态路径、v1 只读适配、在线规则 v2、结构化错误、OpenAPI 与 FastAPI 端点；M2 专项 13 项及临时规范化旧夹具后的全仓库 237 项通过，状态进入 `awaiting_review`，M3 未授权。
- 2026-08-12：确认历史 D2/D3 Git blob 的 CRLF 与 artifact-index 的 LF 哈希不一致会导致当前工作树旧版回归失败；未修改历史资产，记录为独立维护风险。
- 2026-08-12：用户明确允许启动下一步 M2；创建 `codex/web-v2-m2-contract-api` 分支和 M2 ExecPlan。当前授权限于 v2 契约、API、只读适配与在线规则 v2，不进入 M3/M4。
- 2026-08-12：用户确认页面初步设计可以通过；M1 状态改为 `approved`，生成唯一阶段交接摘要。当前无活动 ExecPlan，M2 实施授权保持关闭。
- 2026-08-12：完成 C 融合方向零依赖高保真交互原型、四张 Edge 响应式截图和 11 项 Playwright 交互/布局验证；M1 第二审批门进入 `awaiting_review`，实施授权暂停。
- 2026-08-12：用户选择 C 融合视觉方向；车主端采用“城市智慧出行”的明亮地图结构，答辩端吸收“未来停车舱”的科研驾驶舱和动态语言。M1 第二审批门启动，授权仅覆盖静态高保真交互原型和 PNG 验证。
- 2026-08-12：完成 M1 第一审批门的“城市智慧出行”和“未来停车舱”两套方向板、提示词归档与视觉评审；状态改为 `awaiting_review`，实施授权暂停，唯一下一步为用户选择 A/B/C/D。
