"""approval.respond (Stage 1 stub)."""

from __future__ import annotations

from berry.gateway.methods.registry import CallContext, MethodRegistry
from berry.protocol.errors import ErrorCode, ProtocolError
from berry.protocol.methods_core import (
    CORE_METHODS,
    ApprovalAck,
    ApprovalRespondParams,
)


async def respond(
    params: ApprovalRespondParams, ctx: CallContext
) -> ApprovalAck:
    raise ProtocolError(
        ErrorCode.APPROVAL_NOT_FOUND,
        "approval registry not implemented in Stage 1; see Stage 2",
    )


def register(registry: MethodRegistry) -> None:
    registry.register(CORE_METHODS["approval.respond"], respond)  # type: ignore[arg-type]
