"""Integration tests for the AgentSession <-> DB persistence layer."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from berry.core.agent.persistence import load_agent_session, save_message
from berry.core.db.repos.session_repo import SessionRepo
from berry.core.db.repos.user_repo import UserRepo
from berry.core.llm.types import (
    LlmMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from berry.domain.enums import Channel, SessionStatus


async def _bootstrap_session(db_session: AsyncSession, suffix: str):
    user = await UserRepo(db_session).create_or_get_by_external(
        external_source="feishu",
        external_id=f"ou_persist_{suffix}",
        display_name=f"Persist {suffix}",
    )
    return await SessionRepo(db_session).get_or_create(
        user_id=user.id, channel=Channel.FEISHU, chat_id=f"chat_persist_{suffix}",
    )


@pytest.mark.asyncio
async def test_load_returns_none_when_session_missing(
    db_session: AsyncSession,
) -> None:
    result = await load_agent_session(uuid4(), db_session)
    assert result is None


@pytest.mark.asyncio
async def test_load_empty_session_has_no_messages(
    db_session: AsyncSession,
) -> None:
    row = await _bootstrap_session(db_session, "empty")
    agent_session = await load_agent_session(row.id, db_session)
    assert agent_session is not None
    assert agent_session.id == row.id
    assert agent_session.user_id == row.user_id
    assert agent_session.channel == Channel.FEISHU
    assert agent_session.status == SessionStatus.ACTIVE
    assert agent_session.messages == []


@pytest.mark.asyncio
async def test_save_and_load_round_trip_user_text(
    db_session: AsyncSession,
) -> None:
    row = await _bootstrap_session(db_session, "rt_user")
    msg = LlmMessage.user("hello world")
    await save_message(row.id, msg, db_session)

    loaded = await load_agent_session(row.id, db_session)
    assert loaded is not None
    assert len(loaded.messages) == 1
    assert loaded.messages[0].role == "user"
    assert loaded.messages[0].content == [TextBlock(text="hello world")]


@pytest.mark.asyncio
async def test_save_and_load_round_trip_complex_assistant(
    db_session: AsyncSession,
) -> None:
    """Multi-block assistant message round-trips with all block types intact."""
    row = await _bootstrap_session(db_session, "rt_complex")
    asst = LlmMessage(
        role="assistant",
        content=[
            ThinkingBlock(text="user wants to find TODOs"),
            TextBlock(text="OK, I'll grep."),
            ToolUseBlock(id="toolu_a", name="grep", input={"pattern": "TODO"}),
        ],
    )
    await save_message(row.id, asst, db_session)

    loaded = await load_agent_session(row.id, db_session)
    assert loaded is not None
    assert len(loaded.messages) == 1
    blocks = loaded.messages[0].content
    assert len(blocks) == 3
    assert isinstance(blocks[0], ThinkingBlock)
    assert blocks[0].text == "user wants to find TODOs"
    assert isinstance(blocks[1], TextBlock)
    assert isinstance(blocks[2], ToolUseBlock)
    assert blocks[2].name == "grep"
    assert blocks[2].input == {"pattern": "TODO"}


@pytest.mark.asyncio
async def test_save_and_load_round_trip_tool_result(
    db_session: AsyncSession,
) -> None:
    """tool_result lives inside a user-role message; structure must survive."""
    row = await _bootstrap_session(db_session, "rt_toolresult")
    res = LlmMessage(
        role="user",
        content=[
            ToolResultBlock(
                tool_use_id="toolu_a", output="found 3 TODOs", is_error=False,
            ),
        ],
    )
    await save_message(row.id, res, db_session)

    loaded = await load_agent_session(row.id, db_session)
    assert loaded is not None
    assert isinstance(loaded.messages[0].content[0], ToolResultBlock)
    assert loaded.messages[0].content[0].tool_use_id == "toolu_a"
    assert loaded.messages[0].content[0].output == "found 3 TODOs"
    assert loaded.messages[0].content[0].is_error is False


@pytest.mark.asyncio
async def test_load_preserves_message_order(db_session: AsyncSession) -> None:
    row = await _bootstrap_session(db_session, "rt_order")
    await save_message(row.id, LlmMessage.user("first"), db_session)
    await asyncio.sleep(0.01)
    await save_message(row.id, LlmMessage.assistant("second"), db_session)
    await asyncio.sleep(0.01)
    await save_message(row.id, LlmMessage.user("third"), db_session)

    loaded = await load_agent_session(row.id, db_session)
    assert loaded is not None
    texts = [m.content[0].text for m in loaded.messages]
    assert texts == ["first", "second", "third"]
