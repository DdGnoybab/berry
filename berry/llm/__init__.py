"""Berry LLM Gateway —— 统一模型网关。

对外只暴露:
- ModelGateway:调用入口
- LlmRequest / LlmMessage / LlmResponse / StreamEvent:中立类型

内部细节(adapters / registry / watcher)不应被业务模块直接 import。
"""

from berry.llm.gateway import ModelGateway
from berry.llm.types import (
    LlmMessage,
    LlmRequest,
    LlmResponse,
    StreamEvent,
    TextBlock,
    Usage,
)

__all__ = [
    "ModelGateway",
    "LlmRequest",
    "LlmResponse",
    "LlmMessage",
    "StreamEvent",
    "TextBlock",
    "Usage",
]
