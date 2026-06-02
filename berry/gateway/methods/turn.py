"""turn.send / turn.cancel handlers.

Stage 2:
- turn.send connects to LLM via an injected TurnRunner (GoalTutor in practice)
- Explicitly persists messages via SessionStore (Stage 1 moved this from runtime to caller)
- Picks runner by project.domain; for now only "learning" is supported

Architecture compliance:
  gateway must not import channels.* or assistants.* (import-linter rules 3b / 10).
  Instead, the entrypoint (entrypoints/cli.py or entrypoints/feishu.py) constructs
  the runner (GoalTutor) and registers it here via configure_runner() before the
  REPL / event loop starts.

  TurnRunner Protocol lives in core/agent/ — gateway is allowed to import that.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from berry.config import settings
from berry.core.agent.persistence import load_agent_session
from berry.core.agent.session_store import SessionStore
from berry.core.agent.turn_runner import TurnRunner
from berry.core.db.repos.project_repo import ProjectRepo
from berry.core.project.service import ProjectService
from berry.gateway.methods.registry import CallContext, MethodRegistry
from berry.protocol.errors import ErrorCode, ProtocolError
from berry.protocol.events import AgentEvent
from berry.protocol.methods_core import (
    CORE_METHODS,
    CancelledResult,
    TurnCancelParams,
    TurnSendParams,
)

# ─── Injected runner (set by entrypoints before REPL starts) ──────────────────
#
# Entrypoints call configure_runner(runner) once at startup.
# This avoids gateway importing channels.* or assistants.* directly.

_runner: TurnRunner | None = None


def configure_runner(runner: TurnRunner) -> None:
    """Inject the TurnRunner implementation (called by entrypoints at startup).

    Args:
        runner: A GoalTutor (learning), WorkAssistant (work), etc.  Any object
                that satisfies TurnRunner Protocol.
    """
    global _runner
    _runner = runner


# ─── Handlers ──────────────────────────────────────────────


async def turn_send(
    params: TurnSendParams, ctx: CallContext
) -> AsyncIterator[AgentEvent]:
    """Real turn.send.

    1. Find session's project (scan all user projects)
    2. project.domain == "learning" -> use injected TurnRunner
    3. Load AgentSession from SessionStore
    4. Delegate to runner.run_turn -> stream events
    5. After: persist new messages to SessionStore
    """
    if _runner is None:
        raise ProtocolError(
            ErrorCode.INTERNAL_ERROR,
            "TurnRunner not configured; call turn.configure_runner() at startup",
        )

    # Find session file location
    repo = ProjectRepo(ctx.db)
    projects = await repo.list_by_user(ctx.user_id)
    svc = ProjectService(settings.data_root)
    target_project = None
    target_session_dir = None
    for p in projects:
        sd = svc.session_dir(p, params.session_id)
        if sd.is_dir():
            target_project = p
            target_session_dir = sd
            break

    if target_project is None or target_session_dir is None:
        raise ProtocolError(
            ErrorCode.SESSION_NOT_FOUND,
            f"session {params.session_id} not found in any of your projects",
        )

    if target_project.domain != "learning":
        raise ProtocolError(
            ErrorCode.INTERNAL_ERROR,
            f"domain {target_project.domain!r} not supported in Stage 2",
        )

    store = SessionStore(target_session_dir)
    agent_session = load_agent_session(store)
    if agent_session is None:
        raise ProtocolError(
            ErrorCode.SESSION_NOT_FOUND,
            f"session {params.session_id} meta.json missing",
        )

    # Snapshot pre-turn message count to know what to persist after
    pre_message_count = len(agent_session.messages)

    # Delegate; stream events to caller
    async for ev in _runner.run_turn(session=agent_session, user_text=params.text):
        yield ev

    # After turn: persist all new messages added in-memory
    # (ConversationRuntime calls session.push_user_text + push_message internally
    # but doesn't write to file - Stage 1 moved that responsibility here)
    new_messages = agent_session.messages[pre_message_count:]
    for msg in new_messages:
        store.append_message(msg)


async def turn_cancel(
    params: TurnCancelParams, ctx: CallContext
) -> CancelledResult:
    raise ProtocolError(
        ErrorCode.INTERNAL_ERROR, "turn.cancel not implemented yet (Stage 3)"
    )


def register(registry: MethodRegistry) -> None:
    registry.register(CORE_METHODS["turn.send"], turn_send)  # type: ignore[arg-type]
    registry.register(CORE_METHODS["turn.cancel"], turn_cancel)  # type: ignore[arg-type]
