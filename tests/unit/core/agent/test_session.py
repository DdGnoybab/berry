"""Unit tests for AgentSession (no DB)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from berry.core.agent.session import AgentSession
from berry.core.llm.types import LlmMessage, TextBlock
from berry.domain.enums import Channel, SessionStatus


def _make_session(**overrides) -> AgentSession:
    now = datetime.now(UTC)
    defaults = {
        "id": "test-session-id",
        "user_id": uuid4(),
        "channel": Channel.FEISHU,
        "chat_id": "chat_test",
        "status": SessionStatus.ACTIVE,
        "title": None,
        "messages": [],
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return AgentSession(**defaults)


def test_default_messages_is_empty_list() -> None:
    s = _make_session()
    assert s.messages == []


def test_push_user_text_appends_and_returns_message() -> None:
    s = _make_session()
    msg = s.push_user_text("hello")
    assert len(s.messages) == 1
    assert s.messages[0] is msg
    assert msg.role == "user"
    assert msg.content == [TextBlock(text="hello")]


def test_push_message_appends_arbitrary_message() -> None:
    s = _make_session()
    msg = LlmMessage.assistant("done")
    s.push_message(msg)
    assert s.messages == [msg]


def test_push_does_not_share_default_list_across_instances() -> None:
    """Regression: ensure default_factory isn't producing a shared list."""
    a = _make_session()
    b = _make_session()
    a.push_user_text("a")
    assert b.messages == []
