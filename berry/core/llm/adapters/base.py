"""Adapter Protocol —— 协议适配器接口。

每个协议(anthropic-messages / openai-completions / ...)一个实现。
Adapter 只做「中立类型 ↔ 协议格式」转换 + SDK 调用,
不做重试 / 限流 / 路由(那是 Gateway 的事)。
"""

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from berry.core.llm.config import ModelEntry
from berry.core.llm.types import LlmRequest, LlmResponse, StreamEvent


@runtime_checkable
class Adapter(Protocol):
    """协议适配器。"""

    api: str   # KnownApi 的字符串值

    async def invoke(
        self, entry: ModelEntry, req: LlmRequest
    ) -> LlmResponse:
        """非流式调用。"""
        ...

    def stream(
        self, entry: ModelEntry, req: LlmRequest
    ) -> AsyncIterator[StreamEvent]:
        """流式调用。返回异步迭代器。

        注:这里是 def 而不是 async def,因为 async generator 的类型签名比较绕,
        实现时用 `async def stream(...) -> AsyncIterator[...]: yield ...`。
        """
        ...
