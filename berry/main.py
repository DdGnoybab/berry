"""FastAPI app 工厂。

为什么用工厂模式而不是模块级 app = FastAPI():
- 测试时能起独立 app 实例,避免全局状态污染
- 方便注入不同配置(测试 / 生产)
- entrypoints/* 可以选择性挂载不同路由集
"""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from berry import __version__
from berry.core.db.session import engine
from berry.gateway.http.health import router as health_router
from berry.observability.logging import configure_logging, get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """app 生命周期钩子:启动时初始化,关闭时清理。"""
    logger.info("berry_starting", version=__version__)
    yield
    logger.info("berry_stopping")
    # 关闭 DB 连接池
    await engine.dispose()


def create_app() -> FastAPI:
    """创建 FastAPI app 实例。"""
    # 日志配置:进程启动时调一次
    # 本地开发用 console 易读,生产 JSON
    import os
    log_format = os.environ.get("LOG_FORMAT", "console")
    configure_logging(log_format=log_format)

    app = FastAPI(
        title="Berry",
        version=__version__,
        description="飞书原生个人工作台 / 编码 Agent 后端",
        lifespan=lifespan,
    )

    # 路由注册
    app.include_router(health_router)

    return app


# 模块级 app 实例(供 uvicorn 直接 import:`uvicorn berry.main:app`)
app = create_app()
