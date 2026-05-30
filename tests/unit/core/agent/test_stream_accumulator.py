"""Tests for StreamAccumulator."""

from __future__ import annotations

import pytest

from berry.core.agent.stream_accumulator import StreamAccumulator
from berry.core.llm.enums import StopReason
from berry.core.llm.errors import LlmStreamError
from berry.core.llm.types import (
    MessageStart,
    MessageStop,
    StreamError,
    TextBlock,
    TextDelta,
    ThinkingBlock,
    ThinkingDelta,
    ToolCallDelta,
    ToolCallStart,
    ToolUseBlock,
    Usage,
    UsageEvent,
)


def test_text_only_stream_builds_text_block() -> None:
    acc = StreamAccumulator(model_id="main")
    acc.feed(MessageStart(id="msg_1", model="main"))
    acc.feed(TextDelta(text="hel"))
    acc.feed(TextDelta(text="lo"))
    acc.feed(MessageStop(stop_reason=StopReason.END_TURN))
    acc.feed(UsageEvent(usage=Usage(input_tokens=10, output_tokens=2)))

    resp = acc.build_response()
    assert resp.id == "msg_1"
    assert resp.model == "main"
    assert resp.stop_reason == StopReason.END_TURN
    assert len(resp.content) == 1
    assert isinstance(resp.content[0], TextBlock)
    assert resp.content[0].text == "hello"
    assert resp.usage.input_tokens == 10
    assert resp.usage.output_tokens == 2


def test_tool_call_stream_assembles_input_json() -> None:
    acc = StreamAccumulator(model_id="main")
    acc.feed(MessageStart(id="msg_2", model="main"))
    acc.feed(TextDelta(text="let me call a tool"))
    acc.feed(ToolCallStart(id="t1", name="echo_tool"))
    acc.feed(ToolCallDelta(id="t1", input_json_delta='{"text"'))
    acc.feed(ToolCallDelta(id="t1", input_json_delta=':"hi"}'))
    acc.feed(MessageStop(stop_reason=StopReason.TOOL_USE))
    acc.feed(UsageEvent(usage=Usage(input_tokens=15, output_tokens=8)))

    resp = acc.build_response()
    # Expect text block then tool_use block
    assert len(resp.content) == 2
    assert isinstance(resp.content[0], TextBlock)
    assert isinstance(resp.content[1], ToolUseBlock)
    assert resp.content[1].id == "t1"
    assert resp.content[1].name == "echo_tool"
    assert resp.content[1].input == {"text": "hi"}


def test_multiple_tool_calls_preserve_order() -> None:
    acc = StreamAccumulator(model_id="main")
    acc.feed(MessageStart(id="msg_3", model="main"))
    acc.feed(ToolCallStart(id="t1", name="first"))
    acc.feed(ToolCallDelta(id="t1", input_json_delta="{}"))
    acc.feed(ToolCallStart(id="t2", name="second"))
    acc.feed(ToolCallDelta(id="t2", input_json_delta="{}"))
    acc.feed(MessageStop(stop_reason=StopReason.TOOL_USE))

    resp = acc.build_response()
    tool_blocks = [b for b in resp.content if isinstance(b, ToolUseBlock)]
    assert [b.name for b in tool_blocks] == ["first", "second"]


def test_tool_call_with_no_input_deltas_yields_empty_args() -> None:
    """Some providers emit no ToolCallDelta when the tool takes no arguments.
    Empty args must parse as an empty dict, not raise.
    """
    acc = StreamAccumulator(model_id="main")
    acc.feed(MessageStart(id="msg_4", model="main"))
    acc.feed(ToolCallStart(id="t1", name="noop"))
    acc.feed(MessageStop(stop_reason=StopReason.TOOL_USE))

    resp = acc.build_response()
    assert isinstance(resp.content[0], ToolUseBlock)
    assert resp.content[0].input == {}


def test_thinking_block_appears_before_text() -> None:
    acc = StreamAccumulator(model_id="main")
    acc.feed(MessageStart(id="msg_5", model="main"))
    acc.feed(ThinkingDelta(text="hmm "))
    acc.feed(ThinkingDelta(text="thinking..."))
    acc.feed(TextDelta(text="answer"))
    acc.feed(MessageStop(stop_reason=StopReason.END_TURN))

    resp = acc.build_response()
    assert len(resp.content) == 2
    assert isinstance(resp.content[0], ThinkingBlock)
    assert resp.content[0].text == "hmm thinking..."
    assert isinstance(resp.content[1], TextBlock)
    assert resp.content[1].text == "answer"


def test_build_without_message_stop_raises() -> None:
    acc = StreamAccumulator(model_id="main")
    acc.feed(MessageStart(id="msg_6", model="main"))
    acc.feed(TextDelta(text="hi"))
    # No MessageStop fed
    with pytest.raises(LlmStreamError, match="MessageStop"):
        acc.build_response()


def test_stream_error_event_propagates() -> None:
    acc = StreamAccumulator(model_id="main")
    acc.feed(MessageStart(id="msg_7", model="main"))
    acc.feed(StreamError(message="rate limited", error_type="RateLimit"))
    with pytest.raises(LlmStreamError, match="rate limited"):
        acc.build_response()


def test_invalid_tool_call_json_raises() -> None:
    acc = StreamAccumulator(model_id="main")
    acc.feed(MessageStart(id="msg_8", model="main"))
    acc.feed(ToolCallStart(id="t1", name="echo"))
    acc.feed(ToolCallDelta(id="t1", input_json_delta="not json at all"))
    acc.feed(MessageStop(stop_reason=StopReason.TOOL_USE))
    with pytest.raises(LlmStreamError, match="not valid JSON"):
        acc.build_response()


def test_orphan_tool_call_delta_silently_dropped() -> None:
    """If a ToolCallDelta arrives without a matching ToolCallStart, ignore it.
    This makes the accumulator tolerant of provider quirks (we'll catch the
    real problem when the response can't be assembled).
    """
    acc = StreamAccumulator(model_id="main")
    acc.feed(MessageStart(id="msg_9", model="main"))
    acc.feed(ToolCallDelta(id="ghost", input_json_delta='{"x":1}'))
    acc.feed(TextDelta(text="hi"))
    acc.feed(MessageStop(stop_reason=StopReason.END_TURN))

    resp = acc.build_response()
    # Only the text block survived.
    assert len(resp.content) == 1
    assert isinstance(resp.content[0], TextBlock)


def test_empty_text_buffer_excluded_from_content() -> None:
    """A stream with only a tool_use call (no text) should not get an empty TextBlock."""
    acc = StreamAccumulator(model_id="main")
    acc.feed(MessageStart(id="msg_10", model="main"))
    acc.feed(ToolCallStart(id="t1", name="echo"))
    acc.feed(ToolCallDelta(id="t1", input_json_delta='{"text":"x"}'))
    acc.feed(MessageStop(stop_reason=StopReason.TOOL_USE))

    resp = acc.build_response()
    assert len(resp.content) == 1
    assert isinstance(resp.content[0], ToolUseBlock)
