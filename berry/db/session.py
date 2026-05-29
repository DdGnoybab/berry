"""异步数据库 session 管理。

业务代码用 asyncpg(高性能、异步原生)。
alembic 用同步 psycopg(迁移工具更稳)。
两套 URL 在 berry/config.py 里统一生成。
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from berry.config import settings

# 全局 engine(进程级单例)
# echo=False:生产关掉 SQL 日志;调试时改 True 或用 LOG_LEVEL=DEBUG 时打开
engine: AsyncEngine = create_async_engine(
    settings.database_url_async,
    echo=False,
    pool_pre_ping=True,  # 连接池每次取连接前 ping 一下,防 stale 连接
    pool_size=5,          # MVP 阶段够用,V1 起按 QPS 调
    max_overflow=10,
)

# Session 工厂:expire_on_commit=False 让 commit 后对象仍可用
async_session_factory = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI Depends 用的 session 生成器。

    用法:
        @app.get("/users")
        async def list_users(session: AsyncSession = Depends(get_session)):
            ...
    """
    async with async_session_factory() as session:
        yield session


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """非 FastAPI 场景用的 context manager。

    用法:
        async with session_scope() as session:
            await session.execute(...)
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
