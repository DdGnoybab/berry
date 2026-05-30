"""Shared pytest fixtures for Berry tests.

Strategy: connect to the local Postgres at localhost:5432 (user `bbb`).
At session start, create a fresh database `berry_test_<random>`, run alembic
upgrade head against it, and use it for all integration tests.
At session end, drop the database.

This isolates test data from the dev `berry` database while still exercising
real Postgres semantics (jsonb, gen_random_uuid, FK CASCADE).
"""

from __future__ import annotations

import os
import secrets
from collections.abc import AsyncIterator, Iterator

import psycopg
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Local PG connection — matches your .env's DATABASE_URL.
_PG_HOST = os.environ.get("BERRY_TEST_PG_HOST", "localhost")
_PG_PORT = int(os.environ.get("BERRY_TEST_PG_PORT", "5432"))
_PG_USER = os.environ.get("BERRY_TEST_PG_USER", "bbb")
_PG_PASSWORD = os.environ.get("BERRY_TEST_PG_PASSWORD", "berry")
# Connect to the maintenance DB to issue CREATE/DROP DATABASE.
_PG_ADMIN_DB = os.environ.get("BERRY_TEST_PG_ADMIN_DB", "postgres")


def _admin_dsn(dbname: str = _PG_ADMIN_DB) -> str:
    return (
        f"host={_PG_HOST} port={_PG_PORT} "
        f"user={_PG_USER} password={_PG_PASSWORD} dbname={dbname}"
    )


@pytest.fixture(scope="session")
def test_db_name() -> Iterator[str]:
    """Create a unique test database for the whole pytest session, drop at end."""
    name = f"berry_test_{secrets.token_hex(4)}"
    # CREATE DATABASE must run outside a transaction.
    with psycopg.connect(_admin_dsn(), autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    try:
        yield name
    finally:
        with psycopg.connect(_admin_dsn(), autocommit=True) as conn:
            # Terminate connections lingering on the test db before dropping.
            conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (name,),
            )
            conn.execute(f'DROP DATABASE IF EXISTS "{name}"')


@pytest.fixture(scope="session")
def postgres_async_url(test_db_name: str) -> str:
    """Async URL for sqlalchemy[asyncio] (uses asyncpg)."""
    return (
        f"postgresql+asyncpg://{_PG_USER}:{_PG_PASSWORD}"
        f"@{_PG_HOST}:{_PG_PORT}/{test_db_name}"
    )


@pytest.fixture(scope="session", autouse=True)
def apply_migrations(test_db_name: str) -> Iterator[None]:
    """Run alembic upgrade head against the test DB once per session.

    Berry's alembic/env.py reads ``settings.database_url_sync`` at runtime,
    so we monkey-patch ``settings.database_url`` for the alembic run, then
    restore it. The application's own DB URL stays untouched outside this
    fixture's scope.
    """
    from berry.config import settings

    test_url_unprefixed = (
        f"postgresql://{_PG_USER}:{_PG_PASSWORD}"
        f"@{_PG_HOST}:{_PG_PORT}/{test_db_name}"
    )
    original_url = settings.database_url
    object.__setattr__(settings, "database_url", test_url_unprefixed)
    try:
        cfg = AlembicConfig("alembic.ini")
        command.upgrade(cfg, "head")
        yield
    finally:
        object.__setattr__(settings, "database_url", original_url)


@pytest_asyncio.fixture
async def db_session(postgres_async_url: str) -> AsyncIterator[AsyncSession]:
    """Per-test AsyncSession against the temp DB.

    Tests don't share data because each test creates its own user/session
    rows with unique external_id / chat_id, and integration tests are read-
    your-own-writes only.
    """
    engine = create_async_engine(postgres_async_url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()
