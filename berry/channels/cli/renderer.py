"""AgentEvent → terminal output.

Plain stream (no rich library, no ANSI repaint). LLM text streams
character-by-character; structural events get a ``[label]`` line so a
debugger can tell tool calls apart from prose at a glance.

This module deliberately keeps zero dependencies on any specific channel
state — pass an event in, get bytes on stdout. Round 5 (feishu) replaces
this entirely with a card-based renderer.
"""

from __future__ import annotations

import json

from berry.core.agent.events import (
    AgentEvent,
    ApprovalAsked,
    TextDelta,
    ToolCallStart,
    ToolResult,
    TurnEnd,
    TurnStart,
)


def _safe(text: str) -> str:
    """Strip lone surrogate halves so terminal write never raises
    UnicodeEncodeError. Surrogates can leak in when an upstream SSE chunk
    splits a multi-byte emoji at the wrong byte boundary."""
    return text.encode("utf-8", errors="replace").decode("utf-8")


def render(event: AgentEvent) -> None:
    """Print one event to stdout in the agreed CLI format."""
    if isinstance(event, TextDelta):
        # Token stream — no newline, flush so the user sees it live.
        print(_safe(event.text), end="", flush=True)
        return

    if isinstance(event, ToolCallStart):
        # New line first so it doesn't tail an in-progress text stream.
        args_repr = _compact_json(event.args)
        print(_safe(f"\n[tool_call] {event.name}({args_repr})"), flush=True)
        return

    if isinstance(event, ApprovalAsked):
        # The CLI ApprovalChannel handles the actual prompt. We don't print
        # anything here; double-printing would stutter "[approval] ... [approval] ...".
        return

    if isinstance(event, ToolResult):
        label = "[tool_result-error]" if event.is_error else "[tool_result]"
        # Truncate very long outputs so the terminal stays scannable.
        body = event.output if len(event.output) <= 500 else event.output[:497] + "..."
        print(_safe(f"{label} {body}"), flush=True)
        return

    if isinstance(event, TurnEnd):
        # Newline so the next prompt starts on a fresh line.
        print()
        return

    if isinstance(event, TurnStart):
        # Silent — nothing useful to show the user at turn start.
        return


def _compact_json(value: dict[str, object]) -> str:
    """One-line JSON; mostly for readability of small tool args. Falls back
    to repr() if the value isn't JSON-serializable (defensive — should not
    happen in normal flow).
    """
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return repr(value)
