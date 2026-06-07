"""``session.resume_create`` handler.

Same shape as ``learning.create_project`` (streaming RPC) but:
  - Project + workspace already exist; only a fresh session is created.
  - Priming message reads the workspace's ``progress.json`` to decide
    which resume options to suggest.

Why backend-derived options (not LLM-inferred): the priming message
LITERALLY tells the LLM the labels to put on the buttons — it is the
single most reliable way to make sure the user always sees a sensible
set of choices regardless of the LLM's mood. SKILL.md §1bis remains
the underlying contract; this handler just gives the LLM a very
precise script.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from berry.config import settings
from berry.core.agent.events import TextDelta, TurnEnd
from berry.core.agent.persistence import load_agent_session
from berry.core.agent.session_store import SessionStore, generate_session_id
from berry.core.db.models import Project
from berry.core.db.repos.project_repo import ProjectRepo
from berry.core.project.service import ProjectService
from berry.gateway.methods.registry import CallContext, MethodRegistry
from berry.gateway.methods.turn import get_runner
from berry.observability.logging import get_logger
from berry.protocol.errors import ErrorCode, ProtocolError
from berry.protocol.events import AgentEvent
from berry.protocol.methods_core import (
    CORE_METHODS,
    SessionMeta,
    SessionResumeCreateParams,
)

logger = get_logger(__name__)


# ─── progress.json reader ───────────────────────────────────────────────


def _read_progress(workspace: Path) -> dict[str, Any] | None:
    pj = workspace / ".berry" / "progress.json"
    if not pj.is_file():
        return None
    try:
        return json.loads(pj.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "resume_progress_read_failed",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return None


def _next_atom_after(
    modules: dict[str, Any],
    current_module: str | None,
    current_atom: str | None,
) -> tuple[str | None, str | None, str | None]:
    """Find the atom that comes right after the given (module, atom).

    Returns ``(next_module_id, next_atom_id, next_atom_name)``.
    Returns ``(None, None, None)`` when the user is already on the last
    atom of the last module.
    """
    seen_current = current_module is None and current_atom is None
    for mod_id, mod_data in modules.items():
        atoms = mod_data.get("atoms") or {}
        for atom_id, atom_data in atoms.items():
            if seen_current:
                return mod_id, atom_id, atom_data.get("name")
            if mod_id == current_module and atom_id == current_atom:
                seen_current = True
    return None, None, None


# ─── priming-message builder ────────────────────────────────────────────


def build_resume_priming(progress: dict[str, Any] | None) -> str:
    """Compose the synthetic 'first user message' for a resume turn.

    The message hands the LLM a one-sentence summary template + an
    explicit options array to pass to ``ask_user_question``. Backend
    drives the option set — LLM only fills text + invokes the tool.
    """
    if progress is None:
        # No plan yet — should not happen in practice (creating a session
        # under a not-yet-init learning project). Fall back to "where do
        # we start" prompt.
        return (
            "我打开了一个新会话,但 .berry/progress.json 还没建。"
            "请用 ask_user_question 让我选下一步,选项就用这 3 个 label:\n"
            "  - 「先建学习计划」(recommended=true)\n"
            "  - 「让我先看看 ROADMAP」\n"
            "  - 「自由聊聊学这个的事」\n"
            "调完工具就停,不要多说。"
        )

    topic = progress.get("topic") or "this topic"
    current = progress.get("current") or {}
    current_module = current.get("module")
    current_atom = current.get("atom")
    micro = current.get("micro_state") or "PROBING"
    modules = progress.get("modules") or {}

    atom_data = (
        (modules.get(current_module) or {}).get("atoms") or {}
    ).get(current_atom) if current_module and current_atom else None
    atom_name = atom_data.get("name") if atom_data else None
    atom_label = (
        f"{current_atom} {atom_name}" if (current_atom and atom_name)
        else (current_atom or "")
    )

    next_mod, next_atom, next_name = _next_atom_after(
        modules, current_module, current_atom
    )
    next_atom_label = (
        f"{next_atom} {next_name}" if (next_atom and next_name) else next_atom
    )

    # Per-micro_state option set. Each row is a list of (label, recommended)
    # pairs the LLM should pass to ask_user_question verbatim.
    if micro == "PROBING":
        options = [
            (f"接着答 {atom_label} 的摸底题", True),
            (f"换种方式问 {current_atom}", False),
            (f"跳过 {current_atom}", False),
            ("让我看看路线图", False),
        ]
    elif micro == "TEACHING":
        options = [
            (f"接着讲 {atom_label}", True),
            ("换个角度讲", False),
            (f"我懂了,直接测 {current_atom}", False),
            ("让我看看路线图", False),
        ]
    elif micro == "ASSESSING":
        options = [
            (f"接着答完 {atom_label} 的测试", True),
            (f"先复习 {atom_label} 再续", False),
            *(
                [(f"跳到下一个 atom {next_atom_label}", False)]
                if next_atom
                else []
            ),
            ("让我看看路线图", False),
        ]
    elif micro in ("AWAITING_USER", ""):
        # User left during AWAITING_USER — give the recommended forward
        # options + escape hatches.
        options = [
            (f"小测一下 {atom_label} 复习", True),
            *(
                [(f"接着学 {next_atom_label}", False)]
                if next_atom
                else []
            ),
            ("让我看看路线图", False),
            ("调整下学习计划", False),
        ]
    else:
        # MODULE_INTRO / MODULE_REVIEW / TOPIC_DONE / unknown — generic
        options = [
            *(
                [(f"开始学 {next_atom_label}", True)]
                if next_atom
                else [("继续上次的进度", True)]
            ),
            ("先小测一下复习", False),
            ("让我看看路线图", False),
            ("调整下学习计划", False),
        ]

    options_md = "\n".join(
        f"  - 「{label}」"
        + ("(recommended=true)" if rec else "")
        for label, rec in options
    )

    summary_hint = (
        f"上次到 {current_module} / {atom_label} 的 {micro} 阶段"
        if current_module and current_atom
        else "之前已经初始化好计划"
    )

    return (
        f"我刚开了一个新会话,继续学 {topic}。\n"
        f"{summary_hint}。\n\n"
        f"请按 SKILL.md §1bis 「resume」流程:\n"
        f"  1. 用一句话总结上次的进度(不超过 30 字)\n"
        f"  2. 立刻调 ask_user_question,question 用「想从哪儿继续?」\n"
        f"     options 严格用下面这 {len(options)} 个 label:\n"
        f"{options_md}\n"
        f"调完工具就停,不要再多说话。"
    )


# ─── handler ───────────────────────────────────────────────────────────


async def _get_owned_project(project_id: UUID, ctx: CallContext) -> Project:
    repo = ProjectRepo(ctx.db)
    row = await repo.get_by_id(project_id)
    if row is None:
        raise ProtocolError(
            ErrorCode.PROJECT_NOT_FOUND, f"project {project_id} not found"
        )
    if row.user_id != ctx.user_id:
        raise ProtocolError(
            ErrorCode.FORBIDDEN, f"project {project_id} not yours"
        )
    return row


async def resume_create(
    params: SessionResumeCreateParams, ctx: CallContext
) -> AsyncIterator[AgentEvent]:
    """Create a session + stream the resume turn."""
    project = await _get_owned_project(params.project_id, ctx)
    svc = ProjectService(settings.data_root)

    # 1. Create a fresh session under the project
    sid = generate_session_id()
    store = SessionStore(svc.session_dir(project, sid))
    session_meta = store.create(
        session_id=sid,
        user_id=ctx.user_id,
        project_id=project.id,
        channel=ctx.transport,
        metadata={"created_by": "session.resume_create"},
    )
    session_payload = SessionMeta(
        id=session_meta.id,
        project_id=UUID(session_meta.project_id),
        user_id=UUID(session_meta.user_id),
        channel=session_meta.channel,
        status=session_meta.status,
        started_at=datetime.fromisoformat(session_meta.started_at),
        ended_at=None,
        title=session_meta.title,
        metadata=session_meta.metadata,
    )

    # 2. Tell frontend to switch active session BEFORE the LLM stream
    yield TextDelta(
        text=f"<<session-created>>{session_payload.model_dump_json()}<</session-created>>"
    )  # type: ignore[misc]

    # 3. Run the resume priming turn through the configured TurnRunner
    runner = get_runner()
    if runner is None:
        logger.warning("resume_create_no_runner")
        yield TextDelta(
            text="<<session-error>>turn runner not configured<</session-error>>"
        )  # type: ignore[misc]
        yield TurnEnd(stop_reason="error")  # type: ignore[misc]
        return

    workspace = svc.workspace_path(project)
    progress = _read_progress(workspace)
    priming_text = build_resume_priming(progress)

    agent_session = load_agent_session(store)
    if agent_session is None:
        logger.warning(
            "resume_create_session_load_failed", session_id=session_meta.id
        )
        yield TurnEnd(stop_reason="error")  # type: ignore[misc]
        return

    pre_count = len(agent_session.messages)
    try:
        async for ev in runner.run_turn(
            session=agent_session, user_text=priming_text
        ):
            yield ev  # type: ignore[misc]
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "resume_create_turn_failed",
            session_id=session_meta.id,
            error_type=type(exc).__name__,
            error=str(exc),
            exc_info=True,
        )

    # Persist new messages
    new_messages = agent_session.messages[pre_count:]
    for msg in new_messages:
        store.append_message(msg)


def register(registry: MethodRegistry) -> None:
    registry.register(
        CORE_METHODS["session.resume_create"], resume_create  # type: ignore[arg-type]
    )
