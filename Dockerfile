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

# 全程走腾讯云 PyPI 镜像(国内访问稳)。
# 用 pip 而不是 uv:berry 的依赖列表里没有 torch / nvidia 这种大包,
# pip 装够快,且在国内镜像下行为最稳。
ENV PIP_INDEX_URL=https://mirrors.tencent.com/pypi/simple/ \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/app/.venv \
    PATH=/app/.venv/bin:$PATH

WORKDIR /app

# 创建 venv,跟 uv sync 产出形状一致(/app/.venv)
RUN python -m venv /app/.venv && \
    /app/.venv/bin/pip install --upgrade pip

# 一次性拷源码并装 —— berry 依赖列表很短,
# 拆分 layer 带来的缓存收益不大,简单优先。
COPY pyproject.toml readme.md ./
COPY berry ./berry
COPY alembic ./alembic
COPY alembic.ini ./
COPY config ./config

# pyproject.toml 里 readme 写的是大写 README.md,Linux 大小写敏感会找不到 →
# 装之前临时把小写软链成大写,装完即弃。这是 berry 自己历史遗留命名问题。
RUN ln -s readme.md README.md

# 装项目 + 依赖(不装 dev group)
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install .


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
