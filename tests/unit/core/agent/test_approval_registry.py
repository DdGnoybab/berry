"""Unit tests for ApprovalRegistry."""

from __future__ import annotations

import asyncio

import pytest

from berry.core.agent.approval_registry import (
    ApprovalAlreadyResolvedError,
    ApprovalNotFoundError,
    ApprovalRegistry,
    get_approval_registry,
)


@pytest.mark.asyncio
async def test_register_returns_id_and_future() -> None:
    reg = ApprovalRegistry()
    aid, fut = reg.register()
    assert aid.startswith("appr_")
    assert isinstance(fut, asyncio.Future)
    assert not fut.done()


@pytest.mark.asyncio
async def test_resolve_completes_future() -> None:
    reg = ApprovalRegistry()
    aid, fut = reg.register()
    reg.resolve(aid, approved=True, reason="ok")
    result = await fut
    assert result.approved is True
    assert result.reason == "ok"


@pytest.mark.asyncio
async def test_resolve_unknown_raises() -> None:
    reg = ApprovalRegistry()
    with pytest.raises(ApprovalNotFoundError):
        reg.resolve("nope", approved=True)


@pytest.mark.asyncio
async def test_resolve_twice_raises() -> None:
    reg = ApprovalRegistry()
    aid, _ = reg.register()
    reg.resolve(aid, approved=True)
    # second resolve - approval_id is gone after first resolve
    with pytest.raises(ApprovalNotFoundError):
        reg.resolve(aid, approved=False)


@pytest.mark.asyncio
async def test_register_duplicate_id_raises() -> None:
    reg = ApprovalRegistry()
    aid = "appr_fixed"
    reg.register(aid)
    with pytest.raises(ApprovalAlreadyResolvedError):
        reg.register(aid)


@pytest.mark.asyncio
async def test_wait_resolves_normally() -> None:
    reg = ApprovalRegistry()
    aid, _ = reg.register()

    async def resolver() -> None:
        await asyncio.sleep(0.01)
        reg.resolve(aid, approved=True, reason="yes")

    task = asyncio.create_task(resolver())
    result = await reg.wait(aid, timeout_seconds=1.0)
    await task
    assert result.approved is True
    assert result.reason == "yes"


@pytest.mark.asyncio
async def test_wait_timeout() -> None:
    reg = ApprovalRegistry()
    aid, _ = reg.register()
    result = await reg.wait(aid, timeout_seconds=0.05)
    assert result.approved is False
    assert result.reason == "approval timeout"


@pytest.mark.asyncio
async def test_cleanup_idempotent() -> None:
    reg = ApprovalRegistry()
    aid, _ = reg.register()
    reg.cleanup(aid)
    reg.cleanup(aid)  # idempotent


def test_singleton_is_singleton() -> None:
    a = get_approval_registry()
    b = get_approval_registry()
    assert a is b
