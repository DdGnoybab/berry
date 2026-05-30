"""Tests for AgentEvent discriminated union."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from berry.core.agent.events import (
    AgentEvent,
    ApprovalAsked,
    TextDelta,
    ToolCallStart,
    ToolResult,
    TurnEnd,
    TurnStart,
)


def test_turn_start_serializes_with_type_field() -> None:
    sid = uuid4()
    ev = TurnStart(session_id=sid)
    dumped = ev.model_dump()
    assert dumped["type"] == "turn_start"
    assert dumped["session_id"] == sid


def test_text_delta_holds_text() -> None:
    ev = TextDelta(text="hello")
    assert ev.type == "text_delta"
    assert ev.text == "hello"


def test_tool_call_start_carries_args() -> None:
    ev = ToolCallStart(name="echo", id="abc", args={"x": 1})
    assert ev.name == "echo"
    assert ev.args == {"x": 1}


def test_approval_asked_default_not_error() -> None:
    ev = ApprovalAsked(name="write_md", id="t1", args={})
    assert ev.type == "approval_asked"


def test_tool_result_default_not_error() -> None:
    ev = ToolResult(id="t1", output="ok")
    assert ev.is_error is False


def test_turn_end_carries_stop_reason() -> None:
    ev = TurnEnd(stop_reason="end_turn")
    assert ev.stop_reason == "end_turn"


def test_agent_event_discriminator_parses_text_delta() -> None:
    """Discriminated union must dispatch on 'type'."""
    adapter = TypeAdapter(AgentEvent)
    parsed = adapter.validate_python({"type": "text_delta", "text": "hi"})
    assert isinstance(parsed, TextDelta)
    assert parsed.text == "hi"


def test_agent_event_rejects_unknown_type() -> None:
    adapter = TypeAdapter(AgentEvent)
    with pytest.raises(ValidationError):
        adapter.validate_python({"type": "unknown_event", "x": 1})


@pytest.mark.parametrize(
    "payload, expected_cls",
    [
        ({"type": "turn_start", "session_id": "00000000-0000-0000-0000-000000000001"}, TurnStart),
        ({"type": "text_delta", "text": "x"}, TextDelta),
        (
            {"type": "tool_call_start", "id": "t1", "name": "echo", "args": {}},
            ToolCallStart,
        ),
        (
            {"type": "approval_asked", "id": "t1", "name": "echo", "args": {}},
            ApprovalAsked,
        ),
        ({"type": "tool_result", "id": "t1", "output": "ok"}, ToolResult),
        ({"type": "turn_end", "stop_reason": "end_turn"}, TurnEnd),
    ],
)
def test_agent_event_discriminator_dispatches_all_variants(
    payload: dict, expected_cls: type
) -> None:
    adapter = TypeAdapter(AgentEvent)
    parsed = adapter.validate_python(payload)
    assert isinstance(parsed, expected_cls)
