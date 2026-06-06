"""Tests for the runtime's last-chance tool-pairing sanitize."""

from __future__ import annotations

from berry.core.agent.runtime import _strip_unpaired_tool_blocks
from berry.core.llm.types import LlmMessage, TextBlock, ToolResultBlock, ToolUseBlock


def test_passes_well_formed_messages_through() -> None:
    msgs = [
        LlmMessage(role="user", content=[TextBlock(text="hi")]),
        LlmMessage(
            role="assistant",
            content=[
                TextBlock(text="checking"),
                ToolUseBlock(id="tu_1", name="bash", input={"cmd": "ls"}),
            ],
        ),
        LlmMessage(
            role="user",
            content=[ToolResultBlock(tool_use_id="tu_1", output="ok")],
        ),
    ]
    out = _strip_unpaired_tool_blocks(msgs)
    assert len(out) == 3
    # Same content, identity-preserved or at least equal
    assert out[1].content[1].id == "tu_1"  # type: ignore[union-attr]


def test_drops_orphan_tool_result_no_matching_use() -> None:
    msgs = [
        LlmMessage(role="user", content=[TextBlock(text="hi")]),
        LlmMessage(
            role="user",
            content=[ToolResultBlock(tool_use_id="tu_ghost", output="x")],
        ),
        LlmMessage(role="assistant", content=[TextBlock(text="resp")]),
    ]
    out = _strip_unpaired_tool_blocks(msgs)
    # The orphan tool_result is dropped; its message becomes empty and is also dropped.
    assert len(out) == 2
    assert out[0].content[0].text == "hi"  # type: ignore[union-attr]
    assert out[1].content[0].text == "resp"  # type: ignore[union-attr]


def test_drops_dangling_tool_use_with_no_result() -> None:
    msgs = [
        LlmMessage(
            role="assistant",
            content=[
                TextBlock(text="check"),
                ToolUseBlock(id="tu_1", name="bash", input={"cmd": "ls"}),
            ],
        ),
        LlmMessage(role="user", content=[TextBlock(text="next")]),
    ]
    out = _strip_unpaired_tool_blocks(msgs)
    # tu_1 had no tool_result anywhere → dangling → stripped from blocks.
    # The assistant message's text block survives.
    assert len(out) == 2
    assert len(out[0].content) == 1
    assert isinstance(out[0].content[0], TextBlock)
    assert out[0].content[0].text == "check"


def test_drops_assistant_message_that_becomes_empty_after_strip() -> None:
    msgs = [
        LlmMessage(
            role="assistant",
            content=[ToolUseBlock(id="tu_1", name="bash", input={})],
        ),
        LlmMessage(role="user", content=[TextBlock(text="hi")]),
    ]
    out = _strip_unpaired_tool_blocks(msgs)
    # tu_1 is dangling, message is left empty → dropped
    assert len(out) == 1
    assert out[0].content[0].text == "hi"  # type: ignore[union-attr]


def test_strips_both_orphan_result_and_dangling_use() -> None:
    msgs = [
        LlmMessage(
            role="assistant",
            content=[ToolUseBlock(id="tu_dangling", name="bash", input={})],
        ),
        LlmMessage(
            role="user",
            content=[ToolResultBlock(tool_use_id="tu_ghost", output="x")],
        ),
        LlmMessage(role="user", content=[TextBlock(text="hello")]),
    ]
    out = _strip_unpaired_tool_blocks(msgs)
    # Both orphan blocks gone, both messages dropped
    assert len(out) == 1
    assert out[0].content[0].text == "hello"  # type: ignore[union-attr]


def test_paired_tool_use_and_result_with_distance_in_between() -> None:
    """A common shape: assistant text → assistant tool_use → user tool_result."""
    msgs = [
        LlmMessage(role="user", content=[TextBlock(text="run ls")]),
        LlmMessage(
            role="assistant",
            content=[
                TextBlock(text="ok, running"),
                ToolUseBlock(id="tu_X", name="bash", input={"cmd": "ls"}),
            ],
        ),
        LlmMessage(
            role="user",
            content=[ToolResultBlock(tool_use_id="tu_X", output="files")],
        ),
        LlmMessage(role="assistant", content=[TextBlock(text="done")]),
    ]
    out = _strip_unpaired_tool_blocks(msgs)
    assert len(out) == 4
    # No mutations applied since everything is paired
    assert msgs == out


def test_empty_input_returns_empty() -> None:
    assert _strip_unpaired_tool_blocks([]) == []
