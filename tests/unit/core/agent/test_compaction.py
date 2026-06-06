"""Unit tests for four-layer compaction pipeline."""

from __future__ import annotations

from pathlib import Path

from berry.core.agent.compaction import (
    CompactionConfig,
    apply_compaction_pipeline,
    compact_history,
    estimate_tokens,
    micro_compact,
    reactive_compact,
    snip_compact,
    tool_result_budget,
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


# ─── estimate_tokens ─────────────────────────────────────────────────────


def test_estimate_text_block() -> None:
    msg = _user("hello world")
    tokens = estimate_tokens([msg])
    assert tokens == len("hello world") // 4 + 1


def test_estimate_tool_use_block() -> None:
    msg = _assistant_tool_use("id1", "bash")
    tokens = estimate_tokens([msg])
    assert tokens > 0


# ─── L1: snip_compact ────────────────────────────────────────────────────


def test_snip_no_op_when_under_limit() -> None:
    messages = [_user(f"msg {i}") for i in range(10)]
    result = snip_compact(messages, max_messages=50)
    assert len(result) == 10


def test_snip_cuts_middle() -> None:
    messages = [_user(f"msg {i}") for i in range(100)]
    result = snip_compact(messages, max_messages=20, keep_head=3)
    assert len(result) == 20
    # Head preserved
    assert result[0].content[0].text == "msg 0"
    assert result[1].content[0].text == "msg 1"
    assert result[2].content[0].text == "msg 2"
    # Placeholder in middle
    assert "snipped" in result[3].content[0].text
    # Tail preserved
    assert result[-1].content[0].text == "msg 99"


# ─── L2: micro_compact ───────────────────────────────────────────────────


def test_micro_no_op_when_few_results() -> None:
    messages = [
        _assistant_tool_use("t1", "bash"),
        _tool_result("t1", "output " * 100),
    ]
    result = micro_compact(messages, keep_recent=3)
    assert result == messages


def test_micro_compacts_old_results() -> None:
    messages = [
        _assistant_tool_use("t1", "bash"),
        _tool_result("t1", "old output " * 100),
        _assistant_tool_use("t2", "bash"),
        _tool_result("t2", "old output " * 100),
        _assistant_tool_use("t3", "bash"),
        _tool_result("t3", "recent output " * 100),
    ]
    result = micro_compact(messages, keep_recent=1)
    # First two tool results should be compacted
    old_result = result[1].content[0]
    assert old_result.output == "[Earlier tool result compacted. Re-run if needed.]"
    # Last tool result should be intact
    recent = result[5].content[0]
    assert "recent output" in recent.output


# ─── L3: tool_result_budget ──────────────────────────────────────────────


def test_budget_no_op_when_under_limit() -> None:
    messages = [_tool_result("t1", "small output")]
    result = tool_result_budget(messages, max_bytes=100_000)
    assert result == messages


def test_budget_persists_large_output(tmp_path: Path) -> None:
    large_output = "x" * 300_000
    messages = [_tool_result("t1", large_output)]
    result = tool_result_budget(messages, max_bytes=100_000, persist_dir=tmp_path)
    # Output should be replaced with preview + persist notice
    output = result[0].content[0].output
    assert "persisted" in output.lower() or "truncated" in output.lower()


# ─── L4: compact_history ─────────────────────────────────────────────────


def test_compact_preserves_recent_messages() -> None:
    messages = [_user(f"msg {i} " * 100) for i in range(10)]
    result = compact_history(messages, preserve_recent=3)
    assert result.removed_count > 0
    # First message is the continuation summary
    first = result.messages[0]
    assert "continued from a previous conversation" in first.content[0].text
    # Last 3 original messages are preserved
    assert len(result.messages) == 4  # 1 summary + 3 preserved


def test_compact_no_op_for_small_session() -> None:
    messages = [_user("hi"), _assistant("hello")]
    result = compact_history(messages, preserve_recent=4)
    assert result.removed_count == 0
    assert result.messages == messages


def test_compact_does_not_split_tool_pairs() -> None:
    """Tool use + tool result should not be split at the boundary."""
    messages = [
        _user("search for files " * 50),
        _assistant_tool_use("call_1", "grep_search"),
        _tool_result("call_1", "found 5 files " * 50),
        _assistant("here are the results " * 50),
    ]
    result = compact_history(messages, preserve_recent=1)

    for i in range(1, len(result.messages)):
        msg = result.messages[i]
        for block in msg.content:
            if isinstance(block, ToolResultBlock):
                prev = result.messages[i - 1]
                has_tool_use = any(isinstance(b, ToolUseBlock) for b in prev.content)
                assert has_tool_use, f"Orphaned ToolResult at index {i}"


# ─── reactive_compact ────────────────────────────────────────────────────


def test_reactive_compact_aggressive() -> None:
    messages = [_user(f"msg {i} " * 100) for i in range(20)]
    result = reactive_compact(messages, preserve_recent=3)
    assert len(result.messages) == 4  # 1 summary + 3 tail
    assert "Reactive compact" in result.messages[0].content[0].text


# ─── apply_compaction_pipeline ───────────────────────────────────────────


def test_pipeline_no_op_for_small_session() -> None:
    messages = [_user("hi"), _assistant("hello")]
    result, triggered_l4 = apply_compaction_pipeline(messages)
    assert not triggered_l4
    assert len(result) == 2


def test_pipeline_runs_l1_snip() -> None:
    messages = [_user(f"msg {i} " * 10) for i in range(100)]
    config = CompactionConfig(max_messages=20, auto_compact_threshold=999_999)
    result, _ = apply_compaction_pipeline(messages, config)
    assert len(result) == 20
