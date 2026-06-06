"""Todo 事件总线 — core 层 emit,channels 层 listen。

core/ 不能 import channels/(架构规则 §2.1),所以用回调桥接。
entrypoints 组装层注册 listener,core 只 emit 不感知谁在监听。

对齐 claw-code:claw-code 没有这个机制(它没有 channel 层)。
这是 berry 的合理扩展:飞书需要实时渲染 todo 进度卡片。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from berry.observability.logging import get_logger

logger = get_logger(__name__)


@dataclass
class TodoUpdatedEvent:
    """todo_write 工具执行后发出的事件。"""

    conversation_id: str
    todos: list[dict[str, str]]
    old_todos: list[dict[str, str]]
    verification_nudge: bool


TodoEventListener = Callable[[TodoUpdatedEvent], None]

_listeners: list[TodoEventListener] = []


def register_todo_listener(listener: TodoEventListener) -> None:
    """注册一个 todo 更新监听器。在 entrypoints 组装层调用。"""
    _listeners.append(listener)


def emit_todo_updated(event: TodoUpdatedEvent) -> None:
    """通知所有监听器。fire-and-forget,异常不传播。"""
    for listener in _listeners:
        try:
            listener(event)
        except Exception as exc:
            logger.warning(
                "todo_listener_failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )
