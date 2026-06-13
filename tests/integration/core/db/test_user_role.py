"""User.role 字段 + require_admin dep 集成测试。

跑真 PG,验证:
  1. alembic upgrade 后 users 表有 role 列,server_default 'user'
  2. 老行 INSERT 不传 role 也能成功(走 server_default)
  3. require_admin 对普通 user 返 403,对 admin 通过

(2) 是关键 — 防御性测试,确保迁移真的把 server_default 加上了。
"""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from berry.channels.web.auth.deps import require_admin
from berry.core.db.models import User


def _make_request_with_user(user_id: UUID) -> Request:
    """Synthesize a Starlette Request whose state.user_id is set,
    matching what AuthMiddleware would have produced."""
    scope = {
        "type": "http",
        "method": "GET",
        "headers": [],
        "path": "/v1/admin/logs/files",
        "state": {},
    }
    req = Request(scope)
    req.state.user_id = user_id
    return req


@pytest.mark.asyncio
async def test_role_column_defaults_to_user(db_session: AsyncSession) -> None:
    """INSERT 不指定 role,server_default 应该填 'user'。"""
    user = User(handle="test:nodefault", display_name="Test User")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    assert user.role == "user"


@pytest.mark.asyncio
async def test_can_create_admin_user(db_session: AsyncSession) -> None:
    user = User(handle="test:admin1", display_name="Admin", role="admin")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    assert user.role == "admin"


@pytest.mark.asyncio
async def test_require_admin_rejects_user(
    db_session: AsyncSession, monkeypatch
) -> None:
    """role='user' 走 require_admin 应该 403。"""
    user = User(handle="test:user2", display_name="User2", role="user")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    # require_admin 用 berry.core.db.session.async_session_factory,
    # 测试里用 patch 让它走我们的 test session
    from berry.channels.web.auth import deps

    class _StubSessionCtx:
        async def __aenter__(self) -> AsyncSession:
            return db_session

        async def __aexit__(self, *_a) -> None:
            return None

    monkeypatch.setattr(deps, "async_session_factory", lambda: _StubSessionCtx())

    req = _make_request_with_user(user.id)
    with pytest.raises(HTTPException) as exc_info:
        await require_admin(req)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_admin_accepts_admin(
    db_session: AsyncSession, monkeypatch
) -> None:
    """role='admin' 应该返回 AdminUser。"""
    admin = User(handle="test:admin2", display_name="Admin2", role="admin")
    db_session.add(admin)
    await db_session.commit()
    await db_session.refresh(admin)

    from berry.channels.web.auth import deps

    class _StubSessionCtx:
        async def __aenter__(self) -> AsyncSession:
            return db_session

        async def __aexit__(self, *_a) -> None:
            return None

    monkeypatch.setattr(deps, "async_session_factory", lambda: _StubSessionCtx())

    req = _make_request_with_user(admin.id)
    out = await require_admin(req)
    assert out.user_id == admin.id
    assert out.role == "admin"


@pytest.mark.asyncio
async def test_require_admin_no_user_id_in_state(monkeypatch) -> None:
    """state.user_id 缺失 → 401。理论上中间件兜底,这里防御。"""
    scope = {
        "type": "http",
        "method": "GET",
        "headers": [],
        "path": "/x",
        "state": {},
    }
    req = Request(scope)
    # intentionally don't set state.user_id
    with pytest.raises(HTTPException) as exc_info:
        await require_admin(req)
    assert exc_info.value.status_code == 401
