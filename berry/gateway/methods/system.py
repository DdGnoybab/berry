"""system.* method handlers."""

from __future__ import annotations

from importlib.metadata import version

from sqlalchemy import select

from berry.core.db.models import User
from berry.gateway.methods.registry import CallContext, MethodRegistry
from berry.protocol.errors import ErrorCode, ProtocolError
from berry.protocol.methods_core import (
    CORE_METHODS,
    HealthParams,
    HealthResult,
    MeParams,
    MeResult,
)
from berry.protocol.types import UserInfo


async def health(params: HealthParams, ctx: CallContext) -> HealthResult:
    try:
        v = version("berry")
    except Exception:
        v = "0.0.0-dev"
    return HealthResult(status="ok", version=v)


async def me(params: MeParams, ctx: CallContext) -> MeResult:
    result = await ctx.db.execute(
        select(User).where(User.id == ctx.user_id)  # type: ignore[arg-type]
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise ProtocolError(
            ErrorCode.USER_NOT_FOUND, f"user {ctx.user_id} not found"
        )
    return MeResult(
        user=UserInfo(
            id=row.id, handle=row.handle, display_name=row.display_name
        )
    )


def register(registry: MethodRegistry) -> None:
    registry.register(CORE_METHODS["system.health"], health)  # type: ignore[arg-type]
    registry.register(CORE_METHODS["system.me"], me)  # type: ignore[arg-type]
