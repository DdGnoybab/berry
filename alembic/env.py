"""Alembic 环境配置(同步驱动版)。

为什么用同步而不是 async:
- 迁移是一次性、低频操作,async 没收益
- 同步驱动(psycopg)alembic 支持最稳
- 应用代码用 asyncpg 不冲突(各走各的 URL)

模型自动检测:
- 必须 import berry.db.models,把表挂到 SQLModel.metadata
- target_metadata 指向 SQLModel.metadata,autogenerate 才能扫到
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

# ★ 关键:import 一次让 SQLModel.metadata 知道有这些表
from berry.config import settings
from berry.db import models  # noqa: F401

# ─── alembic 标准配置 ───
config = context.config

# 把 DATABASE_URL 注入 alembic config(覆盖 alembic.ini 的占位)
config.set_main_option("sqlalchemy.url", settings.database_url_sync)

# 日志
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ★ 让 autogenerate 能扫到模型
target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    """离线模式:不连 DB,生成 SQL 脚本。

    用法:`alembic upgrade head --sql > migration.sql`
    一般不用,生产环境批量执行才需要。
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,  # 检测列类型变化
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式:连 DB 跑迁移。日常用这个。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            # 让 autogenerate 检测 server_default 变化(jsonb default 等)
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
