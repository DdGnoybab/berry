"""AgentEvent — discriminated union of events emitted by ConversationRuntime.

Channels (cli / feishu) consume this stream to render to user.
Following the same shape as berry.core.llm.types.StreamEvent so a channel
can transparently forward LLM-layer events.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class TurnStart(BaseModel):
    """First event of every turn. Channels use it to open the rendering scope
    (e.g. feishu card header, CLI prompt) bound to this session_id.
    """

    type: Literal["turn_start"] = "turn_start"
    session_id: str


class TextDelta(BaseModel):
    """One streamed text chunk from the assistant message. Channels concatenate
    these to render incremental output. Mirrors llm.types.TextDelta — the
    agent layer typically forwards LLM TextDelta events unchanged.
    """

    type: Literal["text_delta"] = "text_delta"
    text: str


class ToolCallStart(BaseModel):
    """Tool call assembled from the LLM's streamed tool_use deltas, ready to dispatch.

    Distinct from llm.types.ToolCallStart (which is mid-stream, no args). The
    agent layer adds `args` once the streaming JSON delta is fully accumulated;
    `id` and `name` keep the same names as the LLM-layer event so channels and
    runtime can pass through without renaming.
    """

    type: Literal["tool_call_start"] = "tool_call_start"
    id: str                              # tool_use_id, same as llm.types
    name: str                            # tool name, same as llm.types
    args: dict[str, Any]


class ApprovalAsked(BaseModel):
    """Emitted when policy says the tool needs user approval before exec.

    Channel renders the approval UI (CLI Y/n; feishu card). Whether the user
    approved is signaled via ApprovalChannel.ask return value, not via a
    follow-up event.

    Field naming mirrors ToolCallStart so a channel can render this from the
    same fields it uses to render the actual call.
    """

    type: Literal["approval_asked"] = "approval_asked"
    id: str
    name: str
    args: dict[str, Any]


class ToolResult(BaseModel):
    """Result of a tool execution, paired with its originating ToolCallStart by `id`.

    is_error=True when the tool raised or the user denied approval — channel
    typically renders these in a different style. Note: this field name uses
    `id` rather than `tool_use_id` for consistency with the other agent events.
    """

    type: Literal["tool_result"] = "tool_result"
    id: str
    output: str
    is_error: bool = False


class TurnEnd(BaseModel):
    """Last event of every turn.

    `stop_reason` is bare `str` (not an enum) so the agent layer tolerates
    provider-specific values that the LLM-layer enumeration may not include
    yet. Common values are "end_turn", "max_tokens", "tool_use", "stop_sequence".
    """

    type: Literal["turn_end"] = "turn_end"
    stop_reason: str


AgentEvent = Annotated[
    TurnStart | TextDelta | ToolCallStart | ApprovalAsked | ToolResult | TurnEnd,
    Field(discriminator="type"),
]
