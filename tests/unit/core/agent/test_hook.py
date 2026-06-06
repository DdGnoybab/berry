"""Tests for PreToolUseHook + HookRunner."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from berry.core.agent.hook import (
    DENY,
    DEFER,
    ALLOW,
    HookRunner,
    HookVerdict,
    HookVerdictAction,
    PreToolUseHook,
    allow,
    defer,
    deny,
)
from berry.core.tools.base import ToolContext


# ── helpers ───────────────────────────────────────────────────────────────


def _ctx() -> ToolContext:
    return ToolContext(
        session_id="test-session-id",
        user_id=uuid4(),
        db=None,
        data_root=Path("/tmp/berry_test"),
        cwd=Path("/tmp/berry_test"),
    )


class _StaticHook:
    """A hook that always returns the same verdict."""

    def __init__(self, verdict: HookVerdict) -> None:
        self._verdict = verdict
        self.call_count = 0

    async def run(
        self,
        tool_name: str,
        args: dict[str, object],
        ctx: ToolContext,
    ) -> HookVerdict:
        self.call_count += 1
        return self._verdict


class _RecordingHook:
    """A hook that records calls and returns a configurable verdict."""

    def __init__(self, verdict: HookVerdict) -> None:
        self._verdict = verdict
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def run(
        self,
        tool_name: str,
        args: dict[str, object],
        ctx: ToolContext,
    ) -> HookVerdict:
        self.calls.append((tool_name, args))
        return self._verdict


class _ExplodingHook:
    """A hook that always raises."""

    async def run(
        self,
        tool_name: str,
        args: dict[str, object],
        ctx: ToolContext,
    ) -> HookVerdict:
        raise RuntimeError("boom")


# ── convenience constructors ──────────────────────────────────────────────


def test_allow_convenience() -> None:
    v = allow("safe operation")
    assert v.action is ALLOW
    assert v.reason == "safe operation"


def test_deny_convenience() -> None:
    v = deny("blocked")
    assert v.action is DENY
    assert v.reason == "blocked"


def test_defer_convenience() -> None:
    v = defer()
    assert v.action is DEFER
    assert v.reason is None


# ── HookVerdict ───────────────────────────────────────────────────────────


def test_verdict_is_frozen() -> None:
    v = allow()
    with pytest.raises(AttributeError):
        v.action = DENY  # type: ignore[misc]


def test_verdict_action_is_str_enum() -> None:
    assert ALLOW.value == "allow"
    assert DENY.value == "deny"
    assert DEFER.value == "defer"


# ── HookRunner — no hooks ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_runner_no_hooks_returns_defer() -> None:
    runner = HookRunner()
    result = await runner.run("bash", {"command": "ls"}, _ctx())
    assert result.action is DEFER
    assert runner.hook_count == 0


# ── HookRunner — single hook ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_runner_single_allow() -> None:
    hook = _StaticHook(allow("all good"))
    runner = HookRunner([hook])
    result = await runner.run("bash", {"command": "ls"}, _ctx())
    assert result.action is ALLOW
    assert result.reason == "all good"
    assert hook.call_count == 1


@pytest.mark.asyncio
async def test_runner_single_deny() -> None:
    hook = _StaticHook(deny("forbidden"))
    runner = HookRunner([hook])
    result = await runner.run("bash", {"command": "rm -rf /"}, _ctx())
    assert result.action is DENY
    assert result.reason == "forbidden"


@pytest.mark.asyncio
async def test_runner_single_defer() -> None:
    hook = _StaticHook(defer())
    runner = HookRunner([hook])
    result = await runner.run("bash", {"command": "ls"}, _ctx())
    assert result.action is DEFER


# ── HookRunner — multiple hooks ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_runner_first_defer_second_allow() -> None:
    h1 = _StaticHook(defer())
    h2 = _StaticHook(allow("approved"))
    runner = HookRunner([h1, h2])
    result = await runner.run("bash", {"command": "ls"}, _ctx())
    assert result.action is ALLOW
    assert h1.call_count == 1
    assert h2.call_count == 1


@pytest.mark.asyncio
async def test_runner_first_deny_stops_chain() -> None:
    h1 = _StaticHook(deny("blocked"))
    h2 = _StaticHook(allow("should not run"))
    runner = HookRunner([h1, h2])
    result = await runner.run("bash", {"command": "ls"}, _ctx())
    assert result.action is DENY
    assert h1.call_count == 1
    assert h2.call_count == 0  # never called


@pytest.mark.asyncio
async def test_runner_first_allow_stops_chain() -> None:
    h1 = _StaticHook(allow("fast pass"))
    h2 = _StaticHook(deny("should not run"))
    runner = HookRunner([h1, h2])
    result = await runner.run("bash", {"command": "ls"}, _ctx())
    assert result.action is ALLOW
    assert h1.call_count == 1
    assert h2.call_count == 0


@pytest.mark.asyncio
async def test_runner_all_defer_returns_defer() -> None:
    h1 = _StaticHook(defer())
    h2 = _StaticHook(defer())
    h3 = _StaticHook(defer())
    runner = HookRunner([h1, h2, h3])
    result = await runner.run("bash", {"command": "ls"}, _ctx())
    assert result.action is DEFER
    assert h1.call_count == 1
    assert h2.call_count == 1
    assert h3.call_count == 1


# ── HookRunner — exception handling ───────────────────────────────────────


@pytest.mark.asyncio
async def test_runner_hook_raises_returns_deny() -> None:
    hook = _ExplodingHook()
    runner = HookRunner([hook])
    result = await runner.run("bash", {"command": "ls"}, _ctx())
    assert result.action is DENY
    assert "raised" in (result.reason or "")


@pytest.mark.asyncio
async def test_runner_first_raises_stops_chain() -> None:
    h1 = _ExplodingHook()
    h2 = _StaticHook(allow("should not run"))
    runner = HookRunner([h1, h2])
    result = await runner.run("bash", {"command": "ls"}, _ctx())
    assert result.action is DENY
    assert h2.call_count == 0


# ── HookRunner — arguments forwarded ──────────────────────────────────────


@pytest.mark.asyncio
async def test_runner_forwards_tool_name_and_args() -> None:
    hook = _RecordingHook(defer())
    runner = HookRunner([hook])
    args = {"command": "echo hello"}
    await runner.run("bash", args, _ctx())
    assert len(hook.calls) == 1
    assert hook.calls[0] == ("bash", args)


# ── Protocol conformance ──────────────────────────────────────────────────


def test_static_hook_satisfies_protocol() -> None:
    hook = _StaticHook(allow())
    assert isinstance(hook, PreToolUseHook)


def test_recording_hook_satisfies_protocol() -> None:
    hook = _RecordingHook(defer())
    assert isinstance(hook, PreToolUseHook)


def test_exploding_hook_satisfies_protocol() -> None:
    hook = _ExplodingHook()
    assert isinstance(hook, PreToolUseHook)
