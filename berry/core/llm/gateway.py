"""ModelGateway —— 调用方唯一入口。

业务代码只 import 它,不感知 adapter / SDK / 具体协议。

Batch 1 范围:
- invoke / stream 路由
- adapter not found 报错
- LLM 调用切面日志(请求/响应可在 /admin/logs 面板展开看)
- 不做重试 / 限流 / fallback / usage 落库(V1)
"""

import time
from collections.abc import AsyncIterator

from berry.core.llm.adapters.base import Adapter
from berry.core.llm.errors import LlmAdapterNotFoundError
from berry.core.llm.registry import ModelRegistry
from berry.core.llm.types import (
    LlmRequest,
    LlmResponse,
    MessageStop,
    StreamEvent,
    TextDelta,
    ThinkingDelta,
    ToolCallDelta,
    ToolCallStart,
    UsageEvent,
)
from berry.observability.llm_logging import (
    summarize_request,
    summarize_response,
    summarize_stream_outcome,
)
from berry.observability.logging import get_logger

logger = get_logger(__name__)


class ModelGateway:
    """调用 LLM 的唯一入口。"""

    def __init__(
        self,
        registry: ModelRegistry,
        adapters: dict[str, Adapter],
    ) -> None:
        """
        Args:
            registry: 模型 catalog
            adapters: api 字符串 → Adapter 实现
                      例 {"openai-completions": OpenAICompletionsAdapter()}
        """
        self._registry = registry
        self._adapters = adapters

    @property
    def registry(self) -> ModelRegistry:
        """暴露 registry 供调用方查询元信息(如 fallback chain)。"""
        return self._registry

    def _resolve(self, model_id: str) -> tuple[Adapter, "ModelEntry"]:  # type: ignore[name-defined]  # noqa: F821
        """model_id → (adapter, entry)。"""
        entry = self._registry.get(model_id)
        api_str = entry.api.value if hasattr(entry.api, "value") else str(entry.api)
        adapter = self._adapters.get(api_str)
        if adapter is None:
            raise LlmAdapterNotFoundError(
                f"no adapter registered for api={api_str!r} "
                f"(model={model_id!r})"
            )
        return adapter, entry

    async def invoke(self, model_id: str, request: LlmRequest) -> LlmResponse:
        """非流式调用。"""
        adapter, entry = self._resolve(model_id)

        # ── 切面:start ──
        req_summary = summarize_request(request)
        logger.info("llm_call_start", mode="invoke", **req_summary)

        t0 = time.monotonic()
        try:
            response = await adapter.invoke(entry, request)
        except Exception as e:
            logger.error(
                "llm_call_failed",
                mode="invoke",
                model=request.model,
                duration_ms=int((time.monotonic() - t0) * 1000),
                error_type=type(e).__name__,
                error=str(e),
                exc_info=True,
            )
            raise

        logger.info(
            "llm_call_done",
            mode="invoke",
            model=request.model,
            duration_ms=int((time.monotonic() - t0) * 1000),
            **summarize_response(response),
        )
        return response

    async def stream(
        self, model_id: str, request: LlmRequest
    ) -> AsyncIterator[StreamEvent]:
        """流式调用。"""
        adapter, entry = self._resolve(model_id)

        # ── 切面:start ──
        req_summary = summarize_request(request)
        logger.info("llm_call_start", mode="stream", **req_summary)

        t0 = time.monotonic()

        # 累积出收尾要打的信息
        text_buf: list[str] = []
        thinking_buf: list[str] = []
        tool_call_names: dict[str, str] = {}      # tool_use_id -> tool name
        tool_call_input_chars: dict[str, int] = {}  # tool_use_id -> 累积 input json 字符数
        stop_reason: str | None = None
        usage_in = 0
        usage_out = 0
        usage_cr = 0
        usage_cw = 0

        try:
            async for ev in adapter.stream(entry, request):
                if isinstance(ev, TextDelta):
                    text_buf.append(ev.text)
                elif isinstance(ev, ThinkingDelta):
                    thinking_buf.append(ev.text)
                elif isinstance(ev, ToolCallStart):
                    tool_call_names[ev.id] = ev.name
                    tool_call_input_chars[ev.id] = 0
                elif isinstance(ev, ToolCallDelta):
                    if ev.id in tool_call_input_chars:
                        tool_call_input_chars[ev.id] += len(ev.input_json_delta)
                elif isinstance(ev, MessageStop):
                    stop_reason = (
                        ev.stop_reason.value
                        if hasattr(ev.stop_reason, "value")
                        else str(ev.stop_reason)
                    )
                elif isinstance(ev, UsageEvent):
                    usage_in = ev.usage.input_tokens
                    usage_out = ev.usage.output_tokens
                    usage_cr = ev.usage.cache_read_tokens
                    usage_cw = ev.usage.cache_write_tokens
                # MessageStart / StreamError 不做累积:Start 已经在 start 日志里;
                # StreamError 走 except 路径
                yield ev
        except Exception as e:
            logger.error(
                "llm_call_failed",
                mode="stream",
                model=request.model,
                duration_ms=int((time.monotonic() - t0) * 1000),
                error_type=type(e).__name__,
                error=str(e),
                output_chars="".join(text_buf).__len__(),
                exc_info=True,
            )
            raise

        logger.info(
            "llm_call_done",
            mode="stream",
            model=request.model,
            duration_ms=int((time.monotonic() - t0) * 1000),
            **summarize_stream_outcome(
                accumulated_text="".join(text_buf),
                accumulated_thinking="".join(thinking_buf),
                tool_calls=[
                    {
                        "id": tid,
                        "name": tool_call_names[tid],
                        "input_chars": tool_call_input_chars[tid],
                    }
                    for tid in tool_call_names
                ],
                stop_reason=stop_reason,
                input_tokens=usage_in,
                output_tokens=usage_out,
                cache_read_tokens=usage_cr,
                cache_write_tokens=usage_cw,
            ),
        )
