"""MethodRegistry - Berry process-internal method name -> handler dict.

All channels (Web / CLI / Feishu) call via registry.call(name, params, ctx);
they don't care about transport.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from berry.protocol.errors import ErrorCode, ProtocolError
from berry.protocol.methods_core import MethodSpec

# Handler signatures (BaseModel rather than ParamSchema because Protocol
# can't be generic too deeply).
SyncHandler = Callable[[BaseModel, "CallContext"], Awaitable[BaseModel]]
StreamHandler = Callable[[BaseModel, "CallContext"], AsyncIterator[BaseModel]]


@dataclass
class CallContext:
    """Per-method-call execution context.

    Channel injects user_id / project_id / db / transport; handler uses directly.
    """

    user_id: UUID
    request_id: str
    transport: str            # "http_rpc" / "http_sse" / "cli" / "feishu"
    db: AsyncSession           # one per call (within a turn, one)
    project_id: UUID | None = None
    metadata: dict[str, Any] | None = None


class MethodRegistry:
    """Container for registration + dispatch.

    One instance per process (singleton); various register functions push
    methods at startup.
    """

    def __init__(self) -> None:
        self._specs: dict[str, MethodSpec] = {}
        self._handlers: dict[str, SyncHandler | StreamHandler] = {}

    # ── register ──

    def register(
        self,
        spec: MethodSpec,
        handler: SyncHandler | StreamHandler,
    ) -> None:
        if spec.name in self._specs:
            raise ValueError(f"duplicate method registered: {spec.name!r}")
        self._specs[spec.name] = spec
        self._handlers[spec.name] = handler

    # ── lookup ──

    def list_methods(self, domain: str | None = None) -> list[MethodSpec]:
        specs = list(self._specs.values())
        if domain is not None:
            specs = [s for s in specs if s.domain == domain]
        return specs

    def get_spec(self, name: str) -> MethodSpec:
        spec = self._specs.get(name)
        if spec is None:
            raise ProtocolError(
                ErrorCode.METHOD_NOT_FOUND,
                f"unknown method: {name!r}",
            )
        return spec

    # ── call (one-shot) ──

    async def call(
        self,
        name: str,
        raw_params: dict[str, Any],
        ctx: CallContext,
    ) -> BaseModel:
        spec = self.get_spec(name)
        if spec.stream_event_schema is not None:
            raise ProtocolError(
                ErrorCode.INVALID_INPUT,
                f"method {name!r} is streaming; use call_stream",
            )
        params = _validate_params(spec, raw_params)
        handler = cast(SyncHandler, self._handlers[name])
        result = await handler(params, ctx)
        if not isinstance(result, BaseModel):
            raise RuntimeError(
                f"handler for {name!r} returned non-BaseModel: {type(result).__name__}"
            )
        return result

    # ── call (streaming) ──

    async def call_stream(
        self,
        name: str,
        raw_params: dict[str, Any],
        ctx: CallContext,
    ) -> AsyncIterator[BaseModel]:
        spec = self.get_spec(name)
        if spec.stream_event_schema is None:
            raise ProtocolError(
                ErrorCode.INVALID_INPUT,
                f"method {name!r} is not streaming; use call",
            )
        params = _validate_params(spec, raw_params)
        handler = cast(StreamHandler, self._handlers[name])
        async for event in handler(params, ctx):
            yield event


def _validate_params(spec: MethodSpec, raw: dict[str, Any]) -> BaseModel:
    """Unified schema validation; failure -> ProtocolError."""
    try:
        return spec.params_schema.model_validate(raw)
    except Exception as exc:
        raise ProtocolError(
            ErrorCode.INVALID_INPUT,
            f"invalid params for {spec.name!r}: {exc}",
            detail={"raw_error": str(exc)},
        ) from exc
