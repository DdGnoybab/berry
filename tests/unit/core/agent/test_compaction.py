"""Unit tests for auto compaction."""

from __future__ import annotations

from berry.core.agent.compaction import (
    CompactionConfig,
    compact_session,
    estimate_message_tokens,
    estimate_session_tokens,
    should_compact,
)
from berry.core.llm.types import LlmMessage, TextBlock, ToolResultBlock, ToolUseBlock


def _user(text: str) -> LlmMessage:
    return LlmMessage(role="user", content=[TextBlock(text=text)])


def _assistant(text: str) -> LlmMessage:
    return LlmMessage(role="assistant", content=[TextBlock(text=text)])


def _assistant_tool_use(tool_id: str, name: str) -> LlmMessage:
    return LlmMessage(
        role="assistant",
        content=[ToolUseBlock(id=tool_id, name=name, input={"q": "test"})],
    )


def _tool_result(tool_id: str, output: str) -> LlmMessage:
    return LlmMessage(
        role="user",
        content=[ToolResultBlock(tool_use_id=tool_id, output=output, is_error=False)],
    )


# ─── estimate_message_tokens ─────────────────────────────────────────────


def test_estimate_text_block() -> None:
    msg = _user("hello world")
    tokens = estimate_message_tokens(msg)
    assert tokens == len("hello world") // 4 + 1


def test_estimate_tool_use_block() -> None:
    msg = _assistant_tool_use("id1", "bash")
    tokens = estimate_message_tokens(msg)
    assert tokens > 0


def test_estimate_session_sums_all() -> None:
    messages = [_user("a" * 100), _assistant("b" * 200)]
    total = estimate_session_tokens(messages)
    assert total == estimate_message_tokens(messages[0]) + estimate_message_tokens(messages[1])


# ─── should_compact ──────────────────────────────────────────────────────


def test_small_session_does_not_compact() -> None:
    messages = [_user("hi"), _assistant("hello")]
    assert not should_compact(messages, CompactionConfig())


def test_large_session_should_compact() -> None:
    messages = [_user("x" * 5000) for _ in range(10)]
    messages.extend([_assistant("y" * 5000) for _ in range(10)])
    config = CompactionConfig(preserve_recent_messages=4, max_estimated_tokens=1000)
    assert should_compact(messages, config)


def test_does_not_compact_if_only_preserve_count_messages() -> None:
    messages = [_user("x" * 5000) for _ in range(3)]
    config = CompactionConfig(preserve_recent_messages=4, max_estimated_tokens=1)
    assert not should_compact(messages, config)


# ─── compact_session ─────────────────────────────────────────────────────


def test_compact_preserves_recent_messages() -> None:
    messages = [_user(f"msg {i} " * 100) for i in range(10)]
    config = CompactionConfig(preserve_recent_messages=3, max_estimated_tokens=1)

    result = compact_session(messages, config)

    assert result.removed_message_count > 0
    # First message is the continuation summary
    first = result.compacted_messages[0]
    assert first.content[0].text.startswith("This session is being continued")
    # Last 3 original messages are preserved
    assert len(result.compacted_messages) == 4  # 1 summary + 3 preserved


def test_compact_no_op_for_small_session() -> None:
    messages = [_user("hi"), _assistant("hello")]
    config = CompactionConfig(preserve_recent_messages=4, max_estimated_tokens=100_000)

    result = compact_session(messages, config)

    assert result.removed_message_count == 0
    assert result.compacted_messages == messages


def test_compact_does_not_split_tool_pairs() -> None:
    """Tool use + tool result should not be split at the boundary."""
    messages = [
        _user("search for files " * 50),
        _assistant_tool_use("call_1", "grep_search"),
        _tool_result("call_1", "found 5 files " * 50),
        _assistant("here are the results " * 50),
    ]
    config = CompactionConfig(preserve_recent_messages=1, max_estimated_tokens=1)

    result = compact_session(messages, config)

    # Verify no orphaned tool_result without preceding tool_use
    for i in range(1, len(result.compacted_messages)):
        msg = result.compacted_messages[i]
        for block in msg.content:
            if isinstance(block, ToolResultBlock):
                # Preceding message must have a ToolUseBlock
                prev = result.compacted_messages[i - 1]
                has_tool_use = any(isinstance(b, ToolUseBlock) for b in prev.content)
                assert has_tool_use, (
                    f"Orphaned ToolResult at index {i} without preceding ToolUse"
                )


def test_compact_summary_contains_scope() -> None:
    messages = [_user(f"question {i} " * 100) for i in range(8)]
    config = CompactionConfig(preserve_recent_messages=2, max_estimated_tokens=1)

    result = compact_session(messages, config)

    assert "Scope:" in result.summary
    assert "earlier messages compacted" in result.summary


def test_compact_repeated_compaction_merges_summaries() -> None:
    """Second compaction should merge with first, not nest."""
    messages = [_user(f"round1 msg {i} " * 100) for i in range(8)]
    config = CompactionConfig(preserve_recent_messages=2, max_estimated_tokens=1)

    # First compaction
    first = compact_session(messages, config)

    # Add more messages
    extended = list(first.compacted_messages)
    extended.extend([_user(f"round2 msg {i} " * 100) for i in range(6)])

    # Second compaction
    second = compact_session(extended, config)

    assert second.removed_message_count > 0
    # Summary should reference prior compaction
    assert "Previously" in second.summary or "Newly compacted" in second.summary
