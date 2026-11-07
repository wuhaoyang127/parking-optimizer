# Web v2 车主端

本目录是 M4 React + TypeScript + Vite 车主端。当前使用明确标记的 synthetic 数据与 FastAPI v2
契约，不代表真实停车场运营，也不提供实车级导航或自动驾驶能力。

## 环境

- Node.js `24.18.0` LTS；
- npm `11.16.0`；
- Windows PowerShell；
- 后端默认地址 `http://127.0.0.1:8000`；
- Vite 开发地址 `http://127.0.0.1:5173`。

本机没有系统级 Node 时，可将官方便携 Node 的目录临时加入当前 PowerShell 的 `PATH`。便携
运行时和 Playwright 浏览器属于本机工具，不提交 Git。

## 安装与验证

```powershell
cd apps\web
npm ci
npm run generate:api
npm run check:api
npm run test
npm run typecheck
npm run lint
npm run build
npm run test:e2e
```

`generate:api` 从仓库根目录 `schemas/v2/openapi.json` 生成 `src/api/schema.d.ts`；
`check:api` 在临时目录重新生成并逐字节比较，防止前端类型与 FastAPI/OpenAPI 漂移。

## 本地开发

先在一个终端启动 FastAPI（必须使用 `h11`，见下方失败案例）：

```powershell
cd <仓库根目录>
.\.venv\Scripts\python.exe -m uvicorn parking_opt.api.app:app --app-dir src --host 127.0.0.1 --port 8000 --http h11
```

再在另一个终端启动 Vite：

```powershell
npm run dev
```

Vite 将 `/api` 代理到 FastAPI。前端不得自行实现推荐、锁位、预留、路径或占用算法；这些状态
必须来自 v2 API。浏览器断线时显示明确错误，不得静默切换到随机假数据。

## 一键本地演示与真实联调

`npm run demo` 会构建当前 production 资源，同时启动 FastAPI synthetic 与 Vite preview；访问
`http://127.0.0.1:4173`，按 `Ctrl+C` 同时停止两个服务。

```powershell
cd apps\web
npm run demo
```

真实浏览器验收不会拦截 API；它会构建当前代码、健康等待双服务、串行运行 Edge 桌面、Pixel 7
模拟手机和 Chrome 桌面 smoke，并在结束后清理服务：

```powershell
npm run test:e2e:real
```

若 Uvicorn 自动选择本机已安装但不兼容的 `httptools`，可能出现
`AttributeError: HttpRequestParser`。本项目固定 `--http h11` 以使用已验证的 HTTP 实现；这不是业务
契约或推荐算法失败。脚本依赖仓库 `.venv` 和当前执行 npm 的 Node，不写死个人电脑绝对路径。

## 当前边界

M4 只实现车主模式的“找停车场、智能停车、当前行程”。答辩模式、自由实验台、伪 3D、新算法、
真实数据连接器和公网部署分别属于后续里程碑，不在本目录当前实现范围内。
