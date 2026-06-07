# Berry backend image — FastAPI + agent runtime.
#
# 多阶段:
#   builder  装依赖、生成 .venv
#   runtime  只拷代码 + .venv,镜像更小
#
# 构建:  docker build -t berry:latest .
# 运行:  通过 docker-compose.yml,不要直接 docker run

# ───── Stage 1: builder ─────
FROM python:3.12-slim AS builder

# uv 是 berry 的依赖管理工具(pyproject.toml + uv.lock)
# 用 pip 装(走 PyPI 国内镜像),不走 ghcr.io —— 国内访问 GitHub Container Registry 慢
RUN pip install --no-cache-dir -i https://mirrors.tencent.com/pypi/simple/ uv==0.5.11

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_INDEX_URL=https://mirrors.tencent.com/pypi/simple/

WORKDIR /app

# 先只拷依赖描述,利用 docker layer cache:
# 代码改动不会触发依赖重装
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# 再拷源码并把项目本身装进 venv
COPY berry ./berry
COPY alembic ./alembic
COPY alembic.ini ./
COPY config ./config
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


# ───── Stage 2: runtime ─────
FROM python:3.12-slim AS runtime

# 非 root 用户跑应用
RUN groupadd -r berry && useradd -r -g berry -d /app -s /sbin/nologin berry

WORKDIR /app

# 从 builder 拷代码 + venv(已包含所有 site-packages)
COPY --from=builder --chown=berry:berry /app /app

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LOG_FORMAT=json

# data_root 挂卷,容器内目录预创建
RUN mkdir -p /app/data && chown -R berry:berry /app/data

USER berry

EXPOSE 8000

# 默认起 web entrypoint(包含 lifespan 装配 method registry)
# 不用 --reload(生产)
CMD ["python", "-m", "berry.entrypoints.web"]
