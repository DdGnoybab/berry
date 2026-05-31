"""Unit tests for MethodRegistry."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from pydantic import BaseModel

from berry.gateway.methods.registry import CallContext, MethodRegistry
from berry.protocol.errors import ErrorCode, ProtocolError
from berry.protocol.methods_core import MethodSpec

# ─── Test schemas ───────────────────────────────────────


class EchoParams(BaseModel):
    text: str


class EchoResult(BaseModel):
    text: str


class EchoEvent(BaseModel):
    chunk: str


ECHO_SPEC = MethodSpec(
    name="test.echo",
    params_schema=EchoParams,
    result_schema=EchoResult,
    description="echo for test",
    domain="test",
)

ECHO_STREAM_SPEC = MethodSpec(
    name="test.stream",
    params_schema=EchoParams,
    result_schema=None,
    stream_event_schema=EchoEvent,
    description="stream echo for test",
    domain="test",
)


# ─── fixture ────────────────────────────────────────────


def _make_ctx() -> CallContext:
    return CallContext(
        user_id=uuid4(),
        request_id="req-1",
        transport="cli",
        db=None,  # type: ignore[arg-type]
    )


# ─── handlers ──────────────────────────────────────────


async def echo_handler(params: EchoParams, ctx: CallContext) -> EchoResult:
    return EchoResult(text=params.text)


async def echo_stream_handler(
    params: EchoParams, ctx: CallContext
) -> AsyncIterator[EchoEvent]:
    for ch in params.text:
        yield EchoEvent(chunk=ch)


# ─── register ──────────────────────────────────────────


def test_register_and_call() -> None:
    reg = MethodRegistry()
    reg.register(ECHO_SPEC, echo_handler)  # type: ignore[arg-type]
    specs = reg.list_methods(domain="test")
    assert len(specs) == 1
    assert specs[0].name == "test.echo"


def test_register_duplicate_raises() -> None:
    reg = MethodRegistry()
    reg.register(ECHO_SPEC, echo_handler)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="duplicate"):
        reg.register(ECHO_SPEC, echo_handler)  # type: ignore[arg-type]


# ─── call (one-shot) ────────────────────────────────────


async def test_call_validates_params() -> None:
    reg = MethodRegistry()
    reg.register(ECHO_SPEC, echo_handler)  # type: ignore[arg-type]

    result = await reg.call("test.echo", {"text": "hi"}, _make_ctx())
    assert isinstance(result, EchoResult)
    assert result.text == "hi"


async def test_call_unknown_method_raises_method_not_found() -> None:
    reg = MethodRegistry()
    with pytest.raises(ProtocolError) as exc:
        await reg.call("nope", {}, _make_ctx())
    assert exc.value.code == ErrorCode.METHOD_NOT_FOUND


async def test_call_invalid_params_raises_invalid_input() -> None:
    reg = MethodRegistry()
    reg.register(ECHO_SPEC, echo_handler)  # type: ignore[arg-type]
    with pytest.raises(ProtocolError) as exc:
        await reg.call("test.echo", {"text": 123}, _make_ctx())
    assert exc.value.code == ErrorCode.INVALID_INPUT


async def test_call_streaming_method_with_call_raises() -> None:
    reg = MethodRegistry()
    reg.register(ECHO_STREAM_SPEC, echo_stream_handler)  # type: ignore[arg-type]
    with pytest.raises(ProtocolError, match="streaming"):
        await reg.call("test.stream", {"text": "ab"}, _make_ctx())


# ─── call_stream ────────────────────────────────────────


async def test_call_stream_yields_events() -> None:
    reg = MethodRegistry()
    reg.register(ECHO_STREAM_SPEC, echo_stream_handler)  # type: ignore[arg-type]
    chunks = []
    async for ev in reg.call_stream("test.stream", {"text": "abc"}, _make_ctx()):
        assert isinstance(ev, EchoEvent)
        chunks.append(ev.chunk)
    assert chunks == ["a", "b", "c"]


async def test_call_stream_with_non_streaming_method_raises() -> None:
    reg = MethodRegistry()
    reg.register(ECHO_SPEC, echo_handler)  # type: ignore[arg-type]
    with pytest.raises(ProtocolError, match="not streaming"):
        async for _ in reg.call_stream("test.echo", {"text": "x"}, _make_ctx()):
            pass


# ─── domain filter ──────────────────────────────────────


def test_list_methods_filter_by_domain() -> None:
    reg = MethodRegistry()
    reg.register(ECHO_SPEC, echo_handler)  # type: ignore[arg-type]

    other = MethodSpec(
        name="other.x",
        params_schema=EchoParams,
        result_schema=EchoResult,
        description="other",
        domain="core",
    )

    async def other_h(p: EchoParams, c: CallContext) -> EchoResult:
        return EchoResult(text="ok")

    reg.register(other, other_h)  # type: ignore[arg-type]

    test_only = reg.list_methods(domain="test")
    assert len(test_only) == 1
    assert test_only[0].name == "test.echo"

    core_only = reg.list_methods(domain="core")
    assert len(core_only) == 1
    assert core_only[0].name == "other.x"

    all_ = reg.list_methods()
    assert len(all_) == 2
