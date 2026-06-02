"""approval.respond handler.

Stage 2: connects to ApprovalRegistry singleton to resolve in-flight Future.
"""

from __future__ import annotations

from berry.core.agent.approval_registry import (
    ApprovalAlreadyResolvedError,
    ApprovalNotFoundError,
    get_approval_registry,
)
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
    if params.decision not in {"approve", "deny"}:
        raise ProtocolError(
            ErrorCode.INVALID_INPUT,
            f"decision must be 'approve' or 'deny', got {params.decision!r}",
        )

    registry = get_approval_registry()
    try:
        registry.resolve(
            params.approval_id,
            approved=(params.decision == "approve"),
            reason=params.reason,
        )
    except ApprovalNotFoundError as exc:
        raise ProtocolError(
            ErrorCode.APPROVAL_NOT_FOUND,
            f"approval {params.approval_id!r} not found or already expired",
        ) from exc
    except ApprovalAlreadyResolvedError as exc:
        raise ProtocolError(
            ErrorCode.INVALID_INPUT,
            f"approval {params.approval_id!r} already resolved",
        ) from exc

    return ApprovalAck(accepted=True)


def register(registry: MethodRegistry) -> None:
    registry.register(CORE_METHODS["approval.respond"], respond)  # type: ignore[arg-type]
