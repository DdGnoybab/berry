"""StreamAccumulator — assemble a streaming LLM response into a complete LlmResponse.

The LLM gateway emits a sequence of small StreamEvents
(MessageStart, TextDelta, ToolCallStart, ToolCallDelta, MessageStop, UsageEvent).
ConversationRuntime needs the complete `LlmResponse` (with full content blocks
and usage) at the end of a turn — both to push it onto the AgentSession history
and to write a single LlmCallLog row.

This class consumes the stream event-by-event and exposes `build_response()`
once the stream has ended.
"""

from __future__ import annotations

import json

from berry.core.llm.enums import StopReason
from berry.core.llm.errors import LlmStreamError
from berry.core.llm.types import (
    ContentBlock,
    LlmResponse,
    MessageStart,
    MessageStop,
    StreamError,
    StreamEvent,
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
from berry.utils.unicode import strip_surrogates as _strip_surrogates


class StreamAccumulator:
    """Reassembles a streaming response into a single LlmResponse.

    Usage:
        acc = StreamAccumulator(model_id="main")
        async for ev in gateway.stream(...):
            acc.feed(ev)
        response = acc.build_response()
    """

    def __init__(self, model_id: str) -> None:
        # Final model id (logical, the registry id we routed by). Falls back to
        # whatever MessageStart says, which the providers also set to the logical id.
        self._model_id = model_id

        # Accumulators for each block type. Tool calls keep partial input JSON
        # text until ToolCallDelta stream finishes; we json.loads at the end.
        self._text_buf: list[str] = []
        self._thinking_buf: list[str] = []
        self._tool_calls: dict[str, _ToolCallBuilder] = {}
        self._tool_call_order: list[str] = []  # preserve emission order

        self._message_id: str | None = None
        self._stop_reason: StopReason | None = None
        self._usage = Usage()
        self._stream_error: StreamError | None = None

    def feed(self, event: StreamEvent) -> None:
        """Consume one stream event.

        All inbound text is run through :func:`_strip_surrogates` so lone
        surrogate halves (which leak in when an upstream SSE chunk splits a
        multi-byte emoji) never propagate into in-memory message history.
        Without this, the next turn's request body encoding would raise
        UnicodeEncodeError and lose the entire turn.
        """
        if isinstance(event, MessageStart):
            self._message_id = event.id
        elif isinstance(event, TextDelta):
            self._text_buf.append(_strip_surrogates(event.text))
        elif isinstance(event, ThinkingDelta):
            self._thinking_buf.append(_strip_surrogates(event.text))
        elif isinstance(event, ToolCallStart):
            self._tool_calls[event.id] = _ToolCallBuilder(id=event.id, name=event.name)
            self._tool_call_order.append(event.id)
        elif isinstance(event, ToolCallDelta):
            if event.id not in self._tool_calls:
                # Provider sent a delta for a tool we never saw start. Skip silently;
                # a downstream `build_response()` will fail at JSON parse time anyway.
                return
            self._tool_calls[event.id].input_json.append(
                _strip_surrogates(event.input_json_delta)
            )
        elif isinstance(event, MessageStop):
            self._stop_reason = event.stop_reason
        elif isinstance(event, UsageEvent):
            self._usage = event.usage
        elif isinstance(event, StreamError):
            self._stream_error = event
        # Other event types ignored.

    def build_response(self) -> LlmResponse:
        """Materialize the LlmResponse. Raises if the stream ended mid-flight."""
        if self._stream_error is not None:
            raise LlmStreamError(
                f"stream errored: {self._stream_error.error_type}: "
                f"{self._stream_error.message}"
            )
        if self._stop_reason is None:
            raise LlmStreamError(
                "stream ended without MessageStop (stop_reason missing)"
            )

        content: list[ContentBlock] = []

        # Convention: thinking blocks come first if present (Anthropic order),
        # then text, then tool_use blocks in the order they started.
        if self._thinking_buf:
            content.append(ThinkingBlock(text="".join(self._thinking_buf)))
        if self._text_buf:
            content.append(TextBlock(text="".join(self._text_buf)))
        for tool_id in self._tool_call_order:
            content.append(self._tool_calls[tool_id].build())

        return LlmResponse(
            id=self._message_id or "",
            model=self._model_id,
            content=content,
            stop_reason=self._stop_reason,
            usage=self._usage,
        )


class _ToolCallBuilder:
    """Buffer for a single tool_use block being streamed in."""

    __slots__ = ("id", "input_json", "name")

    def __init__(self, id: str, name: str) -> None:
        self.id = id
        self.name = name
        self.input_json: list[str] = []

    def build(self) -> ToolUseBlock:
        raw = "".join(self.input_json)
        # Empty args is valid (no-arg tools): Anthropic sometimes emits no deltas.
        if not raw.strip():
            input_value: dict[str, object] = {}
        else:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                # The model produced malformed JSON (e.g. unescaped quotes
                # in a string field). Don't kill the turn — surface the
                # parse failure as a structured input that runtime turns
                # into a tool_result(is_error=True). The LLM almost always
                # retries cleanly when it sees the error in the next round.
                input_value = {
                    "_berry_parse_error": (
                        f"Your tool_use input was not valid JSON. "
                        f"Reason: {exc.msg} at line {exc.lineno} col {exc.colno}. "
                        f"Common cause: an unescaped double-quote inside a "
                        f"string field. Escape internal quotes as \\\" or "
                        f"reword to avoid them, then call the tool again. "
                        f"Raw input received: {raw!r}"
                    )
                }
                return ToolUseBlock(id=self.id, name=self.name, input=input_value)
            if not isinstance(parsed, dict):
                input_value = {
                    "_berry_parse_error": (
                        f"Your tool_use input must be a JSON object "
                        f"(got {type(parsed).__name__}). Retry with an object."
                    )
                }
                return ToolUseBlock(id=self.id, name=self.name, input=input_value)
            input_value = parsed
        return ToolUseBlock(id=self.id, name=self.name, input=input_value)
