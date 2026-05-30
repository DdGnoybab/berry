"""Integration tests for SessionRepo."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from berry.core.db.models import User
from berry.core.db.repos.session_repo import SessionRepo
from berry.core.db.repos.user_repo import UserRepo
from berry.domain.enums import Channel, SessionStatus


async def _make_user(db_session: AsyncSession, suffix: str) -> User:
    repo = UserRepo(db_session)
    return await repo.create_or_get_by_external(
        external_source="feishu",
        external_id=f"ou_session_test_{suffix}",
        display_name=f"Session Test {suffix}",
    )


@pytest.mark.asyncio
async def test_get_or_create_creates_when_missing(db_session: AsyncSession) -> None:
    user = await _make_user(db_session, "create")
    repo = SessionRepo(db_session)
    session = await repo.get_or_create(
        user_id=user.id,
        channel=Channel.FEISHU,
        chat_id="chat_create",
    )
    assert session.id is not None
    assert session.user_id == user.id
    assert session.channel == "feishu"
    assert session.channel_chat_id == "chat_create"
    assert session.status == SessionStatus.ACTIVE.value


@pytest.mark.asyncio
async def test_get_or_create_reuses_active_session(db_session: AsyncSession) -> None:
    """Same (user, channel, chat_id) with active status → reuse."""
    user = await _make_user(db_session, "reuse")
    repo = SessionRepo(db_session)
    first = await repo.get_or_create(
        user_id=user.id,
        channel=Channel.FEISHU,
        chat_id="chat_reuse",
    )
    second = await repo.get_or_create(
        user_id=user.id,
        channel=Channel.FEISHU,
        chat_id="chat_reuse",
    )
    assert first.id == second.id


@pytest.mark.asyncio
async def test_get_or_create_creates_new_for_different_chat(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session, "diffchat")
    repo = SessionRepo(db_session)
    first = await repo.get_or_create(
        user_id=user.id,
        channel=Channel.FEISHU,
        chat_id="chat_a",
    )
    second = await repo.get_or_create(
        user_id=user.id,
        channel=Channel.FEISHU,
        chat_id="chat_b",
    )
    assert first.id != second.id


@pytest.mark.asyncio
async def test_get_by_id_returns_none_for_missing(db_session: AsyncSession) -> None:
    repo = SessionRepo(db_session)
    result = await repo.get_by_id(uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_update_status_changes_value(db_session: AsyncSession) -> None:
    user = await _make_user(db_session, "status")
    repo = SessionRepo(db_session)
    session = await repo.get_or_create(
        user_id=user.id,
        channel=Channel.FEISHU,
        chat_id="chat_status",
    )
    await repo.update_status(session.id, SessionStatus.COMPLETED)
    fresh = await repo.get_by_id(session.id)
    assert fresh is not None
    assert fresh.status == SessionStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_list_active_by_user_returns_only_active(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session, "listactive")
    repo = SessionRepo(db_session)
    active = await repo.get_or_create(
        user_id=user.id,
        channel=Channel.FEISHU,
        chat_id="chat_active",
    )
    completed = await repo.get_or_create(
        user_id=user.id,
        channel=Channel.FEISHU,
        chat_id="chat_completed",
    )
    await repo.update_status(completed.id, SessionStatus.COMPLETED)

    rows = await repo.list_active_by_user(user.id)
    ids = {row.id for row in rows}
    assert active.id in ids
    assert completed.id not in ids
