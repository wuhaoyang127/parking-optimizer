# Web v2 M4 车主端运行与验收说明

## 1. 适用范围

本说明用于 M4 车主模式的本地开发验收：当前 production build、FastAPI synthetic 单进程和 Vite
production preview 在回环地址联调。它不是 M6 离线发布包或公网部署说明，也不包含任何 M5
答辩功能。

当前成果只演示版本化 synthetic 停车场、管理层二维布局和 Route 的 UI 插值；不代表真实空位、
实时定位、实车导航、自动驾驶控制或生产并发能力。

## 2. 冻结环境

- Windows；
- 仓库 `.venv`：Python 3.11；
- `apps/web/package.json`：Node `>=24.15.0 <25`、npm `>=11 <12`；
- 标准端口：FastAPI `127.0.0.1:8000`、Vite preview `127.0.0.1:4173`。

不要静默改用全局 Python、不同 Node 主版本或未知已运行服务。缺依赖时先按 lockfile 恢复环境，
不要临时替换关键依赖。

## 3. 一键运行

在仓库根目录执行：

```powershell
npm --prefix apps/web run demo
```

该命令先构建当前 production 资源，再检查两个标准端口空闲，随后启动 FastAPI 与 Vite preview。
准备完成后访问 `http://127.0.0.1:4173`；健康检查为：

```text
http://127.0.0.1:8000/api/v2/health
http://127.0.0.1:4173/
```

若 8000 或 4173 已被占用，脚本会失败关闭。先识别监听进程和命令行；不得直接终止未知服务，
也不得把旧服务当作当前代码证据。

## 4. 正常停止

在启动终端按 `Ctrl+C`。脚本应停止两个子服务并释放 8000/4173。可只读确认：

```powershell
Get-NetTCPConnection -State Listen -LocalPort 8000,4173 -ErrorAction SilentlyContinue
```

无输出表示两个标准端口均已释放。不要让后台服务遗留到下一次验收。

## 5. 验证漏斗

在仓库根目录依次执行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\web_v2
.\.venv\Scripts\python.exe -m ruff check src\parking_opt\api tests\web_v2
.\.venv\Scripts\python.exe -m mypy src\parking_opt\api
npm --prefix apps/web test -- --run
npm --prefix apps/web run typecheck
npm --prefix apps/web run lint
npm --prefix apps/web run check:api
npm --prefix apps/web run build
npm --prefix apps/web run test:e2e
npm --prefix apps/web run test:e2e:real
node apps/web/scripts/probe-orchestration.mjs
```

`test:e2e` 是 mock 快速状态门；`test:e2e:real` 才会重新构建并启动真实 FastAPI + production
preview，覆盖 Edge 桌面、Pixel 7 和系统 Chrome。生成当前 R6 视觉证据时使用：

```powershell
$env:R6_CAPTURE_VISUALS = "1"
npm --prefix apps/web run test:e2e:real
Remove-Item Env:R6_CAPTURE_VISUALS
```

证据写入 `docs/visual-qa/web-v2/m4-r6/`。R4/R5 历史证据继续保留，不覆盖旧验收。
不得为了通过测试放宽 ExecPlan 中冻结的性能阈值。

车主请求页只在 PUBLIC synthetic 模式显示“模拟状态”和“换一组模拟状态”。活动行程期间端点会
返回 409；正常离场或演示重置后下一轮自动推进。需回滚时将 `configs/web-v2/m3.toml` 的
`driver_demo.profiles_enabled` 设为 `false` 并重启当前服务：页面固定“平峰通行”，推进端点失败关闭；
不得把该配置用于真实数据补值。

R6.1 的稳定演示路径为：学校停车场空闲态连续切换到“纵深协同” → 获取智能推荐 → 接受协同停车
并确认 → 开始场内指引 → 明确点击“我已到达，开始协同入位” → 查看外侧车辆移至 `BUF-01`、
当前车辆进入 `P-22`、外侧车辆恢复 `P-21` → “查看停车状态” → “演示协同移位后离场”。离场继续
展示同一外侧车辆移至同一 buffer、当前车辆驶向出口、外侧车辆恢复原位。刷新可恢复同一 replay，
重播只改变 UI 时间轴。

关闭 `driver_demo.tandem_arrival_replay_enabled` 并重启后，深层目标恢复普通 `/occupy`；关闭
`driver_demo.tandem_departure_replay_enabled` 可恢复普通 `/depart`。两个 additive Schema 均保留，
旧端点不变。回放是已完成服务端事务的管理层事件证据，不是实时定位、车辆控制或自动驾驶。

## 6. 已知非阻断限制

- Starlette TestClient 对当前 httpx 的第三方弃用警告不改变 Web v2 运行结果；不得为消除警告而
  未经授权替换关键依赖；
- 全仓历史 Streamlit 测试在缺少可选 `blinker` 时可能收集失败；Web v2 门使用
  `tests/web_v2`，历史问题仍须如实保留；
- Safari/iPhone 实机、公网部署和离线发布物属于 M6 前置条件，不由 M4 自动声明完成。
