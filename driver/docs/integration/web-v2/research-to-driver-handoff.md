# 组员接手：研究站算法发布到车主端

状态：2026-10-18 用户已明确选择此最终方向；**跨站连接尚未实现**。本轮交付可运行的 React/
FastAPI 车主端、发布契约候选和接入任务。外部研究站为
https://parking-optimizer-7hnnrhr2fdf2redwicwznr.streamlit.app/ ，工具未能读取该站点，未核实远端
源码、版本、登录和 API。请先取得研究站仓库/部署版本；不能把页面 URL 当算法 API。

## 目标和责任

研究站训练/实验 → 发布版本化算法 → FastAPI 暂存并校验 → 启用已验证发布版本 → 车主使用
“智能推荐”。失败可回滚到 online-rule-v2；车主浏览器不连接 Streamlit 会话或执行算法代码。

组员负责研究站入口、算法抽离、发布通道、后端适配/注册/启用与联调；接手前先运行本地车主端，
保留当前推荐、30秒软锁、预留、纵深入位/离场、偏航和失败关闭。车主界面无需暴露算法参数。

## 从这些代码接入

| 文件 | 现有职责 / 对接改动点 |
|---|---|
| src/parking_opt/api/services/online_rule.py | 当前推荐实现；可作为统一推荐服务接口的基准，实现类需抽成 Protocol 再由 dispatcher 选择已启用版本 |
| src/parking_opt/api/adapters/v1.py | 当前只读 v1 可行性/恢复性适配；不能把 v1 排序强加给新算法，但应用层统一硬约束仍必须保留 |
| src/parking_opt/api/registry.py | 当前只有 online-rule-v2 可用，其余 pending；“登记名字”不等于实际执行，require_online_algorithm 不是通用 dispatch |
| src/parking_opt/api/app.py | create_app 当前构建单一 OnlineRuleServiceV2，注入 recommender；同时要核对无状态推荐与 Journey 服务的依赖，不能只改一个端点 |
| src/parking_opt/api/services/journey.py | 会话推荐/确认/备选与软锁原子边界；这里仍需对新算法输出做当前状态复核和原子 claim |
| src/parking_opt/api/routing.py | FastAPI 的权威有向路由；研究端给出的路线建议不能直接成为车主权威路线 |
| src/parking_opt/api/models.py、schemas/v2/ | 当前 DriverRequest/Recommendation/Route 与生成契约；新增发布资源须 additive、独立版本化，不给 Layout 2.0.0 增必填字段 |
| apps/web/src/api/recommendationClient.ts | 车主只消费 FastAPI 的统一结果；现有运行时校验需要与正式生成契约同步 |

现有 RecommendationRequest 有 algorithm_id 字段，Recommendation 也有 algorithm_id/version；
**不能据此声称任意算法已经可选**。当前 registry、构造注入及 Journey 流程仍固定现有实现。

## 推荐交付形式

先把算法从 Streamlit 页面抽成不依赖 UI 的 Python 3.11 包：输入不可变可见快照，输出候选排序，
不直接操作 SessionStore、Journey、软锁或占用。两站使用同版本包可以减少环境差异。

需要 GPU/独立依赖时再提供单独算法 HTTP 服务，由 FastAPI 服务端适配，设置连接/执行预算、
隔离/取消和过期结果处理。HTTP 超时不表示远端已停止；不能无限重试。共享包更新同样通过
审核发布流程，不在车主运行进程上传后直接 import 任意 Python 或反序列化不可信 pickle。

密钥放服务端环境，跨站通道 HTTPS/鉴权；发布权限和车主会话分离。包内不放口令或真实用户数据。
本轮无新关键依赖；若引入推理库，先确认许可证、Python/Windows 支持、包体、锁定和部署影响。

## 契约候选：发布与启用

以下为待组员实施的独立 research-release 1.0.0 资源，**不是现有 API**。正式实施时同步 Python
模型、JSON Schema、OpenAPI、生成类型、迁移/回滚说明和相称测试。相邻 JSON 文件只作示例。

| 资源 | 必需内容 |
|---|---|
| AlgorithmRelease | release_id，algorithm_id/version，allocation/prediction 类别，artifact/源码/锁文件 SHA-256，入口、输入输出契约、Python/平台、可见信息策略、预算、seed 能力、依赖与来源 |
| ReleaseValidation | release/input/fixture/validator/route 版本和 hash，逐项通过/失败/未运行，实际耗时/内存，原失败记录；不能由研究端自报 certified |
| DriverActivation | 当前/目标 release hash、激活作用域、操作者/时间、校验记录、回滚目标；同键同版本幂等，不同内容冲突 |
| ExecutionReceipt | requested/executed 算法及版本、输入 hash/as_of/seed、耗时、校验/降级原因、release hash；与每个 Recommendation/Journey 绑定 |

发布状态建议 draft → validating → validated → staged → active，失败为 failed，已替换为 inactive。
这与现有 AlgorithmDescriptor 的 online/pending 枚举分开保存，不原地改旧枚举。启用必须原子
切换一个版本指针；已存在的行程固定其发布版本和输出证据，不在导航途中换算法或覆盖路线。

建议的新端点草案（待实现）：POST /api/research/v1/releases；POST .../{id}/validate；
POST /api/admin/v1/driver-algorithm-activations；GET .../active。发布者不能直接越过验证写 active。
发布/管理端点必须服务端鉴权，不能复用普通车主的 session header 或仅靠前端隐藏按钮。

## 在线输入、输出与复核

输入只含 as_of 当时可见的布局/状态/成本、当前 DriverRequest、用户输入及标注来源的预测。
独立保存 layout/state/cost/version/hash、观测时间、来源健康、可见信息策略、参数、seed 和预算；
禁止未来事件、oracle、未来真实离场时间以及其他会话的可变软锁状态泄漏给算法。

算法输出可先采用：request_id + input_hash + release_hash + status + **有序候选 space_id** +
可解释 reason_codes/求解耗时。不要要求研究算法生成 SessionStore 或 Route 对象。

FastAPI 必须拒绝重复/未知/跨停车场候选、版本错配和过期响应；复核 unknown/occupied/claimed、
充电条件、buffer 不可推荐、纵深 stack/depth/恢复性/专用 buffer、方向/连通及真实源失败关闭。
主推荐及至多一个合规备选必须同硬条件；应用层计算权威 Route，成功创建软锁后才交给前端。
不合法候选不能偷偷修正后冒充原算法成功；timeout/异常/无解保留为真实失败或明确标注降级。

回退必须记录 requested_algorithm/executed_algorithm、原失败和原因；只回退到已验证可用版本，
界面继续显示清楚的服务降级信息。状态不健康、没有合规候选时失败关闭，不能把 unknown 当空闲。

## 实施顺序与验收

1. 获取研究站仓库、冻结算法版本和现有输入/输出，确认是分配算法还是预测模型；将 UI 依赖移出
   算法入口。先用一个人工小布局对齐字段、单位、状态和结果。
2. 冻结 additive 发布契约、候选输入/输出和 canonical JSON hash 规则；数组顺序、UTC/as_of、
   有限数值和 null 规则写清。对旧客户端、fixture 和开关关闭路径提供兼容性证据。
3. 实现隔离运行与适配，验证畸形/超大输出、超时、异常、过期、重复请求、跨 namespace、未来
   泄漏、unknown、busy buffer、不可达和事务回滚。随机算法记录 seed，不把算法自报当通过。
4. 在 research 命名空间完成同布局/状态/需求/可见信息/预算对比，保存所有失败，再做服务端
   shadow 校验；shadow 不写 driver claim 或占用。
5. 用 validated release 激活新车主请求，确认 API 实际执行新版本；完整走推荐→锁位→确认→
   指引→显式停入→离场。包含普通位、充电、纵深、无解/断线和桌面/手机。新算法不能越过硬约束。
6. 演示回滚：切回 online-rule-v2，确认新请求使用旧版、存量行程证据保留、研究端离线仍能使用
   已发布版本；保存激活/回滚和失败回执。

这六步完成后，才可声称“两站对接与研究算法进入车主端”已完成。当前包只完成车主端展示改进
和接手材料；实际验证、已知性能波动及启动方式见包根 START-HERE.md 和本轮审计报告。
