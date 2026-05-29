"""ModelGateway —— 调用方唯一入口。

业务代码只 import 它,不感知 adapter / SDK / 具体协议。

Batch 1 范围:
- invoke / stream 路由
- adapter not found 报错
- 不做重试 / 限流 / fallback / usage 落库(V1)
"""

from collections.abc import AsyncIterator

from berry.llm.adapters.base import Adapter
from berry.llm.errors import LlmAdapterNotFoundError
from berry.llm.registry import ModelRegistry
from berry.llm.types import LlmRequest, LlmResponse, StreamEvent


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
        return await adapter.invoke(entry, request)

    async def stream(
        self, model_id: str, request: LlmRequest
    ) -> AsyncIterator[StreamEvent]:
        """流式调用。"""
        adapter, entry = self._resolve(model_id)
        async for ev in adapter.stream(entry, request):
            yield ev
