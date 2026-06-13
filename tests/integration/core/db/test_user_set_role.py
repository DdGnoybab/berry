"""berry-cli user set-role 集成测试。

直接调 _set_role coroutine,patch async_session_factory 走 conftest 的 db_session。
覆盖:
  - 用户不存在 → exit 1
  - 非法 role → exit 2
  - role 改了 → exit 0,DB 落库
  - 已经是目标 role → exit 0(幂等)
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from berry.core.db.models import User
from berry.entrypoints import admin as admin_module


@pytest.fixture
def patch_session(monkeypatch, db_session: AsyncSession):
    """让 admin._set_role 等命令用我们的 test session 而不是开新连接。

    admin.py 用 `async with async_session_factory() as db`,所以我们提供
    一个 async context manager,yield db_session,不真的关闭它(让 fixture 管)。
    """
    @asynccontextmanager
    async def _factory():
        yield db_session

    monkeypatch.setattr(admin_module, "async_session_factory", _factory)


@pytest.mark.asyncio
async def test_set_role_user_not_found(patch_session, capsys) -> None:
    rc = await admin_module._set_role("nonexistent_user_xyz", "admin")
    assert rc == 1
    err = capsys.readouterr().err
    assert "not found" in err


@pytest.mark.asyncio
async def test_set_role_invalid_role(patch_session, capsys) -> None:
    rc = await admin_module._set_role("anyone", "superuser")
    assert rc == 2
    err = capsys.readouterr().err
    assert "invalid role" in err


@pytest.mark.asyncio
async def test_set_role_promotes_user_to_admin(
    patch_session, db_session: AsyncSession, capsys
) -> None:
    user = User(handle="web:setrole_promote", display_name="Promote Me", role="user")
    db_session.add(user)
    await db_session.commit()

    rc = await admin_module._set_role("setrole_promote", "admin")
    assert rc == 0
    out = capsys.readouterr().out
    assert "user → admin" in out

    # 确认 DB 真的改了
    refetched = await db_session.execute(
        select(User).where(User.handle == "web:setrole_promote")
    )
    row = refetched.scalar_one()
    assert row.role == "admin"


@pytest.mark.asyncio
async def test_set_role_same_role_is_noop(
    patch_session, db_session: AsyncSession, capsys
) -> None:
    user = User(handle="web:setrole_already", display_name="Already Admin", role="admin")
    db_session.add(user)
    await db_session.commit()

    rc = await admin_module._set_role("setrole_already", "admin")
    assert rc == 0
    out = capsys.readouterr().out
    assert "already admin" in out


@pytest.mark.asyncio
async def test_set_role_demote_admin_to_user(
    patch_session, db_session: AsyncSession
) -> None:
    user = User(handle="web:setrole_demote", display_name="Demote", role="admin")
    db_session.add(user)
    await db_session.commit()

    rc = await admin_module._set_role("setrole_demote", "user")
    assert rc == 0

    refetched = await db_session.execute(
        select(User).where(User.handle == "web:setrole_demote")
    )
    assert refetched.scalar_one().role == "user"
