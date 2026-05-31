"""turn.send / turn.cancel (Stage 1 stub: returns simple ack stream;
Stage 2 connects GoalTutor)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

from berry.gateway.methods.registry import CallContext, MethodRegistry
from berry.protocol.errors import ErrorCode, ProtocolError
from berry.protocol.events import AgentEvent, TextDelta, TurnEnd, TurnStart
from berry.protocol.methods_core import (
    CORE_METHODS,
    CancelledResult,
    TurnCancelParams,
    TurnSendParams,
)


async def turn_send(
    params: TurnSendParams, ctx: CallContext
) -> AsyncIterator[AgentEvent]:
    """Stage 1 stub: doesn't call LLM, just confirms wiring works.

    Stage 2 will:
      1. Find the project owning the session
      2. Pick TurnRunner by project.domain (learning -> GoalTutor)
      3. Delegate to TurnRunner.run_turn, stream AgentEvents
    """
    yield TurnStart(session_id=_stub_uuid(params.session_id))
    yield TextDelta(text=f"[stub] echoing your input: {params.text}")
    yield TurnEnd(stop_reason="end_turn")


async def turn_cancel(
    params: TurnCancelParams, ctx: CallContext
) -> CancelledResult:
    raise ProtocolError(
        ErrorCode.INTERNAL_ERROR, "turn.cancel not implemented yet"
    )


def _stub_uuid(s: str) -> UUID:
    """File session_id string -> derived UUID (for TurnStart.session_id type).

    Stage 2 changes TurnStart.session_id to str; this stub will be removed.
    """
    from uuid import NAMESPACE_OID, uuid5
    return uuid5(NAMESPACE_OID, s)


def register(registry: MethodRegistry) -> None:
    registry.register(CORE_METHODS["turn.send"], turn_send)  # type: ignore[arg-type]
    registry.register(CORE_METHODS["turn.cancel"], turn_cancel)  # type: ignore[arg-type]
