"""OpenAI Chat Completions 协议 adapter。

覆盖范围:
- OpenAI 官方
- DeepSeek
- 智谱 GLM
- Kimi
- 通义千问
- 几乎所有 OpenAI 兼容站(只要 base_url + api_key + model_name 配对)

Batch 1 范围:
- 纯文本 invoke(非流)
- 纯文本 stream
- 错误映射
- 不实现 tool_use / thinking(Batch 2 加)
"""

from collections.abc import AsyncIterator
from typing import Any

import openai
from openai import AsyncOpenAI

from berry.core.llm.config import ModelEntry
from berry.core.llm.enums import KnownApi, StopReason
from berry.core.llm.errors import (
    LlmAuthError,
    LlmInvalidRequestError,
    LlmRateLimitError,
    LlmServerError,
    LlmStreamError,
    LlmTimeoutError,
)
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
    ToolCallDelta,
    ToolCallStart,
    ToolUseBlock,
    ToolResultBlock,
    Usage,
    UsageEvent,
)


class OpenAICompletionsAdapter:
    """OpenAI ChatCompletions 协议实现。"""

    api = KnownApi.OPENAI_COMPLETIONS.value

    def __init__(self) -> None:
        # 按 base_url + key 缓存 client(复用 HTTP 连接池)
        self._clients: dict[str, AsyncOpenAI] = {}

    # ─── client 缓存 ───
    def _get_client(self, entry: ModelEntry) -> AsyncOpenAI:
        cache_key = f"{entry.base_url}|{entry.api_key[:8]}"
        if cache_key not in self._clients:
            self._clients[cache_key] = AsyncOpenAI(
                api_key=entry.api_key,
                base_url=entry.base_url,
                timeout=entry.timeout_s,
            )
        return self._clients[cache_key]

    # ─── 中立 → OpenAI ───
    @staticmethod
    def _to_openai_messages(
        system: str | None, messages: list[LlmMessage]
    ) -> list[dict[str, Any]]:
        """中立 messages → OpenAI messages 数组。

        OpenAI Chat 协议特点:
        - system 放在 messages[0],role='system'
        - assistant 的工具调用用 message.tool_calls 表达
        - 工具结果用 role='tool' + tool_call_id
        - 不支持 thinking,丢弃
        """
        out: list[dict[str, Any]] = []
        if system:
            out.append({"role": "system", "content": system})

        for msg in messages:
            text_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            tool_results: list[ToolResultBlock] = []

            for b in msg.content:
                if isinstance(b, TextBlock):
                    text_parts.append(b.text)
                elif isinstance(b, ThinkingBlock):
                    # OpenAI 协议不支持 thinking,丢弃
                    pass
                elif isinstance(b, ToolUseBlock):
                    # assistant 的 tool_use → tool_calls
                    import json
                    tool_calls.append({
                        "id": b.id,
                        "type": "function",
                        "function": {
                            "name": b.name,
                            "arguments": json.dumps(b.input, ensure_ascii=False),
                        },
                    })
                elif isinstance(b, ToolResultBlock):
                    # 收集起来,每个 tool_result 单独发一条 role=tool 消息
                    tool_results.append(b)

            text = "\n".join(text_parts) if text_parts else None

            if msg.role == "user" and tool_results:
                # OpenAI:tool_result 走单独的 role=tool 消息(不是 user)
                # 先把同一条 user 消息里其他文本发出去(如果有)
                if text:
                    out.append({"role": "user", "content": text})
                for tr in tool_results:
                    out.append({
                        "role": "tool",
                        "tool_call_id": tr.tool_use_id,
                        "content": tr.output,
                    })
            elif msg.role == "assistant":
                # assistant:可能同时有 text 和 tool_calls
                entry: dict[str, Any] = {"role": "assistant", "content": text}
                if tool_calls:
                    entry["tool_calls"] = tool_calls
                out.append(entry)
            else:
                out.append({"role": msg.role, "content": text or ""})

        return out

    @staticmethod
    def _tools_to_openai(tools: list[Any] | None) -> list[dict[str, Any]] | None:
        """中立 LlmTool → OpenAI tools。"""
        if not tools:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in tools
        ]

    def _build_body(self, entry: ModelEntry, req: LlmRequest) -> dict[str, Any]:
        """组装传给 SDK 的 kwargs。"""
        body: dict[str, Any] = {
            "model": entry.model_name,
            "messages": self._to_openai_messages(req.system, req.messages),
        }

        # 默认参数 < 请求参数 优先级
        max_tokens = req.max_tokens or entry.defaults.max_tokens
        temperature = (
            req.temperature
            if req.temperature is not None
            else entry.defaults.temperature
        )
        top_p = req.top_p if req.top_p is not None else entry.defaults.top_p

        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if temperature is not None:
            body["temperature"] = temperature
        if top_p is not None:
            body["top_p"] = top_p
        if req.stop:
            body["stop"] = req.stop

        # 工具
        tools = self._tools_to_openai(req.tools)
        if tools:
            body["tools"] = tools

        return body

    # ─── OpenAI → 中立 ───
    @staticmethod
    def _stop_reason_from_openai(finish_reason: str | None) -> StopReason:
        mapping = {
            "stop": StopReason.END_TURN,
            "length": StopReason.MAX_TOKENS,
            "tool_calls": StopReason.TOOL_USE,
            "function_call": StopReason.TOOL_USE,
            None: StopReason.END_TURN,
        }
        return mapping.get(finish_reason, StopReason.END_TURN)  # type: ignore[arg-type]

    # ─── 错误映射 ───
    @staticmethod
    def _map_error(exc: Exception) -> Exception:
        """SDK 异常 → Berry 异常。"""
        if isinstance(exc, openai.AuthenticationError):
            return LlmAuthError(str(exc))
        if isinstance(exc, openai.PermissionDeniedError):
            return LlmAuthError(str(exc))
        if isinstance(exc, openai.RateLimitError):
            return LlmRateLimitError(str(exc))
        if isinstance(exc, openai.BadRequestError):
            return LlmInvalidRequestError(str(exc))
        if isinstance(exc, openai.APITimeoutError):
            return LlmTimeoutError(str(exc))
        if isinstance(exc, openai.InternalServerError):
            return LlmServerError(str(exc))
        if isinstance(exc, openai.APIStatusError):
            # 兜底:其他 4xx / 5xx
            if 500 <= exc.status_code < 600:
                return LlmServerError(str(exc))
            return LlmInvalidRequestError(str(exc))
        # 其他异常透传
        return exc

    # ─── 公开接口:invoke ───
    async def invoke(self, entry: ModelEntry, req: LlmRequest) -> LlmResponse:
        client = self._get_client(entry)
        body = self._build_body(entry, req)

        try:
            sdk_resp = await client.chat.completions.create(**body)
        except Exception as exc:
            raise self._map_error(exc) from exc

        choice = sdk_resp.choices[0]
        msg = choice.message
        usage = sdk_resp.usage

        # 组装中立 content blocks(text + tool_use)
        content: list[ContentBlock] = []
        if msg.content:
            content.append(TextBlock(text=msg.content))

        if getattr(msg, "tool_calls", None):
            import json
            for tc in msg.tool_calls:
                try:
                    parsed_input = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    parsed_input = {"_raw": tc.function.arguments}
                content.append(
                    ToolUseBlock(
                        id=tc.id,
                        name=tc.function.name,
                        input=parsed_input,
                    )
                )

        if not content:
            content.append(TextBlock(text=""))

        return LlmResponse(
            id=sdk_resp.id,
            model=req.model,
            content=content,
            stop_reason=self._stop_reason_from_openai(choice.finish_reason),
            usage=Usage(
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
            ),
        )

    # ─── 公开接口:stream ───
    async def stream(
        self, entry: ModelEntry, req: LlmRequest
    ) -> AsyncIterator[StreamEvent]:
        client = self._get_client(entry)
        body = self._build_body(entry, req)
        body["stream"] = True
        # OpenAI 流式默认不返 usage,需要显式打开
        body["stream_options"] = {"include_usage": True}

        message_started = False
        stop_reason = StopReason.END_TURN
        # 跟踪流式中的 tool_call,每个 index 第一次见时发 start
        seen_tool_call_indices: dict[int, str] = {}  # index -> tool_call_id

        try:
            sdk_stream = await client.chat.completions.create(**body)

            async for chunk in sdk_stream:
                # MessageStart(第一个 chunk 时发)
                if not message_started:
                    yield MessageStart(id=chunk.id, model=req.model)
                    message_started = True

                # 没有 choice 的 chunk(usage-only)
                if not chunk.choices:
                    if chunk.usage:
                        yield UsageEvent(
                            usage=Usage(
                                input_tokens=chunk.usage.prompt_tokens,
                                output_tokens=chunk.usage.completion_tokens,
                            )
                        )
                    continue

                choice = chunk.choices[0]
                delta = choice.delta

                # 文本增量
                if delta.content:
                    yield TextDelta(text=delta.content)

                # 工具调用增量
                if getattr(delta, "tool_calls", None):
                    for tc in delta.tool_calls:
                        idx = tc.index
                        # 第一次见到 index,发 ToolCallStart
                        if idx not in seen_tool_call_indices and tc.id and tc.function:
                            seen_tool_call_indices[idx] = tc.id
                            yield ToolCallStart(
                                id=tc.id,
                                name=tc.function.name or "",
                            )
                        # 增量 arguments
                        if tc.function and tc.function.arguments:
                            tc_id = seen_tool_call_indices.get(idx, tc.id or "")
                            yield ToolCallDelta(
                                id=tc_id,
                                input_json_delta=tc.function.arguments,
                            )

                # finish_reason(末尾)
                if choice.finish_reason:
                    stop_reason = self._stop_reason_from_openai(choice.finish_reason)

            # 流正常结束
            yield MessageStop(stop_reason=stop_reason)

        except Exception as exc:
            mapped = self._map_error(exc)
            # 如果还没发过 message_start,直接抛(让上层 catch);
            # 已经发过,降级为流内 error 事件
            if not message_started:
                raise mapped from exc
            yield StreamError(
                message=str(mapped),
                error_type=type(mapped).__name__,
            )
            raise LlmStreamError(str(mapped)) from exc
