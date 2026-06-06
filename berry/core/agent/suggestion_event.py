"""Suggestion 事件总线 — core 层 emit,channels 层 listen。

present_options 工具调用后,通过 asyncio.Queue 把选项推给 SSE 流。
不走 callback(回调在 sync 上下文里不好往 async Queue 塞),直接用 Queue。

用法:
  web entrypoint 调 register_suggestion_queue(session_id, queue)
  SSE generator 里 yield from drain_suggestion_queue(session_id)
  工具 execute 里 call emit_suggestion(session_id, options)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from berry.observability.logging import get_logger

logger = get_logger(__name__)


@dataclass
class SuggestionOption:
    """一个可选按钮。"""
    key: str
    label: str
    recommended: bool = False


@dataclass
class SuggestionEvent:
    """推给前端的选项集。"""
    type: str = "suggestion_options"
    suggestion_id: str = ""
    context: str = ""
    prompt: str = ""
    options: list[SuggestionOption] = field(default_factory=list)


# ── per-session async queues ──────────────────────────────────────────

_queues: dict[str, asyncio.Queue[SuggestionEvent]] = {}


def register_suggestion_queue(session_id: str) -> asyncio.Queue[SuggestionEvent]:
    """为一个 SSE 流注册 Queue。web entrypoint 的 SSE generator 调用。"""
    q: asyncio.Queue[SuggestionEvent] = asyncio.Queue()
    _queues[session_id] = q
    return q


def unregister_suggestion_queue(session_id: str) -> None:
    _queues.pop(session_id, None)


def emit_suggestion(session_id: str, event: SuggestionEvent) -> None:
    """工具 execute() 调用。把事件塞进 Queue。"""
    q = _queues.get(session_id)
    if q is None:
        return  # 没有 SSE 流在监听,静默跳过
    try:
        q.put_nowait(event)
    except Exception:
        logger.warning("suggestion_emit_failed", session_id=session_id)


async def drain_suggestion_queue(
    session_id: str,
) -> asyncio.AsyncIterator[SuggestionEvent]:
    """SSE generator 用来消费事件。阻塞直到 queue 被关闭。"""
    q = _queues.get(session_id)
    if q is None:
        return
    try:
        while True:
            event = await q.get()
            if event is None:  # type: ignore[comparison-overlap]
                break
            yield event
    except asyncio.CancelledError:
        pass
    finally:
        unregister_suggestion_queue(session_id)
