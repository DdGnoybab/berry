"""Anthropic Messages 协议 adapter。

覆盖范围:
- Anthropic 官方
- DeepSeek `/anthropic` 端点(Anthropic 兼容)
- 任何走 Anthropic Messages 协议的端点(改 base_url + key 即可)

Batch 2 范围:
- 文本 invoke / stream
- thinking 块(Anthropic 原生)
- tool_use / tool_result 来回
- 错误映射
"""

import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import anthropic
from anthropic import AsyncAnthropic

from berry.core.llm.config import ModelEntry
from berry.core.llm.enums import KnownApi, StopReason
from berry.observability.logging import get_logger
from berry.observability.wire_logging import cap_payload, dump_sdk_object
from berry.utils.unicode import strip_surrogates_deep as _strip_surrogates_deep
from berry.core.llm.errors import (
    LlmAuthError,
    LlmInvalidRequestError,
    LlmRateLimitError,
    LlmServerError,
    LlmStreamError,
    LlmTimeoutError,
)

_logger = get_logger(__name__)
from berry.core.llm.types import (
    ContentBlock,
    LlmMessage,
    LlmRequest,
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
    ToolResultBlock,
    ToolUseBlock,
    Usage,
    UsageEvent,
)


class AnthropicMessagesAdapter:
    """Anthropic Messages 协议实现。"""

    api = KnownApi.ANTHROPIC_MESSAGES.value

    def __init__(self) -> None:
        # 按 base_url + key 缓存 client
        self._clients: dict[str, AsyncAnthropic] = {}

    def _get_client(self, entry: ModelEntry) -> AsyncAnthropic:
        cache_key = f"{entry.base_url}|{entry.api_key[:8]}"
        if cache_key not in self._clients:
            self._clients[cache_key] = AsyncAnthropic(
                api_key=entry.api_key,
                base_url=entry.base_url,
                timeout=entry.timeout_s,
            )
        return self._clients[cache_key]

    # ─── 中立 → Anthropic ───
    @staticmethod
    def _to_anthropic_messages(
        messages: list[LlmMessage],
    ) -> list[dict[str, Any]]:
        """中立 messages → Anthropic messages。

        Anthropic 协议特点:
        - system 走顶层字段(不在 messages)
        - 内容块跟我们中立类型几乎 1:1(结构最接近)
        - tool_use 在 assistant 消息;tool_result 在 user 消息
        """
        out: list[dict[str, Any]] = []
        for msg in messages:
            blocks: list[dict[str, Any]] = []
            for b in msg.content:
                if isinstance(b, TextBlock):
                    blocks.append({"type": "text", "text": b.text})
                elif isinstance(b, ThinkingBlock):
                    # Anthropic API 接收的 thinking 块需要 signature 字段,
                    # 但是 history 中通常用不到(Anthropic 自己输出后,
                    # 下一轮我们重发不需要 thinking)。MVP 直接转成 text 注释。
                    # 严格按 Anthropic 协议要求时再补(需要 signature 字段)
                    pass
                elif isinstance(b, ToolUseBlock):
                    blocks.append({
                        "type": "tool_use",
                        "id": b.id,
                        "name": b.name,
                        "input": b.input,
                    })
                elif isinstance(b, ToolResultBlock):
                    blocks.append({
                        "type": "tool_result",
                        "tool_use_id": b.tool_use_id,
                        "content": b.output,
                        "is_error": b.is_error,
                    })

            # CRITICAL: don't silently drop messages whose blocks were all
            # filtered out (e.g. an assistant message that only contained a
            # ThinkingBlock). Dropping shifts subsequent message indices and
            # breaks tool_use ↔ tool_result pairing — Anthropic then rejects
            # the request with `tool_result has no matching tool_use`.
            # Insert a non-empty placeholder so the message position is
            # preserved (Anthropic also rejects empty-text blocks).
            if not blocks:
                blocks.append({"type": "text", "text": "(placeholder)"})
            out.append({"role": msg.role, "content": blocks})

        return out

    @staticmethod
    def _tools_to_anthropic(tools: list[Any] | None) -> list[dict[str, Any]] | None:
        """中立 LlmTool → Anthropic tools。"""
        if not tools:
            return None
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in tools
        ]

    def _build_body(self, entry: ModelEntry, req: LlmRequest) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": entry.model_name,
            "messages": self._to_anthropic_messages(req.messages),
        }

        # system 是顶层字段(不进 messages)。如果包含静态/动态分界 marker,
        # 切成两个 content block 并给静态前缀打 cache_control,激活 Anthropic
        # prompt cache。详见 docs/superpowers/specs/2026-05-31-learning-system-prompt-design.md § 7。
        if req.system:
            body["system"] = _system_to_blocks(req.system)

        # 默认参数 < 请求参数 优先级
        max_tokens = req.max_tokens or entry.defaults.max_tokens
        # Anthropic 协议:max_tokens 是必填的!
        body["max_tokens"] = max_tokens or 4096

        temperature = (
            req.temperature
            if req.temperature is not None
            else entry.defaults.temperature
        )
        top_p = req.top_p if req.top_p is not None else entry.defaults.top_p

        if temperature is not None:
            body["temperature"] = temperature
        if top_p is not None:
            body["top_p"] = top_p
        if req.stop:
            body["stop_sequences"] = req.stop

        tools = self._tools_to_anthropic(req.tools)
        if tools:
            body["tools"] = tools

        # Final defense at the SDK boundary: scrub lone surrogates from the
        # whole body. Earlier scrubs (StreamAccumulator, runtime tool-result
        # block, LlmLogRepo) cover the obvious channels but stray surrogates
        # can still hide in places like SDK message id strings or malformed
        # web_fetch HTML that bypassed earlier paths. Encoding the JSON for
        # an HTTP body is the moment a surrogate would crash the request, so
        # we sanitize once more here regardless of what came before.
        return _strip_surrogates_deep(body)

    # ─── Anthropic → 中立 ───
    @staticmethod
    def _stop_reason_from_anthropic(reason: str | None) -> StopReason:
        mapping = {
            "end_turn": StopReason.END_TURN,
            "max_tokens": StopReason.MAX_TOKENS,
            "stop_sequence": StopReason.STOP_SEQUENCE,
            "tool_use": StopReason.TOOL_USE,
            None: StopReason.END_TURN,
        }
        return mapping.get(reason, StopReason.END_TURN)  # type: ignore[arg-type]

    @staticmethod
    def _content_blocks_from_anthropic(
        blocks: list[Any],
    ) -> list[ContentBlock]:
        out: list[ContentBlock] = []
        for b in blocks:
            btype = getattr(b, "type", None)
            if btype == "text":
                out.append(TextBlock(text=b.text))
            elif btype == "thinking":
                out.append(ThinkingBlock(text=b.thinking))
            elif btype == "tool_use":
                out.append(ToolUseBlock(id=b.id, name=b.name, input=b.input))
        return out

    # ─── 错误映射 ───
    @staticmethod
    def _map_error(exc: Exception) -> Exception:
        if isinstance(exc, anthropic.AuthenticationError):
            return LlmAuthError(str(exc))
        if isinstance(exc, anthropic.PermissionDeniedError):
            return LlmAuthError(str(exc))
        if isinstance(exc, anthropic.RateLimitError):
            return LlmRateLimitError(str(exc))
        if isinstance(exc, anthropic.BadRequestError):
            return LlmInvalidRequestError(str(exc))
        if isinstance(exc, anthropic.APITimeoutError):
            return LlmTimeoutError(str(exc))
        if isinstance(exc, anthropic.InternalServerError):
            return LlmServerError(str(exc))
        if isinstance(exc, anthropic.APIStatusError):
            if 500 <= exc.status_code < 600:
                return LlmServerError(str(exc))
            return LlmInvalidRequestError(str(exc))
        return exc

    # ─── 公开接口:invoke ───
    async def invoke(self, entry: ModelEntry, req: LlmRequest) -> LlmResponse:
        client = self._get_client(entry)
        body = self._build_body(entry, req)
        wire_id = uuid.uuid4().hex[:12]

        # ── wire 日志:即将发出去的原始 body ──
        _logger.info(
            "llm_wire_request",
            wire_id=wire_id,
            api="anthropic_messages",
            mode="invoke",
            model_logical=req.model,
            model_provider=body.get("model"),
            payload=cap_payload(body),
        )

        t0 = time.monotonic()
        try:
            sdk_resp = await client.messages.create(**body)
        except Exception as exc:
            _logger.error(
                "llm_wire_failed",
                wire_id=wire_id,
                api="anthropic_messages",
                mode="invoke",
                model_logical=req.model,
                duration_ms=int((time.monotonic() - t0) * 1000),
                error_type=type(exc).__name__,
                error=str(exc),
                exc_info=True,
            )
            raise self._map_error(exc) from exc

        # ── wire 日志:厂商真正返回的 SDK 对象 ──
        _logger.info(
            "llm_wire_response",
            wire_id=wire_id,
            api="anthropic_messages",
            mode="invoke",
            model_logical=req.model,
            duration_ms=int((time.monotonic() - t0) * 1000),
            payload=cap_payload(dump_sdk_object(sdk_resp)),
        )

        return LlmResponse(
            id=sdk_resp.id,
            model=req.model,
            content=self._content_blocks_from_anthropic(sdk_resp.content),
            stop_reason=self._stop_reason_from_anthropic(sdk_resp.stop_reason),
            usage=Usage(
                input_tokens=sdk_resp.usage.input_tokens,
                output_tokens=sdk_resp.usage.output_tokens,
                cache_read_tokens=getattr(sdk_resp.usage, "cache_read_input_tokens", 0) or 0,
                cache_write_tokens=getattr(sdk_resp.usage, "cache_creation_input_tokens", 0) or 0,
            ),
        )

    # ─── 公开接口:stream ───
    async def stream(
        self, entry: ModelEntry, req: LlmRequest
    ) -> AsyncIterator[StreamEvent]:
        client = self._get_client(entry)
        body = self._build_body(entry, req)
        wire_id = uuid.uuid4().hex[:12]

        # ── wire 日志:即将发出去的原始 body ──
        _logger.info(
            "llm_wire_request",
            wire_id=wire_id,
            api="anthropic_messages",
            mode="stream",
            model_logical=req.model,
            model_provider=body.get("model"),
            payload=cap_payload(body),
        )

        # 累积 SDK 原始事件,流结束时一次性打 llm_wire_stream_done。
        # 不在每个事件上打日志(一次对话上千个 chunk 会爆)。
        raw_events: list[dict[str, Any]] = []
        t0 = time.monotonic()

        message_started = False
        # 跟踪当前 content_block 的类型,delta 才知道是 text / thinking / tool_use
        current_block_type: dict[int, str] = {}
        current_tool_call_id: dict[int, str] = {}
        # 跟踪 input_tokens(message_start 时拿到)
        cached_input_tokens = 0

        try:
            async with client.messages.stream(**body) as stream:
                # Anthropic SDK stream 提供 raw events
                async for event in stream:
                    # 累积原始事件 — admin 排查时能看到完整事件序列
                    raw_events.append(dump_sdk_object(event))
                    etype = event.type

                    if etype == "message_start":
                        msg_id = event.message.id
                        cached_input_tokens = event.message.usage.input_tokens
                        yield MessageStart(id=msg_id, model=req.model)
                        message_started = True

                    elif etype == "content_block_start":
                        block = event.content_block
                        idx = event.index
                        current_block_type[idx] = block.type
                        if block.type == "tool_use":
                            current_tool_call_id[idx] = block.id
                            yield ToolCallStart(id=block.id, name=block.name)

                    elif etype == "content_block_delta":
                        idx = event.index
                        delta = event.delta
                        dtype = delta.type

                        if dtype == "text_delta":
                            yield TextDelta(text=delta.text)
                        elif dtype == "thinking_delta":
                            yield ThinkingDelta(text=delta.thinking)
                        elif dtype == "input_json_delta":
                            tc_id = current_tool_call_id.get(idx, "")
                            yield ToolCallDelta(
                                id=tc_id,
                                input_json_delta=delta.partial_json,
                            )

                    elif etype == "content_block_stop":
                        pass  # 不需要单独事件

                    elif etype == "message_delta":
                        # Anthropic 把 stop_reason 和最终 usage 放在这
                        if event.delta.stop_reason:
                            stop_reason = self._stop_reason_from_anthropic(
                                event.delta.stop_reason
                            )
                            yield MessageStop(stop_reason=stop_reason)
                        if event.usage:
                            yield UsageEvent(
                                usage=Usage(
                                    input_tokens=cached_input_tokens,
                                    output_tokens=event.usage.output_tokens,
                                )
                            )

                    elif etype == "message_stop":
                        pass  # 已经在 message_delta 处理

        except Exception as exc:
            _logger.error(
                "llm_wire_failed",
                wire_id=wire_id,
                api="anthropic_messages",
                mode="stream",
                model_logical=req.model,
                duration_ms=int((time.monotonic() - t0) * 1000),
                error_type=type(exc).__name__,
                error=str(exc),
                event_count=len(raw_events),
                exc_info=True,
            )
            mapped = self._map_error(exc)
            if not message_started:
                raise mapped from exc
            yield StreamError(message=str(mapped), error_type=type(mapped).__name__)
            raise LlmStreamError(str(mapped)) from exc

        # ── wire 日志:流自然结束,完整事件序列 ──
        _logger.info(
            "llm_wire_stream_done",
            wire_id=wire_id,
            api="anthropic_messages",
            mode="stream",
            model_logical=req.model,
            duration_ms=int((time.monotonic() - t0) * 1000),
            event_count=len(raw_events),
            payload=cap_payload({"events": raw_events}),
        )


# ─── helpers ───────────────────────────────────────────────────────────────

# Defined locally instead of importing from learning prompts to keep core/llm
# free of business-layer dependencies (ADR-0003: assistants/* depends on core,
# never the other way). The marker string is the contract; whoever writes
# this string into a system prompt opts into the cache split.
_SYSTEM_PROMPT_DYNAMIC_BOUNDARY = "__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__"


def _system_to_blocks(system: str) -> str | list[dict[str, Any]]:
    """Convert a system-prompt string into a list of content blocks if it
    contains the static/dynamic boundary marker, attaching cache_control to
    the static prefix so Anthropic prompt cache can hit it.

    No marker → return the original string (no cache wiring, no behavior
    change for callers that don't go through the learning prompt builder).

    The boundary line itself is dropped from the output — it's a developer
    marker, not content the LLM should see.
    """
    if _SYSTEM_PROMPT_DYNAMIC_BOUNDARY not in system:
        return system

    static_part, _, dynamic_part = system.partition(_SYSTEM_PROMPT_DYNAMIC_BOUNDARY)
    static_text = static_part.strip()
    dynamic_text = dynamic_part.strip()

    blocks: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": static_text,
            "cache_control": {"type": "ephemeral"},
        }
    ]
    if dynamic_text:
        blocks.append({"type": "text", "text": dynamic_text})
    return blocks
