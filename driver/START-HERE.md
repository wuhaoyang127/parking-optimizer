# 组员先看这里：车主站与研究站算法对接开发包

这是 2026-10-18 的开发源码交接包。当前 React/FastAPI 车主端可演示停车流程；**研究算法发布到
车主端的跨站连接待组员实施**。请先读 TEAMMATE-HANDOFF.md，再看本文件的运行与验证说明。
开发包不代表 M6 自包含离线发布或公网部署，M4 是否验收仍由用户决定。

## 内容与身份

- apps/web：车主前端；src/parking_opt/api：权威 API/会话/路线/纵深服务；schemas/v2、configs、
  data/synthetic：运行所需契约、配置和合成场景；必要只读 v1 模块/Schema/测试基线也在包内。
- docs/integration/web-v2：研究算法发布、校验、启用、回滚的具体接手点与**候选**协议示例。
- SOURCE_MANIFEST.json、FILELIST.txt、SHA256SUMS.txt：来源、逐文件身份与清单；ZIP 本体 hash
  在同目录 .sha256 文件，解包/运行复验回执另附。不要覆盖已有工作目录。
- Git 基线 codex/web-v2-m4-driver-react / 26a0399f11d67211644887b840c361ba7d90e493；上游0/1。
  当前源码包含未提交 R6.1 和本轮补丁，不能仅用 HEAD 复现。没有提交、推送、合并或 tag。

## 准备环境并运行

Windows、Python 3.11.15、Node >=24.15 <25、npm >=11 <12；实际验证 Node 24.19.0/npm 11.17.0。
包不包含解释器、.venv、node_modules、浏览器或已构建资源。首次准备需联网或依赖缓存。

```powershell
uv sync --locked --python 3.11.15 --extra web-api
npm --prefix apps/web ci
npm --prefix apps/web run demo
```

依赖准备完成后也可双击 START-WEB-V2.cmd，它检查环境并调用同一个 demo 入口，不自动安装。
Python 使用本目录 .venv，不静默换全局环境；uv --locked/ npm ci 不应改依赖锁。
uv 本机未安装，因此本轮没有做干净机安装。源码包已实际解包运行，借用原冻结依赖；包内
PACKAGE_VERIFICATION.json明确记录这一点，最终分发包与已运行源码的实现hash完全相同。
参考 https://docs.astral.sh/uv/concepts/projects/sync/ 和 https://docs.npmjs.com/cli/v11/commands/npm-ci/ 。

打开 http://127.0.0.1:4173/ ，API 健康为 http://127.0.0.1:8000/api/v2/health 。启动器先构建
当前代码再开回环服务；终端 Ctrl+C 同时结束二者。端口占用时识别来源，不结束未知进程；
不使用旧服务替代当前源码。不提供明文 LAN 手机模式，手机可用浏览器设备模拟验收。

## 演示路径

普通流程：找停车场 → 完整布局 → 获取推荐 → 30秒内确认 → 开始指引 → 自行确认停入 → 正常离场。
路线预览/动画不会自行停车，路线文字由后端生成，起终点及进度用于管理层演示。

纵深：选择学校场，逐次“换一组模拟状态”直到页面显示“纵深协同”（按实际当前状态，勿盲按固定
次数）→ 获取推荐 → 接受协同停车 → 开始指引 → 显式协同入位 → 查看停车状态 → 协同离场。
绿色当前车辆与橙色阻挡车分角色显示，服务端保存并复用同一 blocker/buffer 协调记录。

## 已验证与限制

本轮类型/lint、87组件、真实 Edge 桌面/手机及 Chrome 共26项功能验收通过；针对展示/渲染改动
只运行一次原预算 production 性能门并通过：gzip114707B，首屏p95 206.27ms，推荐381.98ms，
入位158.32ms，离场106.13ms，帧p95 6.2ms，>100ms长帧0。随后仅移除共享终点 title 的停车指令，
最终 build/API 漂移及实际解包可见行为均通过，回执在包内PACKAGE_VERIFICATION.json；未因
这条辅助文字重复全套性能测试。最终rVBs4Kqo构建桌面/手机实拍亦在包内。

后端/契约未因展示改动变化，复用此前241 passed/1仿真失败、53Schema/OpenAPI一致的证据。
仿真原门≤2.0s保留：2.7115064s及2.006702s失败、1.982145s补充测量均保存，用户只接受M4演示
仿真例外。历史 production 6长帧和推荐超时及旧独立NO-GO也保留；当前一次通过不证明所有负载
都稳定。报告在 docs/audits/web-v2/2026-10-18-route-handoff/，前阶段原始记录在2026-10-17目录。

所有设施为 synthetic；UI 插值不是实时定位/控制/避碰，真实数据失败关闭。重启会丢失演示内存
会话。Safari/iPhone实机、Firefox、公网、干净机安装、自包含离线交付及真实跨站算法接入尚未完成。
M5完整答辩界面、真实车辆感知和算法自动上线不包含在本包已实现功能中。

## 回滚与保护

本轮展示修改前5份源码及哈希位于 docs/audits/web-v2/2026-10-18-route-handoff/rollback/presentation/；
仅恢复对应文件并同步测试/文档，先保留后续开发修改。中文指引/名称的更早回滚位于
rollback/nav-ux/；两套不是同一恢复点。协同入位/离场可通过 configs/web-v2/m3.toml 的相应
feature flag 回退普通 occupy/depart；additive Schema 保留。

排除 .git、.env/密钥、依赖/缓存/构建目录、旧 ZIP、本机工具和用户未跟踪资产（采集停车场、
商业计划书、logo、run.cmd 等）。没有覆盖历史 Streamlit 入口或实验结果；不对旧研究实验声称重验。
