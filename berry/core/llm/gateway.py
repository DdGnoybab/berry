"""ModelGateway —— 调用方唯一入口。

业务代码只 import 它,不感知 adapter / SDK / 具体协议。

切面分工:
- **wire 日志**:在 adapter 层(请求/响应原始 body 落地到 berry.log)
- **业务 metric**:在这里(Counter / Histogram,跟 wire 同语义但不同载体)

为什么 metric 不挪到 adapter?
  metric 关心的是"按 model 维度的总量 / 延迟分布",每条 adapter 都加一遍重复。
  这里是 LLM 调用唯一入口,挂一处覆盖所有 adapter,跟 spec 设计一致。

不在这里做的:
- 重试 / 限流 / fallback / usage 落库(V1)
"""

import time
from collections.abc import AsyncIterator

from berry.core.llm.adapters.base import Adapter
from berry.core.llm.errors import LlmAdapterNotFoundError
from berry.core.llm.registry import ModelRegistry
from berry.core.llm.types import (
    LlmRequest,
    LlmResponse,
    StreamEvent,
    UsageEvent,
)
from berry.observability.metrics import LLM_CALLS, LLM_DURATION, LLM_TOKENS


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
        api_str = entry.api.value if hasattr(entry.api, "value") else str(entry.api)
        labels = {"model_logical": request.model, "api": api_str, "mode": "invoke"}

        t0 = time.monotonic()
        try:
            response = await adapter.invoke(entry, request)
        except Exception:
            LLM_CALLS.labels(**labels, status="failed").inc()
            LLM_DURATION.labels(**labels).observe(time.monotonic() - t0)
            raise

        LLM_CALLS.labels(**labels, status="success").inc()
        LLM_DURATION.labels(**labels).observe(time.monotonic() - t0)

        token_labels = {"model_logical": request.model, "api": api_str}
        LLM_TOKENS.labels(**token_labels, kind="input").inc(response.usage.input_tokens)
        LLM_TOKENS.labels(**token_labels, kind="output").inc(response.usage.output_tokens)
        LLM_TOKENS.labels(**token_labels, kind="cache_read").inc(response.usage.cache_read_tokens)
        LLM_TOKENS.labels(**token_labels, kind="cache_write").inc(response.usage.cache_write_tokens)
        return response

    async def stream(
        self, model_id: str, request: LlmRequest
    ) -> AsyncIterator[StreamEvent]:
        """流式调用。"""
        adapter, entry = self._resolve(model_id)
        api_str = entry.api.value if hasattr(entry.api, "value") else str(entry.api)
        labels = {"model_logical": request.model, "api": api_str, "mode": "stream"}

        t0 = time.monotonic()
        # 累积 token usage(stream 经由 UsageEvent 报告)
        usage_in = 0
        usage_out = 0
        usage_cr = 0
        usage_cw = 0

        try:
            async for ev in adapter.stream(entry, request):
                if isinstance(ev, UsageEvent):
                    usage_in = ev.usage.input_tokens
                    usage_out = ev.usage.output_tokens
                    usage_cr = ev.usage.cache_read_tokens
                    usage_cw = ev.usage.cache_write_tokens
                yield ev
        except Exception:
            LLM_CALLS.labels(**labels, status="failed").inc()
            LLM_DURATION.labels(**labels).observe(time.monotonic() - t0)
            raise

        LLM_CALLS.labels(**labels, status="success").inc()
        LLM_DURATION.labels(**labels).observe(time.monotonic() - t0)

        token_labels = {"model_logical": request.model, "api": api_str}
        LLM_TOKENS.labels(**token_labels, kind="input").inc(usage_in)
        LLM_TOKENS.labels(**token_labels, kind="output").inc(usage_out)
        LLM_TOKENS.labels(**token_labels, kind="cache_read").inc(usage_cr)
        LLM_TOKENS.labels(**token_labels, kind="cache_write").inc(usage_cw)
