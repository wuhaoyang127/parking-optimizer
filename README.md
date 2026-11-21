# 智能停车优化与调度系统

面向停车场「车位分配 + 纵深移位」的算法研究与演示系统，分为两个端：

- **研究端（Streamlit）**：布局/需求导入、仿真对比、指标分析、布局与算法发布；
- **车主端（Web v2，React + FastAPI）**：面向车主的完整停车演示——找停车场 → 智能推荐 → 行程导航 → 纵深移位回放。

> 本项目不实现真实车辆感知、自动驾驶控制、避碰或轨迹跟踪；路网只处理管理层可达性、路径成本和通道资源占用。

## 当前进度（已上线）

- **布局推送**：研究端自定义布局（nodes/edges）→ 车主端，进入发现区地图与推荐列表；
- **算法推送**：研究端发布算法 → 车主端校验、启用（在线规则、RHO 滚动时域、ML 时长树等）；
- **持久化**：推送的布局与算法发布记录存入 Supabase，服务重启不丢；
- **大布局性能**：212 车位布局的推荐由超时优化到约 6 秒返回；
- **安全加固**：安全响应头、XSS 修复、登录限流与服务端锁死、上传大小限制、密钥不入库。

## 车主端（Web v2）

- 线上地址：<https://parking-driver.onrender.com>
- 功能：找停车场 / 智能推荐 / 当前行程 / 车位平面图（2D）/ 纵深移位回放 / 高级模式；
- 默认车主模式只展示完成停车所需的信息，算法名、参数等细节隐藏。

## 研究端（Streamlit）

- 功能：布局与需求导入、仿真对比、指标分析、布局推送、算法推送、状态页健康检查；
- 数据按账号隔离（每人看到自己的布局、参数与历史记录）；
- 「推送到车主端」即发布到公网——所有访问车主端的人都能看到。

## 技术栈

| 端 | 技术 |
|---|---|
| 研究端 | Python 3.11 + Streamlit + Supabase + 自研 `parking_opt`（事件仿真 + 策略） |
| 车主端 | React + TypeScript + Vite + FastAPI + Supabase，Docker 部署 |
| 部署 | 研究端 Streamlit Cloud；车主端 Render（Dockerfile） |

## 关键目录

```text
parking-optimizer/
├─ app.py                # 研究端 Streamlit 入口
├─ src/                  # 研究端（仿真、策略、UI、鉴权、推送）
├─ migrations/           # Supabase SQL 迁移（按编号顺序执行）
├─ driver/
│  ├─ serve.py           # 车主端 FastAPI（单源托管 React dist + /api）
│  ├─ Dockerfile         # 车主端多阶段构建（node 构建前端 + python 运行）
│  ├─ src/parking_opt/   # 车主端后端（v2 契约、推荐、行程、设施布局、研究接入）
│  ├─ apps/web/          # 车主端 React 前端
│  └─ schemas/v2/        # v2 契约 Schema
├─ docs/                 # 模型、数据、产品、交接文档
├─ configs/              # 参数与场景
├─ outputs/              # 运行产物
└─ references/           # 原始申请书与论文（只读）
```

## 分支

- `main` / `stage-d-deliver`：当前工作与交付分支（已同步到同一提交）；
- 其余 `stage-*` 分支为历史阶段快照。

## 本地运行

研究端：

```powershell
pip install -r requirements.txt
streamlit run app.py
# Supabase 配置：复制 .streamlit/secrets.toml.example 为 secrets.toml 并填写
```

车主端：见 `driver/README.md` 与 `driver/AGENTS.md`（本地联调入口为 `driver/serve.py` 或 Docker 构建）。

## 自检

```powershell
python scripts/check_file_lines.py   # 单文件行数 ≤ 200 检查
```

## 重要边界

- 在线算法不读未来真值；`unknown` 状态一律排除推荐；真实数据缺失时失败关闭，不用 synthetic 冒充真实；
- 纵深位用 `stack_group_id` + `depth` 表示，缓冲位不参与推荐；
- 密钥、令牌、真实车牌与未脱敏数据不入库、不提交。
