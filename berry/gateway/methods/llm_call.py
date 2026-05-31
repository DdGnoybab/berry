"""llm_call.* method handlers."""

from __future__ import annotations

from sqlalchemy import desc, select

from berry.core.db.models import LlmCallLog
from berry.gateway.methods.registry import CallContext, MethodRegistry
from berry.protocol.errors import ErrorCode, ProtocolError
from berry.protocol.methods_core import (
    CORE_METHODS,
    LlmCallDetail,
    LlmCallDetailParams,
    LlmCallListParams,
)
from berry.protocol.types import LlmCallSummary, Page


async def list_calls(
    params: LlmCallListParams, ctx: CallContext
) -> Page[LlmCallSummary]:
    stmt = (
        select(LlmCallLog)
        .where(LlmCallLog.user_id == ctx.user_id)  # type: ignore[arg-type]
        .order_by(desc(LlmCallLog.created_at))  # type: ignore[arg-type]
        .limit(params.limit)
    )
    if params.project_id is not None:
        stmt = stmt.where(LlmCallLog.project_id == params.project_id)  # type: ignore[arg-type]
    if params.model is not None:
        stmt = stmt.where(LlmCallLog.model == params.model)  # type: ignore[arg-type]
    if params.since is not None:
        stmt = stmt.where(LlmCallLog.created_at >= params.since)  # type: ignore[arg-type]

    result = await ctx.db.execute(stmt)
    rows = result.scalars().all()
    return Page[LlmCallSummary](
        items=[
            LlmCallSummary(
                id=r.id,
                user_id=r.user_id,
                project_id=r.project_id,
                session_id=r.session_id,
                model=r.model,
                created_at=r.created_at,
            )
            for r in rows
        ],
        next_cursor=None,
    )


async def detail(
    params: LlmCallDetailParams, ctx: CallContext
) -> LlmCallDetail:
    result = await ctx.db.execute(
        select(LlmCallLog).where(LlmCallLog.id == params.id)  # type: ignore[arg-type]
    )
    row = result.scalar_one_or_none()
    if row is None or row.user_id != ctx.user_id:
        raise ProtocolError(
            ErrorCode.INVALID_INPUT, f"llm_call {params.id} not found"
        )
    return LlmCallDetail(
        id=row.id,
        user_id=row.user_id,
        project_id=row.project_id,
        session_id=row.session_id,
        model=row.model,
        request=row.request,
        response=row.response,
        metadata=row.metadata_,
        created_at=row.created_at,
    )


def register(registry: MethodRegistry) -> None:
    registry.register(CORE_METHODS["llm_call.list"], list_calls)  # type: ignore[arg-type]
    registry.register(CORE_METHODS["llm_call.detail"], detail)  # type: ignore[arg-type]
