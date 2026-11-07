---
document: web-v2-decision-log
status: active
version: 1.25.0
last_updated: 2026-10-18
requirements: docs/product/web-v2-requirements.md
status_file: WEB_V2_STATUS.md
governance: AGENTS.md
implementation_blueprint: docs/product/web-v2-implementation-blueprint.md
---

# Web v2 产品决策日志

## 1. 用途

本文记录 Web v2 关键产品决定及其理由。当前有效需求以
`docs/product/web-v2-requirements.md` 为准。后续改变以下决定时，必须先在本文追加新记录，
说明旧决定、新决定、影响、验证和回滚，再更新需求规格和实现。

Web v2 的进度只记录在 `WEB_V2_STATUS.md`。旧 `PROJECT_STATUS.md` 只提供发现入口，不参与
Web v2 的里程碑、阻断和审批判断。

## 1.1 2026-08-12：与旧项目独立治理

### 决定

- 根目录 `AGENTS.md` 作为 Web v2 唯一治理规则，`WEB_V2_AGENTS.md` 只保留迁移提示；
- 使用独立的 `WEB_V2_STATUS.md`；
- 旧项目状态不记录 Web v2 详细进度；
- 旧 A-D 门禁、Streamlit 冻结和旧唯一下一步不自动约束 Web v2；
- v1 历史证据保持只读，只有实际复用时才通过显式适配器建立关系。

### 理由

Web v2 是新的产品化子项目，具有独立技术路线、页面结构、里程碑和交付目标。把新旧进度混在
一起会使其他对话错误地使用旧阶段判断新版任务，同时也会污染已经完成的旧项目状态。

### 迁移说明

最初为避免旧根规则干扰，新建了 `WEB_V2_AGENTS.md`。现在根目录 `AGENTS.md` 已直接改为新版
治理规则，因此继续保留两套完整规则反而会造成冲突。旧规则仍可从 Git 历史查阅，但不参与
Web v2 的开发判断。

## 2. 2026-08-12：产品与用户定位

### 决定

- 第一目标用户为普通车主；
- 当前用于大创答辩，但视觉和交互接近商业产品；
- 先做高质量商业化原型，再预留真实试点和生产架构；
- 不使用新品牌名，继续使用“智能停车优化与调度系统”。

### 理由

现有系统的工程和算法链路较完整，但页面更像科研展示。新版需要让普通用户先完成找停车场、
推荐、预留和导航，同时保留答辩所需的算法证据。

### 边界

synthetic 数据和演示部署不能包装成真实商业运营。

## 3. 2026-08-12：双模式而非单一复杂界面

### 决定

- 默认车主模式，顶部开关进入答辩模式；
- 车主模式使用三个一级页面；
- 答辩模式使用五个一级页面；
- 两种模式空闲时共享最近浏览停车场作为默认值；出现活动状态后各自固定停车场和布局版本，
  业务/实验状态隔离。

### 理由

普通车主只关心停车结果，评委需要算法、纵深移位、指标、数据和扩展路线。全部混在一个界面
会增加认知负担，完全拆成两个项目又会造成状态和算法不一致。

## 4. 2026-08-12：React + FastAPI 替代 Streamlit 作为新版主站

### 决定

- 新版主网站采用 React + TypeScript + Vite；
- Python 应用层采用 FastAPI；
- 现有 `parking_opt` 保持 v1 可行性、纵深恢复和历史证据的权威来源；Web v2 产品推荐以经过
  审计的 `OnlineRuleServiceV2` 为权威；
- 现有 Streamlit 暂时保留为科研审计、旧版演示和回归参考。

### 理由

已确认需求包含电脑/手机完整功能、双模式、地图/详情联动、倒计时、复杂会话状态、多车连续
动画和未来公网商业化。Streamlit 的脚本重运行和布局控制不适合作为这套长期主界面的上限。

### 回滚

新版验收前不删除 Streamlit；若新架构失败，可继续使用当前已验收版本。

## 5. 2026-08-12：先视觉审批，再正式开发

### 决定

- M1 先做两套电脑/手机视觉方向板；
- 用户选择方向后才做 HTML/CSS 可交互高保真原型和 PNG；
- 高保真原型批准后才进入 React、FastAPI 和 v2 Schema；
- 视觉方向为“城市智慧出行”和“未来停车舱”。

### 理由

“美观”是硬性验收项，且具有主观性。先冻结视觉方向和完整用户流程可以显著降低正式代码返工。

## 5.1 2026-08-12：选择 C 融合视觉方向

### 决定

- 用户在 M1 第一审批门选择 C 融合方案；
- 车主模式以“城市智慧出行”的明亮地图结构、信息清晰度和商业可信感为主体；
- 答辩模式吸收“未来停车舱”的深色科研驾驶舱、玻璃层次和动态语言；
- 两种模式共享品牌、圆角、间距、字体尺度和状态色，但维持明确的视觉与状态边界；
- M1 第二审批门使用零依赖 HTML/CSS/JavaScript 制作可交互原型，正式 React 实现仍在 M4。

### 理由

融合方案同时满足普通车主的日常可读性和大创答辩的视觉记忆点，避免整站深色带来的阅读负担，也避免纯明亮方案在算法演示中缺少层次。

### 验证与回滚

通过电脑/手机、车主/答辩四类截图和主要交互路径验证。若用户不批准第二审批门，可保留第一审批门两套方向板并重新调整原型，不影响 M2 及旧项目代码。

## 6. 2026-08-12：保留纵深车位为核心特色

### 决定

- 纵深位同时存在于车主和答辩模式；
- 车主模式固定 `strict_recoverable`；
- 推荐纵深位时，如存在满足相同硬条件的普通位则提供备选；无合规备选时如实说明，并要求
  纵深风险知情确认；
- `risk_accepting` 只用于答辩研究展示；
- 答辩模式建立独立纵深停车专题。

### 理由

纵深阻挡、专用缓冲位和被动移位是项目区别于普通“最近空位”产品的核心研究价值。商业交互
必须尊重车主知情选择，不能直接暴露复杂事务术语。

## 7. 2026-08-12：算法扩展采用注册表

### 决定

- 第一版只允许 `OnlineRuleServiceV2` 注册为可运行；车主界面统一称“智能推荐”，答辩界面可称
  “在线规则”。它在 M2 实现并验证前仍属于待实现能力；
- v2 服务复用只读 v1 候选可行性与纵深恢复能力，并显式增加充电过滤、动态路径排序和 v2
  结果复核；它不冒充原始 `OnlineRulePolicy` 或 v1 正式实验结果；
- v1 评估使用完整布局，并把当前物理状态和有效 v2 资源声明投影进 `observed_snapshot`；充电等
  v2 新硬条件随后过滤。不得先删除不满足充电的车位而改变 v1 容量和纵深恢复语义，也不得在
  v1 评估后才隐藏其他车辆的有效软锁或预留；
- 车主端隐藏算法；
- 答辩端显示模拟退火等分配算法为“待接入”；
- 随机森林归类为预测模块；
- 未实现方法置灰，不生成假结果；
- 后续算法使用统一版本化接口注册。

### 理由

模拟退火与随机森林作用不同，不能为了“算法数量”混为同类。统一接口可以扩展而不重做页面，
也能保持公平的信息条件和校验语义。v1 契约没有充电属性，现有在线规则的候选排序使用静态
路径距离，因此这些 v2 能力必须放在显式应用服务中，不能宣传为 v1 原生能力。

## 8. 2026-08-12：v1 永久冻结，新建 v2

### 决定

- v1 保留旧实验、哈希和验收证据；
- v2 支持多停车场、充电、软锁、会话预留、导航和动态车辆；
- v2 经适配器调用现有算法并由 v2 校验器复核；
- v1/v2 结果不直接比较，v2 无新公平实验时不声称优越。

### 理由

直接修改 v1 会破坏现有证据可追溯性。完全独立的 v2 可以支持产品能力，同时保留研究基线。

### 风险

需要维护两个契约版本、显式适配和跨版本测试；充电条件、停车场 ID 作用域和应用预留不能被
旧算法静默忽略。

## 9. 2026-08-12：四个停车场全部可交互

### 决定

提供商场、学校、医院和交通枢纽四个 synthetic 场景，全部支持完整推荐与导航。学校突出
纵深停车，交通枢纽包含充电位。名称不反复加“演示”，页面统一标记“模拟实时数据”。

### 理由

只有一个可操作场景会让多停车场首页成为假功能；四个差异化布局足以支撑商业观感和答辩演示，
又不会把首版数据制作无限扩大。

## 10. 2026-08-12：充电是硬条件，取消无障碍车位

### 决定

- 普通停车可附加“需要充电”；
- 充电只影响推荐，不模拟充电、计费或设备通信；
- 没有充电位时可等待或由用户取消需求；
- 车主场景由自身确定性事件调度器模拟充电位释放；答辩场景只能在独立副本演示，不跨模式
  修改车主状态；
- 第一版不做无障碍车位。

### 理由

充电能力可以用明确车位属性和过滤规则完整实现。无障碍车位涉及入口、电梯、坡道、尺寸和
资格等现实规范，只加标签会形成不完整和可能误导的功能。

## 11. 2026-08-12：两阶段会话预留

### 决定

- 服务端完成推荐并原子声明主车位后才返回 30 秒软锁；
- 用户确认后产品逻辑预留 5 分钟；
- 答辩演示可加速为 60 秒；
- 取消、拒绝或超时立即释放；
- 一名访客同时只有一个有效预留或行程。
- 纵深知情确认发生在软锁期间；模拟“车位被占”属于外部物理观测冲突，不是系统重复分配；
- 车主倒计时使用服务端墙钟，答辩倍速只作用于隔离仿真时钟；
- 关闭页面不释放占用，“结束并重置演示”才释放并记录 `DEMO_RESET`。

### 理由

软锁避免用户决策期间同一车位被当前会话重复推荐；确认后的预留形成完整商业流程。它仍是
synthetic 会话状态，不能与真实停车场锁位或移位事务预留混淆。

## 11.1 2026-08-12：匿名会话和双模式状态隔离

### 决定

- 每个匿名浏览器会话使用独立 synthetic 场景副本；
- 车主和答辩各自拥有独立可变状态；只在双方空闲时共享默认停车场 ID 和基础不可变布局版本；
- 活动期间切换模式不暂停车主业务墙钟，答辩切换停车场或修改布局不影响车主状态；
- 公网访客之间不共享软锁、预留、占用或实验修改；
- 真实数据源失败时只关闭该数据源，可显式切换到独立 synthetic 演示，不用模拟值填补真实值。

### 理由

没有账户并不意味着所有公网访客应修改同一个停车场状态。隔离场景可以防止答辩实验污染车主
行程、访客互相抢占演示资源，也能保证固定种子复现和隐私边界。

## 12. 2026-08-12：轻量管理层多车仿真

### 决定

- 自主实现多车管理层仿真；
- 支持连续移动、等待、动态成本、偏航、车位被占和纵深移位；
- 二维为可靠基线，伪 3D 尽量动态但受性能门约束；
- 同时提供预设场景和自由实验；
- 不直接复制或集成 ParkSim 代码。

### 理由

ParkSim 的自动驾驶车辆控制、轨迹规划、避碰、ROS/优化依赖和 GPL 许可明显超出当前项目
边界。借鉴展示思路、自主实现管理层仿真更符合大创范围和现有模型。

## 13. 2026-08-12：本地离线与公网部署并存

### 决定

- 本地一键启动、断网答辩是强制门；
- Windows 原生一键启动不依赖 Docker，Docker 只是附加交付方式；
- 断网强制覆盖答辩电脑本机；手机完整功能通过公网实机验证，首版不开放未加密 LAN HTTP；
- 同时实际部署免费公网版本；
- 车主模式公开，答辩模式后端口令保护；
- WebSocket 可用时启用，否则降级为 HTTP/轮询和浏览器动画；
- 未经用户批准不使用付费资源。
- 公网强制 HTTPS；本地 HTTP 只能绑定回环地址。

### 理由

公网方便分享和手机访问，本地离线避免答辩受网络和免费平台冷启动影响。离线发布物应带已
构建前端和后端运行环境，答辩电脑不依赖 Node、Docker 或联网安装；具体使用自包含可执行包
还是便携 Python 环境，在 M6 基于实际依赖体积和兼容性测试后冻结。

## 13.1 2026-08-12：首版使用同源单进程交付拓扑

### 决定

- 开发期 Vite 和 FastAPI 可分开运行；
- 交付期 FastAPI 同源托管 Vite 构建产物，本地运行不要求 Node.js；
- synthetic 会话使用可替换 `SessionStore`，首版为带 TTL 和原子锁的单进程内存实现；
- 公网首版只运行一个应用 worker；多实例和真实停车场锁位必须使用共享事务存储；
- 答辩口令成功后由后端签发短期 HttpOnly 会话，不在前端保存明文口令。

### 理由

同源单进程最适合断网一键演示和免费托管，也能避免前后端跨域、两个启动窗口和内存会话在多
worker 间失配。抽象存储接口保留未来升级空间，但不为演示版提前引入 Redis 等外部服务。

## 14. 2026-08-12：首版范围控制

### 决定

第一版不做账号、支付、运营后台、真实地图、无障碍车位、复杂充电、真实设备控制、自动驾驶
控制、PDF 和生产级权限系统。M1 高保真原型只冻结页面、流程和功能边界；M2 冻结 v2 契约，
M3 冻结状态机和仿真语义，M6 验收后才形成 `web-v2.0.0-rc1` 候选。

### 理由

这些功能会把项目扩展成完整停车运营平台，削弱推荐、纵深移位、导航和仿真等核心成果的质量。

## 15. 2026-08-12：Git 和实施审批

### 决定

- 单仓库管理；
- 总分支加里程碑短期分支；
- 提交使用英文 Conventional Commits 前缀和中文说明；
- 每个里程碑验收后打 annotated tag；
- 最终标签 `web-v2.0.0-rc1`；
- 当前只记录需求，未授权创建分支或实施。

### 理由

分阶段恢复点方便答辩展示过程、独立审查前端/API/Schema/算法变化，也避免未完成新版污染当前
稳定 `main`。

## 15.1 2026-08-12：按依赖重排 M2–M5

### 决定

- M2：v2 契约、只读适配器、`OnlineRuleServiceV2` 与 FastAPI 基础；
- M3：共享会话状态机、路由和确定性二维多车仿真核心；
- M4：基于 M2/M3 的车主模式 React 前端；
- M5：基于同一核心的答辩模式、自由实验台和条件增强；
- M6：离线、公网和全端验收后产生 `web-v2.0.0-rc1` 候选。

### 理由

车主端需要软锁、路线和异常重规划，答辩端需要多车与纵深移位；若把这些共享核心放在页面
之后实现，M3/M4 就无法完整验收。新顺序让每个里程碑只依赖已完成的前置能力。

## 16. 2026-08-13：M2 验收与 M3 启动

### 决定

- 用户验收修复后的 M2 契约、排序口径和 FastAPI 边界；
- M2 标记为 `approved`，创建 `web-v2-m2-approved` 标签；
- 用户明确授权进入 M3，但不自动授权 M4 React 前端。

### 理由

M2 专项、静态检查、v1 只读哈希和隔离全仓回归均已通过；历史 D2/D3 换行哈希问题保持独立，
不改变 M2 的 Web v2 验收结论。

## 17. 2026-08-13：M3 时间与性能参数

### 决定

- 车主 synthetic 会话闲置 TTL 为 30 分钟，答辩会话为 2 小时；
- 软锁固定 30 秒，车主确认后预留固定 5 分钟，答辩独立场景可映射为 60 秒；
- ETA 安全余量固定 60 秒，主推荐须满足 `ETA + 60s <= 300s`；
- 状态机命令 p95 ≤ 100 ms，推荐并原子软锁 p95 ≤ 500 ms，重规划 p95 ≤ 100 ms；
- 100 辆车、10,000 事件重放 ≤ 2 秒，增量峰值内存 ≤ 256 MB；
- 固定种子事件序列和最终状态哈希必须一致。

### 理由

该设置兼顾答辩演示稳定性、会话资源回收和五分钟预留可达性，并明确限定为单进程 synthetic
原型预算，避免误写成生产性能承诺。

## 18. 当前开放决策

以下项目留到对应里程碑决定：

- 免费部署平台；
- WebSocket 降级阈值；
- M5 答辩口令环境变量名与具体秘密；
- M5/M6 的伪 3D 是否通过性能门及最终 `rc1` 冻结清单；
- 真实 Safari/iPhone 验证设备；只有 WebKit 自动化时不得声称 Safari 已实机通过。

## 19. 当前审批状态

```text
需求访谈：完成
需求记录：完成
M1 第一审批门：已通过，选择 C 融合方向
M1 第二审批门：用户已验收
M1：approved
M2：approved
M3：approved
M4 React：approved（完整布局修订 R0a–R5 已完成并验收）
一致性消歧方案：用户已整体接受
```

以上为本节历史审批快照。当前 M4 已重新打开并进入 R6.1 及受限指引/名称修复，具体授权和
PERF-02 阻断以 `WEB_V2_STATUS.md` 为准；M5 未授权。

## 20. 2026-08-13：M4 P1 使用独立 DiscoveryArea 资源

### 原定义的问题和证据

`ParkingLot 2.0.0` 在 M2 已获批准，但 P1 需要开放时间展示、区域坐标、版本化参考点及场外
距离/ETA。直接把这些字段追加为 `ParkingLot` 必填项会在不改变版本号的情况下破坏旧消费者，
也会把页面坐标混入已冻结的停车业务对象。

### 决定与新旧差异

- `ParkingLot 2.0.0` 保持字节级兼容，不增加 P1 展示字段；
- 新增只读 `DiscoveryArea 1.0.0` 与 `GET /api/v2/discovery-area`；
- Discovery 资源使用来源中性的百分比坐标、固定版本号、参考点、开放时间展示文案及每个参考点
  对应的场外距离/ETA；synthetic/real 真实性和健康状态显式携带；
- 点击区域图只吸附到服务端提供的固定参考点，前端不计算距离或路线；
- unavailable 与未配置 real adapter 均失败关闭为 503，degraded 在页面显式显示。
- P1 仅将当前来源标为“固定 synthetic 场景”和“当前接口快照”，暂不沿用第 9 节的
  “模拟实时数据”措辞；因为可用数尚未投影会话内的软锁、预留、占用和异常位。P2 完成
  session-aware 权威快照并验证后，再决定是否恢复“模拟实时”表述。

### 影响、验证和历史实验

影响文件限于新的 Discovery 模型、数据源、fixture、Schema/OpenAPI、只读端点、生成类型与 P1
页面/测试。与 `web-v2-m3-approved` 比较，旧 `parking-lot.schema.json`、
`scenario-bundle.schema.json` 和四个 M3 场景文件均零差异；v1 保护哈希通过，因此无需重跑历史
实验。Web v2 后端全套 89 项、前端 22 项及双视口 E2E 已覆盖生成漂移、边界、503、降级、
取消、超时、加载、离线、搜索、URL、参考点和响应式布局。

### 回滚

删除 `/api/v2/discovery-area`、Discovery Schema/fixture/source 及 P1 页面消费即可回到 P0；旧
ParkingLot、算法、会话、路线和仿真契约无需迁移或回滚。

## 21. 2026-08-13：P2 使用可选会话头投影权威空位

### 原定义的问题和证据

P1 的停车场列表只返回场景初始 `available_spaces`。M3 的软锁、预留、导航中声明、占用和
外部占位保存在会话场景副本内；如果发现页没有携带会话上下文，服务端无法判断应投影哪个
driver 副本。前端自行减数会在刷新、多标签页、到期、取消和异常换位时与推荐权威状态分叉。

### 决定与新旧差异

- `GET /api/v2/parking-lots` 和 `GET /api/v2/parking-lots/{parking_lot_id}` 新增可选
  `X-Session-ID` 请求头；P2 前端必传，未传时保留 M2/P1 初始快照以兼容旧消费者；
- 请求头只标识本地 synthetic driver 会话副本，不是登录凭证或权限证明；namespace 固定为
  `driver`，scenario 由停车场 bundle 推导，禁止客户端自行指定；
- 有效空位按车位 ID 集合计算：基础 `status=available` 集合减去同一
  `(session, driver, scenario, lot)` 的有效声明与异常位并集，禁止按数量连续相减；
- 快照在单次会话锁内先处理期限与闲置回收，再同时读取声明、异常位和观察时间；读取不续期；
- 软锁、会话预留、导航中和占用状态均持续扣除同一车位；等待不扣；取消、到期、失败和正常
  离场释放声明；外部占位与替换声明按两个不同 ID 扣除且不能重复扣减；
- 会话化响应设置 `Cache-Control: no-store` 与 `Vary: X-Session-ID`；`ParkingLot 2.0.0`、
  ParkingLot Schema、ScenarioBundle 和四个已批准 fixture 均不改变。`ParkingLot.updated_at`
  表示投影观察时刻，嵌套 `data_source.updated_at` 继续表示来源快照时间。

### 影响、验证和历史实验

影响会话存储的原子读取边界、停车场 GET 的请求参数/OpenAPI、前端匿名会话 ID 与请求头，及
对应契约/生命周期测试。必须覆盖四种声明状态、切换、取消、到期、离场、外部占位、基础已占
用位、跨 session/namespace/scenario/lot 隔离、列表/单体一致、非法请求头、无头兼容与真实源
失败关闭。旧响应模型和固定 fixture 不变，因此无需重跑历史实验。

### 回滚

移除可选请求头、原子 scope 快照、投影器及前端会话头即可恢复 P1 初始快照；无须迁移或回滚
`ParkingLot 2.0.0`、会话状态、四个场景和 v1 资产。

## 22. 2026-08-13：P2 推荐恢复与纵深拒绝采用兼容资源

### 原定义的问题和证据

既有推荐 POST 要求 `scenario_id`，但 P1 公共资源不暴露该内部作用域；既有 Journey GET 又缺少
推荐、原需求和服务端观察时间，无法满足刷新、断线和多标签恢复。纵深拒绝若仅取消旧 attempt，
普通新请求还可能再次返回用户已拒绝的协同位。

### 决定与新旧差异

- 新增独立 `DriverRecommendationContext 1.0.0` 和 `DriverJourneySnapshot 1.0.0`，不修改冻结的
  ParkingLot/Layout/Journey/Recommendation 2.0.0；
- 推荐页先按 `X-Session-ID` 恢复权威行程；无活动行程才使用服务端派生的 scenario、入口和车位
  展示上下文创建新 attempt；mutation 在提供会话头时校验 driver namespace 和 session；
- 纵深拒绝原子终止旧 attempt、累积排除用户拒绝过的协同位并创建新 attempt；排除只属于需求
  上下文，不伪装为物理异常位；
- 服务端只返回至多一个合规备选。纵深主位存在同硬条件普通独立位时优先提供该普通位；
- 前端倒计时用 snapshot `observed_at` 加本地单调时间插值，不以浏览器墙钟判断权威期限；刷新、
  online 和重新可见只读取，不续期。

### 影响、验证和回滚

影响 P2 兼容 Schema/OpenAPI、会话服务私有上下文、推荐端点和 React 推荐页。历史 v1 实验、四个
scenario fixture 及冻结 2.0.0 响应模型不变，无需重跑历史实验。回滚时删除新增资源/端点和 P2
页面，恢复 P1 入口即可。当前后端 107 项、前端 30 项及静态/构建门通过；系统 Microsoft Edge
完成桌面/Pixel 7 六项 Playwright 验收，覆盖服务端软锁纵深推荐和无横向溢出，P2 已验收。

## 23. 2026-08-13：P3 使用独立导航快照与显式车主命令

### 原定义的问题和证据

P2 的 `DriverJourneySnapshot 1.0.0` 恢复原始 Recommendation，但动态重规划后的路线只保存在
重规划服务内。刷新或第二标签页会重新显示原始路线。既有导航、重规划、外部占位、停入和离场
端点也未全部校验 driver 会话；Journey 虽声明 `reset_demo`，却没有对应命令。“无法停入”若借用
外部占位会把用户操作错误写成物理观测。

### 决定与新旧差异

- 保持 `Journey`、`Route` 和 `DriverJourneySnapshot` 现有版本不变，新增独立
  `DriverTripSnapshot 1.0.0`，聚合当前 Journey、原需求、当前权威路线、当前位置和最近重规划；
- 重规划先在同一会话锁内处理期限并确认仍为 `navigating`，过期后失败关闭，不计算或缓存新路线；
- 所有车主生命周期命令在提供 `X-Session-ID` 时统一校验 driver namespace 与 session；无头请求
  继续兼容既有 defense/测试消费者；
- “无法停入”原子终止旧 attempt、释放声明并创建新 attempt；仅在该需求上下文排除原位，不写入
  物理 unavailable；
- ETA 超窗由用户显式选择继续当前路线或重新推荐；重新推荐只在当前需求链排除原位，避免立即
  循环返回同一目标，不把该车位标为物理异常；
- `reset-demo` 仅允许 synthetic driver 的 `occupied` 行程，记录 `DEMO_RESET`，释放声明并清理该
  session/scenario/lot 的 synthetic 异常位，并映射为 `DEPARTED` + `terminal_reason=DEMO_RESET`；
  普通 `depart` 映射为 `DEPARTED` + `terminal_reason=NORMAL_DEPARTURE`；
- 导航画布、文字指引和动画后续只消费同一个 Trip Snapshot/Route，不由前端重新寻路或推进状态。

### 影响、验证和回滚

影响新的兼容 Schema/OpenAPI、重规划服务恢复状态、会话命令、FastAPI 端点及 P3 测试。必须覆盖
刷新/多标签最新路线、过期重规划不缓存、会话错配、无法停入不产生物理异常、重推/WAITING、
DEMO_RESET 审计与作用域清理、幂等和旧无头兼容。回滚时删除新资源/端点和导航恢复状态即可，
无需迁移或修改冻结的 2.0.0 模型、场景 fixture、v1 资产和历史实验。

## 24. 2026-08-13：P3.1 路线动画只做同源 UI 插值

### 决定

- 当前行程画布、距离、ETA、文字步骤和车辆位置均消费 `DriverTripSnapshot.current_route`；
- 动画按每条 `RouteInstruction.travel_time_s` 的累计区间插值，不按像素距离或步骤数量平均推进；
- 重规划后以匹配当前 `cost_version` 的 `CostSnapshot.observed_at` 重置动画锚点；
- 动画到达终点只表示“到车位附近”，不能自动提交 `OCCUPIED`；
- 周边车辆仅投影 Layout 中明确标记的静态占用，并标明不代表真实车辆感知；
- 当前契约没有权威 ChannelLoad 读取面，因此 P3.1 不实现“成本更新”按钮，禁止前端构造领域负载。

### 影响、验证和回滚

本变更只影响 React 当前行程页面、API 运行时守卫、CSS 和测试，不改变公共 Schema、后端算法、
场景 fixture 或历史实验。前端 39 项、严格类型、ESLint、生产构建与桌面/Pixel 7 八项 E2E 已通过。
回滚时删除当前行程页面与其纯 UI 时间轴即可，P3.0 的权威快照和命令契约无需回滚。

## 25. 2026-08-13：P3.2 演示重规划输入由服务端确定性派生

### 原定义的问题和证据

既有低层 `/replan` 要求调用方提交当前位置和完整 `ChannelLoadSnapshot`，但车主 React 没有权威
通道负载读取面。若浏览器自行填零、随机值或固定值，会把领域真值和演示规则复制到 UI，并把
synthetic 演示伪装成实时感知；相同幂等键重试时，服务端观察时间变化也会破坏重放一致性。

### 决定与新旧差异

- 保留既有低层 `/replan` 和全部冻结响应模型，新增兼容的
  `DriverDemoReplanRequest` 与 `/driver-demo-replan` 命令；浏览器只提交 action、版本与幂等键；
- `simulate_deviation` 使用服务端 clear-channel preset，从当前路线外、可达且非目标的节点中按
  坐标距离平方和 node ID 稳定选择；`simulate_cost_update` 使用当前剩余路线首个有序通道 zone，
  将其负载设为容量，其余 zone 为零；负载覆盖布局全部 zone，观察时间来自服务端；
- 命令仅允许 synthetic driver 会话，应用模式、namespace、停车场真实性和数据源模式任一不一致
  均在 mutation 前返回 409；`reset-demo` 使用同一真实性防线；
- 演示重放键绑定 journey、expected version、action、parking lot 和 layout version；同一 canonical
  输入返回原结果，不同输入冲突，期限归零和 stale 请求均不计算或缓存新路线；
- `NAVIGATING.legal_operations` 兼容增加演示重规划、外部占位和重新推荐能力。失败重规划仍保留
  previous route 作为最后已知路线，但前端必须停止动画并明确显示当前无可达路线。

### 影响、验证和回滚

影响限于新增请求 Schema/OpenAPI/生成类型、重规划应用服务、命令端点、legal operations 和
synthetic reset 守卫；Journey、Route、ParkingLot、四场景 fixture 与 v1 均不改变，无需重跑历史
实验。定向 API/重规划 40 项、Web v2 全量 126 项、Ruff、严格 Mypy、生成类型漂移、TypeScript
与 ESLint 已通过，独立只读审查给出 GO。回滚可删除新增
请求、端点、派生 helper 与 legal operation；既有低层重规划和 P3.1 路线展示无需迁移。

## 26. 2026-08-13：P4 使用 production preview 与真实 FastAPI 完成验收

### 决定

- mock Playwright 继续作为快速页面状态门；新增独立真实联调配置，不拦截 `/api/v2/**`；
- 每次真实验收先构建当前 production 资源，再以 FastAPI synthetic 单进程和 Vite preview 联调；
- 四停车场均在 Edge 桌面和 Pixel 7 视口完成推荐、预留、偏航异常、显式停入与离场，Chrome 桌面
  补真实发现页 smoke；纵深证据必须由服务端 replacement 实际抵达协同位；
- 性能阈值在首次测量前冻结，保存全部样本，不以单次最佳结果或后端 API 延迟替代前端体验指标；
- M4 完成后状态为 `awaiting_review`、实施授权关闭；用户批准前不得进入 M5。

### 证据、限制与回滚

后端 126 项、前端 54 项、严格类型、Ruff、Mypy、ESLint、OpenAPI 漂移、生产构建和 mock 双视口
8 项通过；真实联调 14 passed、1 skipped（只在桌面项目运行一次性能套件）。生产 JS+CSS gzip
96,951 B，最终首屏 p95 230.72 ms，推荐 mutation p95 72.85 ms，5 秒动画帧间隔 p95 6.70 ms且
无大于 100 ms 长帧。证据仅限本机 loopback、单进程 synthetic 和系统 Edge/Chrome，不扩张为真实
停车场、生产并发或 Safari/iPhone 承诺。回滚时删除真实联调配置、启动脚本与 P4 证据即可；M2/M3
领域模型、四场景 fixture、v1 与历史实验无需迁移。

## 27. 2026-08-20：重新打开 M4，先建设完整布局基础层

### 问题与阶段决定

M4 首轮当前行程只显示少量路网节点和路线骨架，无法让车主理解全部车位、占用、纵深组和缓冲位，
未通过用户布局验收。用户决定先重新打开 M4，完成共享布局基础层并再次验收；布局/状态/需求导入、
答辩编辑和算法对比留在 M5。当前对话只更新治理、需求和计划，代码在新对话开始。

### M4 完整布局

- 保留现有四个公开停车场 ID；新建商场 48、学校 28、医院 32、交通枢纽 52 位的版本化 synthetic
  大布局作为网站默认，旧小布局标为 legacy 回归场景；
- 充电位为 8/4/6/10；学校 4 组纵深位，其他停车场各 1 组；首批纵深与充电不重叠；学校 2 个、
  其他各 1 个专用缓冲位，缓冲位不计容量且不可推荐；
- 商场/交通枢纽以单向环流为主，学校/医院为双向主通道加局部单向停车排；入口/出口按场景配置；
- 首批单层，但契约支持多层和显式跨层连接；米制坐标是算法真值，像素坐标只用于叠图校验；
- 默认状态完整、固定和版本化，占用率约 65%/50%/70%/60%；允许少量明确不可用位，不伪造未知位；
- 新增共享二维画布。第一版使用 SVG，但数据/交互与渲染层隔离，以便未来替换 Canvas；
- 车主可进入 `/parking/:parkingLotId/layout` 只读预览；当前行程显示完整布局并叠加权威 Route。电脑/手机均
  支持缩放、拖动、点击、聚焦，手机另有全屏；路线流动动画可降级为静态高亮；
- 只读路线预览不推荐、不锁位；状态失效立即撤销。页面可见时约 3 秒单飞轮询，后台暂停，并预留
  推送适配边界；
- 保留 `Layout 2.0.0` 和历史场景，新增独立版本化的不可变完整设施布局资源及动态状态快照，
  不在前端写死几何或 ID 映射。几何资源承载版本和来源追踪；状态快照独立承载场景版本、观察时间、
  来源健康和车位状态。

### M5 预留边界

- 答辩模式从首页入口进入，但由后端环境口令和短期会话保护；车主内部继续隐藏算法信息；
- 答辩端复用画布，但使用独立路由/命名空间，增加布局 JSON、状态 CSV/JSON、需求 CSV/JSON 导入；
- 布局采用草稿、自动校验、原图叠图人工确认、发布流程；发布布局保存到环境变量指定的受管目录，
  状态编辑只写会话副本并可导出；缺失状态为 `unknown` 且所有算法排除；
- 状态编辑同时支持画布单个和表格批量；若目标位失效，服务端原子终止旧 attempt 并重推或等待；
- 车主只运行在线规则。答辩端可在验证通过后运行在线规则、最近可行和随机可行实验基线；模拟退火
  等未实现算法继续 `pending`，随机森林归预测模块；
- 算法比较分单次与批量；统一输入/预算/可见信息，随机单次显式种子、报告冻结 30 个种子；
- 默认硬约束门禁和 Pareto，不提供官方万能总分。自定义权重只作用于 ETA 与预计移位总耗时，
  固定尺度归一化并做敏感性分析；算法耗时作为门槛/平局项；
- 移位耗时复用并核验 M3 参数，按固定操作时间加缓冲路线时间；次数/距离只展示不重复计分；
- 导出完整 JSON、HTML 和浏览器打印 PDF；指标公式、单位、参数来源、边界和例子写入独立文档。

### 影响、迁移与回滚

本决定改变产品需求、M4/M5 边界和未来 v2 公共资源，但不授权本对话修改 Schema、fixture、前后端
代码或依赖。M4 R0a 必须提交契约变更提案，证明旧 `Layout 2.0.0`、legacy 场景、v1 和历史实验
不变，并由用户确认最终公共名称、端点、字段、版本及默认/legacy 选择方式；之后 R0b 才可实现新
资源。任一恢复点可回滚到提交 `07226cd`，且不得删除用户未跟踪资产。

## 28. 2026-08-20：批准 M4 R0a 公共契约并授权 R0b

### 决定

- 新增 `ParkingFacilityLayout 1.0.0`，通过
  `GET /api/v2/parking-lots/{parking_lot_id}/facility-layout` 提供不可变完整设施几何；
- 新增 `ParkingFacilityStateSnapshot 1.0.0`，通过
  `GET /api/v2/parking-lots/{parking_lot_id}/facility-state` 提供 session-aware 动态状态；
- 新增 `RoutePreview 1.0.0`，通过
  `POST /api/v2/parking-lots/{parking_lot_id}/route-previews` 返回无推荐、锁位或行程副作用的
  `Route 2.0.0` 包装结果；
- `ParkingFacilityLayout` 是完整几何唯一真值；旧算法需要的 `Layout 2.0.0` 必须由几何和状态
  确定性投影，不能维护第二套手写路网；
- 完整布局最终成为唯一车主公共默认。legacy 小场景保留原 ID、fixture、Schema 和哈希，只允许
  测试或应用构造参数显式选择，不提供车主 URL、query 或 header 切换；
- 来源使用新枚举显式区分 `synthetic`、`imported` 和 `real`，不扩写现有只含
  `synthetic | real` 的 `DataMode 2.0.0`；
- R0b 只实现契约、端点/数据源选择边界、生成类型和测试。四套大布局在 R1 生成，SVG 画布在 R2。

### 兼容、错误与回滚

现有 `Layout 2.0.0`、`/layout` 响应模型、四个 legacy fixture 和 v1 保护资产保持不变。新资源通过
`parking_lot_id + layout_version` 与 Route 同源，状态再由 `scenario_version + state_version +
observed_at` 标识。不存在返回 404，非法契约返回 422，版本/状态冲突返回 409，缺失或不健康真实源
返回 503 并失败关闭。R0b 可整体回滚其新增模型、端点、生成物和测试，不迁移旧数据。

### R0b 实施证据

R0b 已实现独立 Pydantic/JSON Schema、FastAPI 端点、OpenAPI、TypeScript 生成类型和显式
`PUBLIC | LEGACY` 应用构造边界。R1 数据尚未发布时，PUBLIC 停车场、发现区和设施资源均返回
503，不回退 legacy。RoutePreview 会复核请求、停车场、布局、状态观察时间、入口、目标、节点、
边、方向和指令序列；陈旧状态或目标失效返回 409，服务端损坏数据返回 503。三个端点统一使用
`ErrorResponse` 表达 422。

Python 3.11.15 下新增契约 20 项、其余 Web v2 回归 126 项全部通过；Ruff、严格 Mypy 定向、
TypeScript、OpenAPI/生成类型漂移、17 项 v1 哈希、`Layout 2.0.0`/`ParkingSpace`/`Route`/旧
`/layout` OpenAPI 对象和四个 legacy fixture 均保持一致。两名独立只读审查未发现 P1/P2 阻断。
唯一已知警告是 Starlette TestClient 对当前 httpx 的第三方弃用提示，不改变运行结果。

## 29. 2026-08-20：批准 R0b 恢复点并授权 R1

用户批准提交 `6ab3311` 的 R0b additive 契约恢复点，授权生成四套完整 synthetic 大布局、默认
状态、PUBLIC catalog 和确定性 `Layout 2.0.0` 投影。R1 必须保持公开停车场 ID、旧 Schema、四个
legacy fixture 与 v1 哈希不变；PUBLIC 成为网站默认，legacy 只允许应用构造参数或测试显式选择。
R2 共享 SVG 画布和 M5 仍未授权。

## 30. 2026-08-20：完成 M4 R1 四套完整设施恢复点

R1 使用独立确定性生成器和 `data/synthetic/web-v2-public/` 发布商场、学校、医院、交通枢纽四套
完整 synthetic 设施。保留公开停车场 ID，新增独立 scenario/layout/state/cost 版本；PUBLIC 成为
应用默认，legacy fixture、旧 Schema 和 v1 保护资产不变。权威 `ParkingFacilityLayout` 确定性
投影 `Layout 2.0.0`，状态与路线使用同一停车场和布局版本。

布局采用每列邻近接入节点、两条真实单向停车巷及场地主环路；商场/枢纽主环单向，学校/医院主环
双向。四套资源分别满足 48/28/32/52 总位、8/4/6/10 充电位、2/8/2/2 纵深位和 1/2/1/1 专用
缓冲位，充电与纵深不重叠。测试冻结矩形不重叠、道路不穿位、接入距离、全入口到目标、目标到
出口、逆行反例、纵深成功和缓冲不足失败。

session-aware 设施状态在同一存储原子区间读取 availability、active claim 和对应 Journey，按
`ResourceClaim.journey_id` 精确关联；状态版本绑定 Journey 状态和更新时间，`occupied` 投影为
真实 observed/effective occupied，并覆盖同一车位取消后复用。Python 3.11.15 下 R1 定向 35 项、
Web v2 全量 161 项、Ruff、严格 Mypy、TypeScript、ESLint 和 API 类型漂移均通过；两名独立只读
终审给出 GO。R1 授权关闭，R2 共享 SVG 画布必须由用户另行授权，M5 继续未授权。

## 31. 2026-08-20：验收 R1 并授权 R2

用户验收 R1 恢复点 `99a20d5`，授权实施共享原生 SVG 布局画布、车主只读布局页、状态轮询、
只读路线预览和桌面/Pixel 7 验证。R2 不新增地图或画布依赖，不迁移当前行程页面；R3 当前行程
完整画布与 M5 答辩功能仍需后续单独授权。

## 32. 2026-08-20：完成 M4 R2 共享完整布局画布恢复点

R2 采用零新增依赖的原生 SVG 共享画布，新增 `/parking/:parkingLotId/layout` 车主只读页。画布按
楼层渲染分区、道路方向、受限区、车位状态、静态占用车辆、充电位、纵深组、专用缓冲位、入口、
出口和同版本路线；跨层入口保持全局选择，路线按当前查看层分段显示。缩放/平移支持鼠标、触控、
键盘、重置、聚焦和 reduced motion，手机与桌面功能一致。

前端运行时守卫完整复核 provenance、楼层/区域/道路/跨层/车位/纵深/缓冲引用、来源状态及路线
入口、目标、有向连续性和 instructions；布局、状态、URL 或请求范围变化时旧路线不会提交。状态
约每 3 秒仅在可见且在线时单飞读取，切换停车场会中止旧请求；路线预览不创建 recommendation、
claim 或 journey。前端 65 项、mock 双视口 10 项、真实 FastAPI + production preview 22 passed、
1 skipped，后端 161 项通过；八张视觉证据和两轮独立只读复核关闭全部 P1。R2 实施授权关闭，
等待用户验收；R3 当前行程迁移与 M5 均未授权。

## 33. 2026-08-20：验收 R2 并授权 R3

用户验收提交 `f82cf34` 的共享完整布局画布，授权 R3 用同一画布替换当前行程的抽象 `trip-map`。
R3 必须继续消费既有 `DriverTripSnapshot`、`Route 2.0.0` 和服务端 legal operations；车辆位置仅按
`RouteInstruction.travel_time_s` 做 UI 插值，不能按像素距离重新计算、不能自动停车。状态、异常、
断线、重规划、显式停入/离场/reset 语义保持不变。R4 全端验收和 M5 答辩功能仍需后续单独授权。

## 34. 2026-08-20：R3 采用夹读一致的当前行程完整设施视图

R3 不修改公共 Schema，也不调用只读路线预览替代行程路线。当前行程以
`DriverTripSnapshot.current_route` 作为画布、文字步骤、距离、ETA 和车辆进度的唯一 Route；设施
布局与 session-aware 状态只提供静态几何、占用和 claim 投影。为避免两个独立 HTTP 读取形成新旧
混搭，客户端执行 `Trip T1 -> FacilityLayout/FacilityState/ParkingLot -> Trip T2` 前后夹读，比较
Journey、Driver、完整 Route、重规划和生命周期身份；冲突重试一次，持续变化失败关闭并保留上次
完整一致视图。

组合守卫验证停车场、布局版本、场景、目标车位、claim/occupied 投影、Route 节点、边、有向连续性
和终点接入。路线与车辆沿权威 edge centerline 绘制，边内几何长度只用于空间投影，不参与时间
分配；`RouteInstruction.travel_time_s` 仍决定跨边和边内进度。点击其他车位只改变本地只读检查项，
不改变 Journey 目标、Route、URL 或发送 mutation。hidden 和 reduced-motion 停止连续路线/车辆
运动，静态路线、目标和指引保留；failed replan 与终态继续隐藏旧路线。

夹读的所有 GET 共享同一取消信号，卸载后不得提交状态；React StrictMode 重放必须新建恢复代次，
旧 Promise 不得清除新代次引用。前端 78 项、mock 桌面/手机 10 项、真实 FastAPI + production preview 22 passed/1 skipped、Web v2
后端 161 项、Ruff、严格 Mypy、TypeScript、ESLint、OpenAPI 类型漂移和生产构建通过。全仓 pytest
因历史 Streamlit 可选依赖 `blinker` 缺失出现 6 个收集错误，不属于 Web v2 授权门禁。R3 多轮
独立终审发现并关闭普通布局目标语义、跨层 Route、取消链路和 StrictMode 回放问题，最终复核
给出 GO。R3 实施授权关闭，等待用户验收；R4 与 M5 均未授权。

## 35. 2026-08-21：治理入口必须可从当前状态直接恢复

为避免新对话被需求、蓝图或 ExecPlan 中的历史“下一步”误导，当前阶段、审批门、授权和唯一
下一步只以 `WEB_V2_STATUS.md` 的结构化字段为准；其他权威文档的当前状态叙述必须与其同步，
带日期的历史决策仍保留为证据但不得覆盖当前状态。新对话在实施前必须核验仓库根、分支、HEAD、
上游、工作区、当前计划和用户未跟踪资产。

`implementation_authorized: false` 时，只允许只读审计、用户明确要求的治理文档修正和验收，不得
修改产品代码、Schema、fixture 或依赖。Git 必须按文件白名单暂存；提交不等于推送，提交、推送、
合并和 tag 分别服从用户授权。本地 Web v2 的标准验收入口为 `npm --prefix apps/web run demo`，
但运行中的旧服务不能替代当前构建、真实 FastAPI 健康检查和双视口证据。

## 36. 2026-08-21：验收 R3 并授权 R4 全端验收

用户验收 M4 R3 恢复点 `2420c3a`，明确授权进入 R4。R4 范围冻结为四套 PUBLIC 布局在真实
FastAPI + production preview 下的 Edge 桌面/Pixel 7 完整车主流程、Chrome 桌面 smoke、视觉证据、
既定性能门、必要缺陷修复、运行与交付文档、唯一 M4 handoff 和独立终审。

R4 不得实现答辩页面、口令、导入编辑、实验基线、算法对比或其他 M5 功能；原则上不新增或替换
关键依赖，不修改公共 Schema、算法语义或数据契约。若必须改变公共接口、技术栈、数据语义、交付
方式或长期维护边界，须停止扩大范围并重新取得用户授权。R4 通过全部门并封存后，M4 仅进入
`awaiting_review`，实施授权关闭，唯一下一步为用户验收 M4；不得创建 M5 分支、合并 main 或打 tag。

## 37. 2026-08-21：完成 R4 并等待用户验收 M4

R4 沿用测量前冻结门，完成四套 PUBLIC 布局的真实 FastAPI + production preview Edge 桌面/
Pixel 7 完整车主流程、四布局只读预览、纵深 replacement、Pixel 7 Fullscreen API 和 Chrome 桌面
smoke。最终真实联调 23 项中 22 passed、1 个按设计 skip；JS+CSS gzip 108,580 B，暖首屏 p95
152.60 ms，推荐 mutation p95 394.49 ms，5 秒动画帧间隔 p95 7.40 ms，长帧 0。后端 161 项、
前端 78 项、mock 双视口 10 项及 Ruff、Mypy、TypeScript、ESLint、API 漂移、构建和编排探针通过。

首轮后端性能门在与前端构建并发时以 3.73 秒失败，隔离复测和最终无并发全量均在既定 2 秒门内
通过；没有放宽阈值。首轮真实联调唯一失败是 headless Edge 进入全屏后不响应 `Escape` 清理，改用
标准 `document.exitFullscreen()` 后完整重跑通过，未改产品全屏行为。29 张视觉证据已人工复核。

R4 未修改公共 Schema、算法语义、数据契约或关键依赖，也未实现 M5。M4 现为 `awaiting_review`，
实施授权关闭，唯一下一步为用户验收 M4；不得自动创建 M5 分支、合并 main 或打 tag。

## 38. 2026-08-21：授权 M4 R5 确定性车主演示情景轮换

### 问题与决定

R4 的四套 PUBLIC 设施使用固定、可复现的单一基态；基础占用集合又按稳定构造顺序选取。车主
推荐采用确定性硬约束和 ETA/距离排序，因此同一停车场在演示重置后经常再次命中相近车位。用户
确认这会削弱车主模式展示效果，并授权在 M4 内增加 R5，而不是提前进入 M5。

R5 为每个 PUBLIC 停车场增加会话级确定性 profile 集合。profile 只定义当前可观察状态、明确
不可用项和动态成本，不携带推荐答案；`OnlineRuleServiceV2`、v1 适配器、硬约束、排序和随机算法
注册均不改变。活动 Journey、replacement 和 replan 固定同一 profile；只有空闲态手动切换，或
正常离场/`DEMO_RESET` 成功后，才为下一轮推进一次。所有推进必须幂等、会话隔离且真实数据失败
关闭。

### 公共契约差异

- 新增独立 `DriverDemoProfile 1.0.0` 只读摘要；
- 在 `DriverRecommendationContext 1.0.0` 与 `ParkingFacilityStateSnapshot 1.0.0` 增加可选
  `demo_profile`，不改变旧必填字段；
- 新增 `DriverDemoProfileAdvanceRequest/Response 1.0.0` 和 synthetic driver 空闲态推进端点；
- 非 synthetic、会话不匹配、期望 profile/state 过期或存在活动行程时失败关闭；旧客户端可忽略
  新字段，现有 Layout/Journey/Route/Recommendation Schema 和 URL 不变。

### 验证与回滚

验证必须覆盖 profile 引用、固定顺序和状态哈希、不同会话/停车场隔离、活动行程 409、手动及终态
推进幂等、推荐/设施状态/摘要同源、至少五类演示状况、无未来信息泄漏、四布局双视口真实联调和
既有性能门。回滚通过关闭轮换并固定默认 profile；不得删除旧 Schema 或把 synthetic profile 用于
真实源。R5 完成后仍只把 M4 设为 `awaiting_review`，M5 未授权。

## 39. 2026-08-21：完成 M4 R5 并等待用户验收

R5 实现四个固定 profile：平峰通行、高峰远端、充电紧张和纵深协同。profile 从不可变设施几何
派生状态，既不携带推荐答案，也不修改 `OnlineRuleServiceV2`；四 lot 的普通请求在连续 profile
中至少产生三个不同推荐结果，充电紧张真实返回无可行并进入 WAITING，纵深协同真实命中通过严格
恢复校验的 tandem 位。driver profile 在 `InMemorySessionStore` 中按 session/lot 隔离，活动行程
切换 409，手动推进绑定 expected profile/state 和幂等键，正常离场/`DEMO_RESET` 重放不会二次推进。

新增 `DriverDemoProfile`、advance request/response 三个独立 1.0.0 Schema，并向 context/facility
state 增加可选 `demo_profile`；旧必填字段及 Journey/Route/Recommendation/Layout 均不变。内部
`configs/web-v2/m3.toml` 可关闭轮换：固定默认 profile 并拒绝推进端点，作为可运行回滚路径。真实
数据模式继续失败关闭，PUBLIC driver profile 不渗入 defense/legacy。

最终 Web v2 后端 166 项、前端 79 项、Ruff、严格 Mypy、TypeScript、ESLint、OpenAPI 类型漂移、
production build 和 mock 10 项通过；真实 FastAPI + production preview 为 24 passed、1 skipped，
包含四布局全流程、Edge 桌面/Pixel 7 profile 轮换和 Chrome smoke。性能为 gzip 109,276 B、首屏
p95 159.05 ms、mutation p95 327.01 ms、动画 p95 7.40 ms、长帧 0。首轮新增真实用例的两项失败
来自宽松文本选择器命中标题与成功提示，改为精确匹配后完整通过，未改产品行为。六张视觉证据
人工复核通过。M4 现为 `awaiting_review`，授权关闭；M5 未授权。

## 40. 2026-08-21：用户验收 M4 R5 并批准 M4

用户验收 R5 的确定性车主演示情景轮换及其全端证据，批准 M4，并授权按精确文件白名单创建、写明
备注并推送单一 R5 恢复点。R5 恢复点必须记录 Why、What、Validation 和 Boundary，不纳入四类用户
未跟踪资产。

M4 状态改为 `approved`，当前 ExecPlan 清空，实施授权保持关闭。该验收不授权 M5；不得自动创建
M5 分支、实现答辩功能、合并 main 或打 M4 tag。唯一下一步是等待用户另行决定是否授权 M5。

## 41. 2026-08-21：批准 M4 R6 纵深协同离场权威回放

用户希望在车主当前行程完整布局上展示深层纵深车辆被外侧车辆阻挡时的移动过程，并确认推荐方案。
现有 M4 只允许其他占用车辆静态显示，而通用多车动画原属 M5；因此本决定把 M4 重新打开为受限
R6，不授权整个 M5。

R6 采用“服务端权威事务、浏览器事件回放”：FastAPI 基于真实浅深关系、专用 buffer 和同版本路网
生成 `RELOCATE_TO_BUFFER → DIRECT_EXIT → RESTORE_ORIGINAL` 规范链，原子完成 synthetic 离场并
保存可恢复、可重放、带状态哈希的过程证据。React 仅插值服务端 Route，不自行推断 blocker、buffer、
路径或完成状态；页面必须说明这是管理层过程回放，不是实时定位、车辆控制或自动驾驶。

允许新增独立 1.0.0 additive replay 资源/命令端点、调整 `tandem-focus` 固定 fixture、扩展共享画布
显示本事务的当前车辆和 blocker，并增加相称测试与文档。旧 `/depart`、Journey/Route/Layout 必填
字段、`OnlineRuleServiceV2` 排序、legacy、真实源失败关闭和关键依赖不变。缓冲不足、路线不可达、
状态过期、会话错配或真实源必须在移动前失败关闭，Journey 保持 `OCCUPIED`。

R6 完成后 M4 只进入 `awaiting_review` 并关闭授权；必须由用户重新验收。M5 的答辩页面、场景编辑、
自由仿真、算法对比、指标和导出继续未授权。

## 42. 2026-08-21：完成 M4 R6 并等待用户验收

R6 已按批准边界完成。FastAPI 新增独立 additive replay 请求/响应资源和 synthetic-only 命令，
在同一原子边界校验 driver `OCCUPIED` 深层 Journey、`tandem-focus`、真实浅深关系、专用 buffer、
state/layout/cost 身份和三段 Route；成功后权威离场并保存可幂等恢复的不可变 replay，失败保持
Journey 与 profile 不变。旧 `/depart` 和功能开关回滚路径继续可用。

`tandem-focus` 只调整合法可见状态，使未修改的 `OnlineRuleServiceV2` 实际推荐严格可恢复深层位，
不携带或硬编码答案。React 共享画布接受服务端 actor/Route，绿色显示当前车辆、橙色显示 blocker，
展示移至 buffer、当前车辆离场、恢复原位三阶段；前端不提交移位完成，页面明确这是管理层回放，
不是实时定位、车辆控制或自动驾驶。reduced motion 使用可操作的静态阶段。

最终 Web v2 后端 172 项、前端 82 项、mock 10 项、真实 FastAPI + production preview 27 passed/
1 skipped，Ruff、严格 Mypy、TypeScript、ESLint、API 漂移和 production build 均通过。R6 在 Edge
桌面、Pixel 7 与系统 Chrome 完成；gzip 112,590 B，暖首屏 p95 154.49 ms，推荐 mutation p95
368.21 ms，replay mutation p95 92.67 ms，双车动画帧间隔 p95 6.20 ms，长帧 0。四张双视口证据
人工复核通过。M4 现为 `awaiting_review`，实施授权关闭；唯一下一步为用户验收 M4 R6，M5 未授权。
最终审计另以故障注入确认离场后任一内部写入异常会同时回滚 Journey、claim、profile、replay、
幂等表和事件，不留下部分事务。

独立终审曾发现 replay 创建后 profile 已推进到下一轮，而前端刷新会读取下一轮设施状态并叠加旧
replay 的同源性 P2。修复后 replay 内嵌离场当刻完整 `ParkingFacilityStateSnapshot`；Pydantic、
浏览器运行时守卫和 Journey 组合恢复共同校验 parking lot、layout、scenario、state、profile 与
Route cost 身份，画布使用该快照而非已推进的 current state。后端恢复测试、前端错配失败关闭测试
和三端真实流程覆盖刷新同源路径。

## 43. 2026-08-31：批准 R6.1 纵深协同入位与离场闭环

用户指出深层纵深位在入位时同样需要外侧车辆移动，现有“我已停入”直接走普通 `/occupy`，只演示
离场并不完整。用户确认推荐方案，并授权先按精确白名单创建仅本地、不推送的 R6 离场安全恢复点；
恢复点为 `26a0399`，不代表用户验收，也不授权推送。

推荐时若浅层位已经实际占用，现有在线规则会按 `ENTRY_NOT_CLEAR` 拒绝深层候选。为保持
`OnlineRuleServiceV2` 排序、硬约束和未来信息边界不变，R6.1 在推荐阶段只保留浅层协调预留；用户
到达后显式触发入位命令，FastAPI 才原子形成本轮 blocker，并生成
`RELOCATE_TO_BUFFER → DIRECT_ENTRY → RESTORE_ORIGINAL` 权威 replay。成功后保存同一 blocker 的
协调记录，既有离场命令必须复用它，不再从普通 unavailable 状态临时推断车辆。

允许新增独立 1.0.0 arrival Schema/API、可选 Trip Snapshot 恢复字段、session 内协调记录、共享
回放组件的局部重构、fixture 状态投影、测试、视觉证据和交付文档。旧 `/occupy`、`/depart`、
Journey/Route/Layout 必填字段、算法排序、v1、legacy、真实数据语义和关键依赖不变；M5 未授权。
关闭独立 arrival feature flag 时恢复普通入位，既有离场 replay 保留。

## 44. 2026-09-01：R6.1 功能完成，最终验证尚未封存

R6.1 已按批准边界完成。FastAPI 新增独立 additive arrival replay 请求/响应、synthetic-only 端点、
协调记录与事务前后设施快照；`atomic()` 覆盖 Journey、claim、arrival/departure replay、幂等、协调
记录和事件。成功入位后 P-21 blocker 与 P-22 目标均为 occupied、buffer available；后续离场读取
同一协调记录并复用 blocker vehicle ID 与 buffer ID。关闭 arrival flag 恢复普通 `/occupy`。

React 将既有离场面板局部泛化为入位/离场共享视图；深层 eligible Journey 由用户明确触发协同入位，
浏览器只回放服务端 actor/Route 和 before/after 快照，完成动画不提交业务状态。普通位、旧端点、
`OnlineRuleServiceV2` 排序、v1、legacy、真实源和 M5 均未改变，也没有新增关键依赖。

Ruff、严格 Mypy、API 漂移、TypeScript、ESLint、production build 通过；前端 83 passed、mock 10
passed，真实 FastAPI + production preview 为 27 passed/1 skipped，Edge 桌面、Pixel 7、Chrome、
四类 PUBLIC 布局和 12 张阶段证据通过。冻结性能为 gzip 113,419 B、暖首屏 p95 206.14 ms、推荐
p95 948.44 ms、arrival p95 342.71 ms、departure p95 159.93 ms、动画帧 p95 6.30 ms、长帧 0。

Web v2 + contracts 组合 226 passed；仿真冻结性能用例在组合高负载下一次 3.55 s 失败，隔离按原门
复跑 1.83 s 通过 ≤2.0 s。全仓历史 Streamlit 测试因 `.venv` 缺可选 `blinker` 在收集阶段失败，按
治理边界保留并如实记录，没有擅自改变依赖。

独立终审发现 arrival 专项缺少路线不可达、会话错配和多 blocker 的直接证据；这些测试随后补齐并
通过。冻结仿真门先隔离 1.83 s 通过，但在用户活跃 GW2 高 CPU 负载下最新全套/隔离复跑为 5.12 s/
4.09 s，不能用旧通过覆盖新失败。M4 因此保持 `in_progress`，实施授权仅限在安静环境按原 ≤2.0 s
门复跑并取得独立 GO。R6.1 工作区未提交、未推送；M5、main 合并和 tag 均未授权。

## 45. 2026-10-17：接手审计后的受限修复与 M4 性能例外

接手审计证明现有 Route 步骤仅拼接内部 edge/node ID，不符合需求 6.1 的中文转向/到达指引；
需求表单还显示内部 lot ID。用户明确批准一个 M4 受限切片：服务端中文方向指引、前端停车场
中文名，保持路径、距离、ETA、排序、状态机和 Schema 字段不变。转角和退化规则冻结在需求 6.1；
既有设施入口朝向仅作显示解释，不参与寻路。Layout 2.0.0、发布 fixture 和 v1 不改。

仿真 pytest 2.7115064 s 未通过原 ≤2.0 s 门；补充同负载测量 1.982145 s、峰值 108,559 B，hash
一致。用户要求重新提问后，再次明确接受“仅限 M4 演示”的性能例外。保留门、失败和全部样本，
不把例外写成通过，也不放宽 M3/M6；不切换电源或关闭用户进程。

实施前同步授权和修复规则；完成后相称回归并取得独立终审 GO，才可 awaiting_review 和生成新的
开发源码包。未授权提交/推送/M5。外部 Streamlit 取代或补充 M5 的方向仍只是待确认提案。

## 46. 2026-10-18：路径展示与研究算法发布到车主端的交接目标

用户更新目标：遇到问题尝试修复，路径演示和展示更美观，可参考优秀项目；以两站对接为目标，
避免反复测试，最终交接包交给组员实施对接。用户在边界问题中明确选择“最终研究站算法要能
推送到车主端使用”，故后续不再采用研究算法永久只供研究端实验的产品方向。

本轮授权 M4 展示/渲染改进与开发对接候选材料，当前算法和业务契约保持可运行默认；组员接入
发布版本后，须经服务端适配/硬约束/契约/信息隔离/复现/预算验证才能启用，并可回滚。当前
实际算法仍为 online-rule-v2；不新增 M5 界面，不冒充已完成跨站连接。

用户新交付目标允许整理具有明确限制的**开发对接候选包**，与正式 M4 封存区分：历史独立
NO-GO、PERF-02 和所有原始失败继续保留，冻结门不变，不把候选包写成里程碑通过。当前详细
计划改为 m4-route-presentation-integration-handoff.md；不提交、推送、合并或 tag。

本轮展示/静态渲染改进完成后，87组件、26真实功能和原production门一次通过；最后中性title
字面量修正后build/API漂移通过。PERF-02按原受控门复验通过，历史波动/失败保留，不另加
“唯一根因/全负载稳定”门。M4 awaiting_review、实施授权关闭，用户验收尚未完成；开发包的
实际生成、哈希和解包运行以本轮清单/回执为准，不冒充研究算法已跨站上线。
