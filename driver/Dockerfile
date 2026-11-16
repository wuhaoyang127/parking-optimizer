# 车主端（driver）单源镜像：FastAPI 同源托管 React 前端。
# 用途：部署到 Render 等稳定平台，替代 cloudflared 隧道，根治 Error 1033。
# 构建上下文 = 仓库根目录；依赖版本与 driver/pyproject.toml 一致。

# ---- 阶段 1：构建 React 前端（engines: node >=24.15 <25）----
FROM node:24-slim AS web
WORKDIR /web
COPY driver/apps/web/package.json driver/apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY driver/apps/web/ ./
RUN npm run build

# ---- 阶段 2：FastAPI 运行时 ----
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 仅安装车主端 API 运行时所需依赖（fastapi/uvicorn/pydantic/jsonschema/referencing/networkx）
RUN pip install --no-cache-dir \
    "fastapi==0.139.2" \
    "uvicorn==0.51.0" \
    "jsonschema[format-nongpl]>=4.25,<5" \
    "referencing>=0.36,<1" \
    "networkx==3.6.1"

# serve.py 依赖 driver/ 目录结构（src/configs/data/schemas/apps/web/dist）
COPY driver/serve.py ./serve.py
COPY driver/src ./src
COPY driver/configs ./configs
COPY driver/data ./data
COPY driver/schemas ./schemas
COPY --from=web /web/dist ./apps/web/dist

EXPOSE 8000

# Render 会注入 PORT 环境变量；本地直接跑时回退 8000
CMD ["sh", "-c", "uvicorn serve:app --host 0.0.0.0 --port ${PORT:-8000}"]
