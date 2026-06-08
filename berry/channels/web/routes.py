"""HTTP transport for MethodRegistry — RPC + SSE streaming.

Endpoints:
  POST /v1/rpc           — one-shot method call
  POST /v1/turn/stream   — SSE streaming for turn.send (events come from EventBus)
  GET  /v1/methods       — self-description (all registered methods)

Architecture: this module is the web channel's HTTP transport.
It subscribes to the agent ``EventBus`` (``core/agent/event_bus.py``)
to forward streaming events as SSE frames; runtime emits, web channel
translates. No SSE knowledge leaks into core.

Note: SuggestionEmitted events fire from inside the runtime's event
loop (during a tool call), so subscribing BEFORE invoking the runtime
is mandatory — see _drain_turn / sse_adapter setup order.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from berry.channels.web.health import router as health_router
from berry.core.agent.event_bus import get_event_bus
from berry.core.agent.method_registry import CallContext, MethodRegistry
from berry.core.db.session import async_session_factory
from berry.protocol.errors import ProtocolError

router = APIRouter(tags=["web"])

# Re-export the health router under the same prefix.
router.include_router(health_router)

# Module-level registry reference, set via configure_http_rpc()
_registry: MethodRegistry | None = None


def configure_http_rpc(registry: MethodRegistry) -> None:
    """Called at startup to wire the method registry for HTTP transport.

    user_id is no longer set here — each request reads it from
    ``request.state.user_id`` (populated by AuthMiddleware).
    """
    global _registry
    _registry = registry


# ─── Request / Response schemas ──────────────────────────────────────────


class RpcRequest(BaseModel):
    method: str
    params: dict[str, Any] = Field(default_factory=dict)
    project_id: UUID | None = None


class RpcResponse(BaseModel):
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


# ─── POST /v1/rpc ────────────────────────────────────────────────────────


@router.post("/v1/rpc")
async def rpc_endpoint(req: RpcRequest, request: Request) -> JSONResponse:
    """One-shot method call. Returns result or error."""
    if _registry is None:
        return JSONResponse(
            {"error": {"code": "INTERNAL_ERROR", "message": "HTTP RPC not configured"}},
            status_code=500,
        )

    user_id = _user_id_from_request(request)
    if user_id is None:
        return _unauthorized()

    try:
        async with async_session_factory() as db:
            ctx = CallContext(
                user_id=user_id,
                request_id=f"http-{datetime.now().isoformat()}",
                transport="web",
                db=db,
                project_id=req.project_id,
            )
            result = await _registry.call(req.method, req.params, ctx)
            return JSONResponse({"result": result.model_dump(mode="json")})
    except ProtocolError as exc:
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message, "detail": exc.detail}},
            status_code=200,
        )
    except Exception as exc:
        return JSONResponse(
            {"error": {"code": "INTERNAL_ERROR", "message": f"{type(exc).__name__}: {exc}"}},
            status_code=500,
        )


# ─── POST /v1/turn/stream ────────────────────────────────────────────────


@router.post("/v1/turn/stream")
async def turn_stream_endpoint(req: RpcRequest, request: Request) -> StreamingResponse:
    """SSE streaming endpoint for turn.send.

    Pipeline:
      1. Subscribe to ``EventBus`` for the session.
      2. Run the turn — runtime emits AgentEvents to the bus.
         Tools (e.g. ``ask_user_question``) emit SuggestionEmitted.
      3. Forward bus events as SSE frames.

    Subscription happens BEFORE turn execution so we don't drop events
    fired during the very first stream chunk.
    """
    if _registry is None:
        return JSONResponse(
            {"error": {"code": "INTERNAL_ERROR", "message": "HTTP RPC not configured"}},
            status_code=500,
        )

    user_id = _user_id_from_request(request)
    if user_id is None:
        return _unauthorized()

    session_id = req.params.get("session_id", "")

    async def event_generator():
        bus = get_event_bus()
        # Pre-subscribe before we kick off the turn so events fired during
        # the first stream chunk are captured.
        sub_queue = bus.subscribe(session_id)

        async def _drain_turn() -> None:
            try:
                async with async_session_factory() as db:
                    ctx = CallContext(
                        user_id=user_id,
                        request_id=f"http-stream-{datetime.now().isoformat()}",
                        transport="web",
                        db=db,
                        project_id=req.project_id,
                    )
                    async for event in _registry.call_stream(
                        req.method, req.params, ctx
                    ):
                        # Runtime emits AgentEvents directly through async
                        # generator; mirror them into the bus so the SSE
                        # forwarder is the single output path.
                        bus.emit(session_id, event)  # type: ignore[arg-type]
            except ProtocolError as exc:
                bus.emit(
                    session_id,
                    _make_error_event(exc.code, exc.message),  # type: ignore[arg-type]
                )
            except Exception as exc:
                bus.emit(
                    session_id,
                    _make_error_event(
                        "INTERNAL_ERROR",
                        f"{type(exc).__name__}: {exc}",
                    ),  # type: ignore[arg-type]
                )
            finally:
                # Sentinel so the SSE stream terminates after the turn.
                await sub_queue.put(None)

        turn_task = asyncio.create_task(_drain_turn())
        try:
            from berry.channels.web.sse_adapter import serialize_event

            while True:
                event = await sub_queue.get()
                if event is None:
                    break
                yield f"data: {serialize_event(event)}\n\n"
        finally:
            turn_task.cancel()
            bus.unsubscribe(session_id, sub_queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ─── GET /v1/methods ─────────────────────────────────────────────────────


@router.get("/v1/methods")
async def methods_endpoint() -> JSONResponse:
    """Self-description: list all registered methods."""
    if _registry is None:
        return JSONResponse({"methods": []})

    methods = []
    for spec in _registry.list_methods():
        methods.append(
            {
                "name": spec.name,
                "description": spec.description,
                "domain": spec.domain,
                "streaming": spec.stream_event_schema is not None,
                "params_schema": spec.params_schema.model_json_schema(),
                "result_schema": (
                    spec.result_schema.model_json_schema()
                    if spec.result_schema
                    else None
                ),
            }
        )
    return JSONResponse({"methods": methods})


# ─── helpers ─────────────────────────────────────────────────────────────


class _ErrorEvent(BaseModel):
    """Streaming-error wire format the frontend understands."""

    type: str = "error"
    code: str
    message: str


def _make_error_event(code: str, message: str) -> _ErrorEvent:
    return _ErrorEvent(code=code, message=message)


def _user_id_from_request(request: Request) -> UUID | None:
    """Pull user_id stamped onto the request by AuthMiddleware."""
    return getattr(request.state, "user_id", None)


def _unauthorized() -> JSONResponse:
    return JSONResponse(
        {"error": {"code": "UNAUTHORIZED", "message": "login required"}},
        status_code=401,
    )
