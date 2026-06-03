"""Auto compaction — compress old messages when session grows too large.

Mirrors claw-code's compact.rs: estimate token count, summarize old messages
(pure text extraction, no LLM call), preserve recent tail, handle tool_use/
tool_result pair boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass

from berry.core.llm.types import (
    ContentBlock,
    LlmMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)

_CONTINUATION_PREAMBLE = (
    "This session is being continued from a previous conversation that ran "
    "out of context. The summary below covers the earlier portion of the "
    "conversation.\n\n"
)
_RECENT_MESSAGES_NOTE = "Recent messages are preserved verbatim."
_DIRECT_RESUME_INSTRUCTION = (
    "Continue the conversation from where it left off without asking the user "
    "any further questions. Resume directly — do not acknowledge the summary, "
    "do not recap what was happening, and do not preface with continuation text."
)

DEFAULT_AUTO_COMPACTION_THRESHOLD = 100_000
DEFAULT_PRESERVE_RECENT_MESSAGES = 4


@dataclass
class CompactionConfig:
    preserve_recent_messages: int = DEFAULT_PRESERVE_RECENT_MESSAGES
    max_estimated_tokens: int = 10_000


@dataclass
class CompactionResult:
    summary: str
    compacted_messages: list[LlmMessage]
    removed_message_count: int


def estimate_message_tokens(message: LlmMessage) -> int:
    """Roughly estimate token count for a message. Uses len/4 + 1 per block."""
    total = 0
    for block in message.content:
        if isinstance(block, TextBlock):
            total += len(block.text) // 4 + 1
        elif isinstance(block, ToolUseBlock):
            raw = str(block.input)
            total += (len(block.name) + len(raw)) // 4 + 1
        elif isinstance(block, ToolResultBlock):
            total += len(block.output) // 4 + 1
        elif isinstance(block, ThinkingBlock):
            total += len(block.text) // 4 + 1
        else:
            total += 1
    return total


def estimate_session_tokens(messages: list[LlmMessage]) -> int:
    """Total estimated tokens across all messages."""
    return sum(estimate_message_tokens(m) for m in messages)


def should_compact(messages: list[LlmMessage], config: CompactionConfig) -> bool:
    """Check if the session exceeds compaction threshold."""
    start = _compacted_prefix_len(messages)
    compactable = messages[start:]

    if len(compactable) <= config.preserve_recent_messages:
        return False

    return (
        sum(estimate_message_tokens(m) for m in compactable)
        >= config.max_estimated_tokens
    )


def compact_session(
    messages: list[LlmMessage],
    config: CompactionConfig,
) -> CompactionResult:
    """Compact a message list by summarizing old messages, preserving recent tail.

    Returns a CompactionResult with the new message list. If no compaction
    is needed, returns the original messages unchanged.
    """
    if not should_compact(messages, config):
        return CompactionResult(
            summary="",
            compacted_messages=list(messages),
            removed_message_count=0,
        )

    existing_summary = _extract_existing_summary(messages)
    compacted_prefix_len = 1 if existing_summary is not None else 0

    # Determine boundary: preserve last N messages
    if config.preserve_recent_messages == 0:
        raw_keep_from = len(messages)
    else:
        raw_keep_from = max(0, len(messages) - config.preserve_recent_messages)

    # Don't split tool_use / tool_result pairs
    keep_from = _adjust_boundary_for_tool_pairs(messages, raw_keep_from, compacted_prefix_len)

    # Split into removed and preserved
    removed = messages[compacted_prefix_len:keep_from]
    preserved = messages[keep_from:]

    if not removed:
        return CompactionResult(
            summary="",
            compacted_messages=list(messages),
            removed_message_count=0,
        )

    # Build summary
    new_summary = _summarize_messages(removed)
    merged_summary = _merge_summaries(existing_summary, new_summary)
    continuation = _build_continuation_message(merged_summary, bool(preserved))

    # Build new message list
    compacted: list[LlmMessage] = [
        LlmMessage(role="user", content=[TextBlock(text=continuation)])
    ]
    compacted.extend(preserved)

    return CompactionResult(
        summary=merged_summary,
        compacted_messages=compacted,
        removed_message_count=len(removed),
    )


def _compacted_prefix_len(messages: list[LlmMessage]) -> int:
    """If first message is a prior compaction summary, return 1, else 0."""
    if _extract_existing_summary(messages) is not None:
        return 1
    return 0


def _extract_existing_summary(messages: list[LlmMessage]) -> str | None:
    """Check if the first message is a prior compaction continuation."""
    if not messages:
        return None
    first = messages[0]
    if not first.content:
        return None
    block = first.content[0]
    if not isinstance(block, TextBlock):
        return None
    text = block.text
    if not text.startswith(_CONTINUATION_PREAMBLE):
        return None
    # Extract the summary portion
    summary = text[len(_CONTINUATION_PREAMBLE):]
    # Strip trailing notes
    for marker in [f"\n\n{_RECENT_MESSAGES_NOTE}", f"\n{_DIRECT_RESUME_INSTRUCTION}"]:
        if marker in summary:
            summary = summary.split(marker)[0]
    return summary.strip()


def _adjust_boundary_for_tool_pairs(
    messages: list[LlmMessage],
    raw_keep_from: int,
    compacted_prefix_len: int,
) -> int:
    """Walk boundary back to avoid splitting tool_use / tool_result pairs."""
    k = raw_keep_from
    while k > compacted_prefix_len and k < len(messages):
        first_preserved = messages[k]
        # Check if first preserved message starts with a tool result
        if not first_preserved.content:
            break
        first_block = first_preserved.content[0]
        if not isinstance(first_block, ToolResultBlock):
            break
        # It's a tool result — check if preceding message has tool_use
        if k - 1 >= compacted_prefix_len:
            preceding = messages[k - 1]
            has_tool_use = any(isinstance(b, ToolUseBlock) for b in preceding.content)
            if has_tool_use:
                k -= 1
                break
        k -= 1
    return k


def _summarize_messages(messages: list[LlmMessage]) -> str:
    """Generate a structured summary of removed messages (no LLM call)."""
    user_count = sum(1 for m in messages if m.role == "user")
    assistant_count = sum(1 for m in messages if m.role == "assistant")

    # Collect tool names
    tool_names: set[str] = set()
    for msg in messages:
        for block in msg.content:
            if isinstance(block, ToolUseBlock):
                tool_names.add(block.name)
            elif isinstance(block, ToolResultBlock):
                # ToolResultBlock doesn't have tool_name, extract from id prefix
                pass

    # Recent user requests
    recent_user = []
    for msg in reversed(messages):
        if msg.role == "user" and len(recent_user) < 3:
            text = _first_text(msg)
            if text:
                recent_user.append(_truncate(text, 160))
    recent_user.reverse()

    # Build summary
    lines = [
        "<summary>",
        "Conversation summary:",
        f"- Scope: {len(messages)} earlier messages compacted "
        f"(user={user_count}, assistant={assistant_count}).",
    ]

    if tool_names:
        lines.append(f"- Tools mentioned: {', '.join(sorted(tool_names))}.")

    if recent_user:
        lines.append("- Recent user requests:")
        for req in recent_user:
            lines.append(f"  - {req}")

    # Key timeline (last 10 messages, truncated)
    lines.append("- Key timeline:")
    for msg in messages[-10:]:
        role = msg.role
        content_summary = _summarize_content(msg)
        lines.append(f"  - {role}: {content_summary}")

    lines.append("</summary>")
    return "\n".join(lines)


def _merge_summaries(existing: str | None, new: str) -> str:
    """Merge prior compaction summary with new summary. Flatten, don't nest."""
    if existing is None:
        return new
    # Combine: existing highlights + new summary
    lines = [
        "<summary>",
        "Conversation summary:",
        f"- Previously: {_truncate(existing, 300)}",
        "- Newly compacted:",
    ]
    # Indent new summary content (skip <summary> tags)
    for line in new.splitlines():
        if line.strip() in ("<summary>", "</summary>", "Conversation summary:"):
            continue
        lines.append(f"  {line}")
    lines.append("</summary>")
    return "\n".join(lines)


def _build_continuation_message(summary: str, has_preserved: bool) -> str:
    """Build the synthetic continuation message."""
    parts = [_CONTINUATION_PREAMBLE, _format_summary(summary)]
    if has_preserved:
        parts.append(f"\n\n{_RECENT_MESSAGES_NOTE}")
    parts.append(f"\n{_DIRECT_RESUME_INSTRUCTION}")
    return "".join(parts)


def _format_summary(summary: str) -> str:
    """Clean up summary for display: strip <analysis>, format <summary> tag."""
    # Strip <analysis> blocks
    result = summary
    while "<analysis>" in result and "</analysis>" in result:
        start = result.index("<analysis>")
        end = result.index("</analysis>") + len("</analysis>")
        result = result[:start] + result[end:]

    # Replace <summary>...</summary> with "Summary:\n..."
    if "<summary>" in result and "</summary>" in result:
        start = result.index("<summary>") + len("<summary>")
        end = result.index("</summary>")
        content = result[start:end].strip()
        result = f"Summary:\n{content}"

    return result.strip()


def _first_text(message: LlmMessage) -> str | None:
    """Extract first text content from a message."""
    for block in message.content:
        if isinstance(block, TextBlock) and block.text.strip():
            return block.text.strip()
    return None


def _summarize_content(message: LlmMessage) -> str:
    """One-line summary of a message's content blocks."""
    parts = []
    for block in message.content:
        if isinstance(block, TextBlock):
            parts.append(_truncate(block.text, 80))
        elif isinstance(block, ToolUseBlock):
            parts.append(f"tool_use {block.name}(...)")
        elif isinstance(block, ToolResultBlock):
            prefix = "error " if block.is_error else ""
            parts.append(f"tool_result: {prefix}{_truncate(block.output, 60)}")
        elif isinstance(block, ThinkingBlock):
            parts.append(f"thinking ({len(block.text)} chars)")
    return " | ".join(parts) if parts else "(empty)"


def _truncate(text: str, max_chars: int) -> str:
    """Truncate text, replacing newlines with spaces for summary."""
    clean = " ".join(text.split())
    if len(clean) <= max_chars:
        return clean
    return clean[:max_chars] + "…"
