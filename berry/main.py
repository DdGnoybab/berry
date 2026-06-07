"""FastAPI app 工厂。

为什么用工厂模式而不是模块级 app = FastAPI():
- 测试时能起独立 app 实例,避免全局状态污染
- 方便注入不同配置(测试 / 生产)
- entrypoints/* 可以选择性挂载不同路由集
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from berry import __version__
from berry.channels.web.routes import router as web_router
from berry.core.db.session import engine
from berry.observability.logging import configure_logging, get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """app 生命周期钩子:启动时初始化,关闭时清理。"""
    logger.info("berry_starting", version=__version__)

    # Web 入口:在 uvicorn 事件循环内装配 method registry
    try:
        from berry.entrypoints.web import web_setup

        await web_setup()
    except ImportError:
        pass  # 非 web 入口(如 CLI)不需要

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

    # CORS — 允许前端 dev server 跨域访问
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 路由注册 — web channel 已经把 health 子路由 include 进去了
    app.include_router(web_router)

    return app


# 模块级 app 实例(供 uvicorn 直接 import:`uvicorn berry.main:app`)
app = create_app()
