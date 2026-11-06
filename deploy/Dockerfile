# ============================================================
# NOTE: 本文件是项目根 Dockerfile 的部署副本（deploy 目录内置，
# 由 deploy/docker-compose.yml 指定 dockerfile: deploy/Dockerfile 使用）。
# 与项目根 Dockerfile 相比，差异在下载源可配置（build-arg）：
#   NPM_REGISTRY   npm 包下载源（默认 npmmirror 镜像）
#   PYPI_INDEX_URL PyPI 包下载源（默认清华镜像）
# 修改项目根 Dockerfile 时请同步本文件。
# ============================================================
# Stage 1: 构建前端
# ============================================================
FROM node:24-slim AS frontend-builder

# npm 下载源，由构建脚本 --registry 传入；默认 npmmirror 镜像（国内快）
# pnpm 会读取该 registry 并重写 lockfile 中的 tarball URL
ARG NPM_REGISTRY=https://registry.npmmirror.com

WORKDIR /build/frontend

# 启用 corepack；pnpm 版本由 frontend/package.json 的 packageManager 字段固定
# 关闭交互式下载确认，否则 docker build 这种非 TTY 环境会卡在
# "Corepack is about to download ..." 直到超时
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
ENV NODE_OPTIONS=--max-old-space-size=3072
# 引用全局 ARG（命令行 --build-arg 传入或回退到上面的默认值）
ARG NPM_REGISTRY
ENV npm_config_registry=${NPM_REGISTRY}

RUN corepack enable

# 先复制依赖文件，利用缓存（corepack 按 packageManager 字段自动下载对应 pnpm）
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# 复制前端源码并构建
COPY frontend/ ./
RUN pnpm build

# ============================================================
# Stage 2: 生产镜像
# ============================================================
FROM python:3.12-slim AS production

# PyPI 下载源，由构建脚本 --registry 传入；默认清华镜像（国内快）
ARG PYPI_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    bubblewrap \
    socat \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# 升级基础镜像预装的 pip：依赖全部由 uv 安装、运行时不调用 pip，
# 但 python:3.12-slim 自带的旧 pip 会被镜像扫描器报 CVE，升级以清除这些告警
RUN python -m pip install --no-cache-dir --upgrade pip

# 安装 uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# 禁用 Python 输出缓冲，确保日志实时输出到 Docker logs
ENV PYTHONUNBUFFERED=1

# 默认时区，可由 docker-compose / 运行时 -e TZ=... 覆盖
ENV TZ=Asia/Shanghai

# 先复制依赖和包元数据文件，利用缓存
COPY pyproject.toml uv.lock README.md ./
# uv workspace 成员（packages/ 必须在 uv sync 前就位，否则锁文件解析失败）
COPY packages/ packages/
# uv 从镜像源安装依赖，避免直连 pypi.org 网络慢
RUN uv sync --no-dev --no-install-project --index-url "${PYPI_INDEX_URL}"

# 复制应用代码
COPY lib/ lib/
COPY server/ server/
COPY alembic/ alembic/
COPY alembic.ini ./
COPY scripts/ scripts/
COPY agent_runtime_profile/ agent_runtime_profile/
COPY public/ public/

# 复制前端构建产物
COPY --from=frontend-builder /build/frontend/dist/ frontend/dist/

# 创建运行时目录
RUN mkdir -p projects vertex_keys

# 暴露端口
EXPOSE 1241

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:1241/health || exit 1

# 启动命令
# --timeout-keep-alive 800：调大 keep-alive 窗口（uvicorn 默认仅 5s）。
# 客户端（ComfyUI 插件）已实现共享 keep-alive 连接 + 锁；服务端窗口过短
# 会在操作空档（>5s）关闭连接，客户端被迫重建 TCP（Windows Docker HNS
# 建连实测 ~21s）。调大到 300s 后正常操作间隔内连接保持存活，消除反复建连。
CMD ["uv", "run", "uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "1241", "--timeout-keep-alive", "800"]
