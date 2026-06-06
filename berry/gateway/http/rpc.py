"""HTTP transport for MethodRegistry: RPC + SSE streaming.

Endpoints:
  POST /v1/rpc          — one-shot method call
  POST /v1/turn/stream  — SSE streaming for turn.send
  GET  /v1/methods      — self-description (all registered methods)
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from berry.core.db.repos.user_repo import UserRepo
from berry.core.db.session import async_session_factory
from berry.gateway.methods.registry import CallContext, MethodRegistry
from berry.protocol.errors import ErrorCode, ProtocolError

router = APIRouter(tags=["rpc"])

# Module-level registry reference, set via configure_http_rpc()
_registry: MethodRegistry | None = None
_default_user_id: UUID | None = None


def configure_http_rpc(registry: MethodRegistry, default_user_id: UUID) -> None:
    """Called at startup to wire the method registry for HTTP transport."""
    global _registry, _default_user_id
    _registry = registry
    _default_user_id = default_user_id


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
    if _registry is None or _default_user_id is None:
        return JSONResponse(
            {"error": {"code": "INTERNAL_ERROR", "message": "HTTP RPC not configured"}},
            status_code=500,
        )

    try:
        async with async_session_factory() as db:
            ctx = CallContext(
                user_id=_default_user_id,
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

    Each SSE event is a JSON-encoded AgentEvent.
    Suggestion events from present_options tool are merged in.
    """
    if _registry is None or _default_user_id is None:
        return JSONResponse(
            {"error": {"code": "INTERNAL_ERROR", "message": "HTTP RPC not configured"}},
            status_code=500,
        )

    from berry.core.agent.suggestion_event import (
        drain_suggestion_queue,
        register_suggestion_queue,
        unregister_suggestion_queue,
    )

    # Extract session_id from params for suggestion queue routing
    session_id = req.params.get("session_id", "")

    async def event_generator():
        # Register suggestion queue for this session
        register_suggestion_queue(session_id)

        # Queue for merging turn events + suggestion events
        yield_queue: asyncio.Queue[str | None] = asyncio.Queue()

        async def _forward_suggestions():
            try:
                async for suggestion in drain_suggestion_queue(session_id):
                    data = json.dumps({
                        "type": "suggestion_options",
                        "suggestion_id": suggestion.suggestion_id,
                        "context": suggestion.context,
                        "prompt": suggestion.prompt,
                        "options": [
                            {"key": o.key, "label": o.label, "recommended": o.recommended}
                            for o in suggestion.options
                        ],
                    })
                    await yield_queue.put(data)
            except asyncio.CancelledError:
                pass

        async def _drain_turn():
            try:
                async with async_session_factory() as db:
                    ctx = CallContext(
                        user_id=_default_user_id,
                        request_id=f"http-stream-{datetime.now().isoformat()}",
                        transport="web",
                        db=db,
                        project_id=req.project_id,
                    )
                    async for event in _registry.call_stream(req.method, req.params, ctx):
                        await yield_queue.put(event.model_dump_json())
            except ProtocolError as exc:
                await yield_queue.put(json.dumps({"type": "error", "code": exc.code, "message": exc.message}))
            except Exception as exc:
                await yield_queue.put(json.dumps({"type": "error", "code": "INTERNAL_ERROR", "message": f"{type(exc).__name__}: {exc}"}))

        # Start both tasks
        turn_task = asyncio.create_task(_drain_turn())
        suggestion_task = asyncio.create_task(_forward_suggestions())

        try:
            while True:
                data = await yield_queue.get()
                if data is None:
                    break
                yield f"data: {data}\n\n"
        finally:
            turn_task.cancel()
            suggestion_task.cancel()
            unregister_suggestion_queue(session_id)

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
        methods.append({
            "name": spec.name,
            "description": spec.description,
            "domain": spec.domain,
            "streaming": spec.stream_event_schema is not None,
            "params_schema": spec.params_schema.model_json_schema(),
            "result_schema": spec.result_schema.model_json_schema() if spec.result_schema else None,
        })
    return JSONResponse({"methods": methods})
