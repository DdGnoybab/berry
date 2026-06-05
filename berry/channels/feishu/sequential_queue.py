"""Per-key serial task queue — 同 key 串行,跨 key 并发。

对齐 openclaw `extensions/feishu/src/sequential-queue.ts`:
- 同 key 任务严格 FIFO(保证同一对话消息不并行处理)
- 不同 key 互不阻塞
- 单任务超时(`task_timeout_ms`,默认 5min):超时后视作完成、把队列让给后续
  同 key 任务;**已开始的 task 不强杀**(协程保留运行,只是不再阻塞链路)。
  这是 openclaw 实战经验:有问题的 task hang 住后,绝不能让整个对话再没法
  收消息。

API:
    queue = SequentialQueue(task_timeout_ms=300_000)
    await queue.run("chat:abc", lambda: do_work())  # 协程函数
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from berry.observability.logging import get_logger

logger = get_logger(__name__)

DEFAULT_TASK_TIMEOUT_MS: int = 5 * 60 * 1000   # 5min,与 openclaw 默认一致


class SequentialQueue:
    """Per-key FIFO 任务队列。

    Args:
        task_timeout_ms: 单任务超时,超时后队列让位给下一个同 key 任务。
            <= 0 / None 关掉超时(无界,只在测试里用)。
        on_task_timeout: 超时回调,签名 `(key, timeout_ms) -> None`,异常被吞。
    """

    def __init__(
        self,
        task_timeout_ms: int = DEFAULT_TASK_TIMEOUT_MS,
        on_task_timeout: Callable[[str, int], None] | None = None,
    ) -> None:
        self._timeout_ms = task_timeout_ms
        self._on_timeout = on_task_timeout
        # 每个 key 维持「最近一次 task 的 future」,新 task 链在它后面跑
        self._tails: dict[str, asyncio.Task[None]] = {}

    def run(
        self,
        key: str,
        task_factory: Callable[[], Awaitable[Any]],
    ) -> asyncio.Task[None]:
        """把一个 task 排进 `key` 的队列尾部,返回它的 asyncio.Task。

        立刻返回 — 调用方决定要不要 await(handler 一般不 await,let it fly)。
        """
        previous = self._tails.get(key)

        async def _runner() -> None:
            if previous is not None:
                try:
                    await previous
                except Exception:
                    # 前一个 task 抛异常不阻断后续
                    pass
            await self._bounded_run(key, task_factory)

        new_task = asyncio.create_task(_runner())
        self._tails[key] = new_task

        # 当 new_task 结束时,如果它仍是 tail,清理(防内存累积)
        def _cleanup(t: asyncio.Task[None]) -> None:
            if self._tails.get(key) is t:
                del self._tails[key]

        new_task.add_done_callback(_cleanup)
        return new_task

    async def _bounded_run(
        self,
        key: str,
        task_factory: Callable[[], Awaitable[Any]],
    ) -> None:
        if self._timeout_ms is None or self._timeout_ms <= 0:
            try:
                await task_factory()
            except Exception as exc:
                logger.error(
                    "feishu_queue_task_failed",
                    key=key,
                    error_type=type(exc).__name__,
                    error=str(exc),
                    exc_info=True,
                )
            return

        timeout_s = self._timeout_ms / 1000.0
        actual = asyncio.create_task(_safe_call(task_factory, key))
        try:
            await asyncio.wait_for(asyncio.shield(actual), timeout=timeout_s)
        except asyncio.TimeoutError:
            # 不强杀 actual — 让它继续在后台跑;队列让位给后续同 key 任务
            try:
                if self._on_timeout is not None:
                    self._on_timeout(key, self._timeout_ms)
            except Exception:
                pass
            logger.warning(
                "feishu_queue_task_timeout",
                key=key,
                timeout_ms=self._timeout_ms,
            )


async def _safe_call(
    factory: Callable[[], Awaitable[Any]],
    key: str,
) -> None:
    """执行 factory(),吞异常并记日志 — 不让它污染队列链。"""
    try:
        await factory()
    except Exception as exc:
        logger.error(
            "feishu_queue_task_failed",
            key=key,
            error_type=type(exc).__name__,
            error=str(exc),
            exc_info=True,
        )
