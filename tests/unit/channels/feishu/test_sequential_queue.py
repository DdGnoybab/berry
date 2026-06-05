"""SequentialQueue 行为测试 — 对应 openclaw `sequential-queue.test.ts`。"""

from __future__ import annotations

import asyncio

import pytest

from berry.channels.feishu.sequential_queue import SequentialQueue


pytestmark = pytest.mark.asyncio


async def test_same_key_runs_serially() -> None:
    q = SequentialQueue()
    log: list[str] = []

    async def make(label: str, delay: float) -> None:
        log.append(f"{label}-start")
        await asyncio.sleep(delay)
        log.append(f"{label}-end")

    t1 = q.run("k1", lambda: make("a", 0.05))
    t2 = q.run("k1", lambda: make("b", 0.01))
    await asyncio.gather(t1, t2)

    # 严格 FIFO:a 完整跑完才轮到 b
    assert log == ["a-start", "a-end", "b-start", "b-end"]


async def test_different_keys_run_concurrently() -> None:
    q = SequentialQueue()
    log: list[str] = []

    async def make(label: str, delay: float) -> None:
        log.append(f"{label}-start")
        await asyncio.sleep(delay)
        log.append(f"{label}-end")

    t1 = q.run("k1", lambda: make("a", 0.05))
    t2 = q.run("k2", lambda: make("b", 0.01))
    await asyncio.gather(t1, t2)

    # 不同 key 并发 — b 短,先 end
    assert log.index("b-end") < log.index("a-end")


async def test_timeout_evicts_but_does_not_abort() -> None:
    """超时后:队列让位给下一个,被超时的 task 继续跑(不 cancel)。"""
    timeouts: list[tuple[str, int]] = []
    q = SequentialQueue(
        task_timeout_ms=20,  # 20ms 超时
        on_task_timeout=lambda key, ms: timeouts.append((key, ms)),
    )
    log: list[str] = []

    async def slow() -> None:
        log.append("slow-start")
        await asyncio.sleep(0.2)  # 200ms,远超 timeout
        log.append("slow-end")

    async def quick() -> None:
        log.append("quick-start")
        log.append("quick-end")

    t_slow = q.run("k1", slow)
    t_quick = q.run("k1", quick)

    # 跑足够长,看 quick 是否被放行 + slow 最终也跑完
    await asyncio.sleep(0.3)
    assert "quick-end" in log, "超时后 quick 应被放行"
    assert "slow-end" in log, "slow 不能被强杀,要跑完"
    assert timeouts and timeouts[0][0] == "k1"

    # 收尾(防 warning)
    await t_slow
    await t_quick


async def test_failing_task_does_not_block_queue() -> None:
    q = SequentialQueue()
    log: list[str] = []

    async def fail() -> None:
        log.append("fail")
        raise RuntimeError("boom")

    async def ok() -> None:
        log.append("ok")

    t1 = q.run("k1", fail)
    t2 = q.run("k1", ok)
    await asyncio.gather(t1, t2)

    assert log == ["fail", "ok"]
