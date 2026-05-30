"""Integration tests for MessageRepo."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from berry.core.db.repos.message_repo import MessageRepo
from berry.core.db.repos.session_repo import SessionRepo
from berry.core.db.repos.user_repo import UserRepo
from berry.core.llm.types import (
    LlmMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from berry.domain.enums import Channel


async def _make_session(db_session: AsyncSession, suffix: str):
    user = await UserRepo(db_session).create_or_get_by_external(
        external_source="feishu",
        external_id=f"ou_msg_test_{suffix}",
        display_name=f"Msg Test {suffix}",
    )
    return await SessionRepo(db_session).get_or_create(
        user_id=user.id, channel=Channel.FEISHU, chat_id=f"chat_msg_{suffix}",
    )


@pytest.mark.asyncio
async def test_append_user_text_message(db_session: AsyncSession) -> None:
    session = await _make_session(db_session, "user_text")
    repo = MessageRepo(db_session)
    msg = LlmMessage.user("hello")
    row = await repo.append(session.id, msg)
    assert row.id is not None
    assert row.session_id == session.id
    assert row.role == "user"
    assert row.content == [{"type": "text", "text": "hello"}]


@pytest.mark.asyncio
async def test_append_assistant_with_multiple_blocks(
    db_session: AsyncSession,
) -> None:
    session = await _make_session(db_session, "asst_multi")
    repo = MessageRepo(db_session)
    msg = LlmMessage(
        role="assistant",
        content=[
            ThinkingBlock(text="user wants to find TODOs"),
            TextBlock(text="OK, let me check."),
            ToolUseBlock(id="toolu_x", name="grep", input={"pattern": "TODO"}),
        ],
    )
    row = await repo.append(session.id, msg)
    assert row.role == "assistant"
    assert len(row.content) == 3
    assert row.content[0]["type"] == "thinking"
    assert row.content[2]["type"] == "tool_use"
    assert row.content[2]["id"] == "toolu_x"


@pytest.mark.asyncio
async def test_append_tool_result_message(db_session: AsyncSession) -> None:
    """tool_result lives inside a user-role message per Anthropic protocol."""
    session = await _make_session(db_session, "toolres")
    repo = MessageRepo(db_session)
    msg = LlmMessage(
        role="user",
        content=[
            ToolResultBlock(tool_use_id="toolu_x", output="found 3 TODOs"),
        ],
    )
    row = await repo.append(session.id, msg)
    assert row.role == "user"
    assert row.content[0]["type"] == "tool_result"
    assert row.content[0]["tool_use_id"] == "toolu_x"
    assert row.content[0]["is_error"] is False


@pytest.mark.asyncio
async def test_list_by_session_returns_in_chronological_order(
    db_session: AsyncSession,
) -> None:
    session = await _make_session(db_session, "order")
    repo = MessageRepo(db_session)
    await repo.append(session.id, LlmMessage.user("first"))
    # tiny sleep to ensure different created_at
    await asyncio.sleep(0.01)
    await repo.append(session.id, LlmMessage.assistant("second"))
    await asyncio.sleep(0.01)
    await repo.append(session.id, LlmMessage.user("third"))

    rows = await repo.list_by_session(session.id)
    assert [row.content[0]["text"] for row in rows] == ["first", "second", "third"]


@pytest.mark.asyncio
async def test_list_by_session_empty(db_session: AsyncSession) -> None:
    session = await _make_session(db_session, "empty")
    repo = MessageRepo(db_session)
    rows = await repo.list_by_session(session.id)
    assert rows == []
