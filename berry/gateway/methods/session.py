"""session.* method handlers.

Read/write all based on SessionStore (filesystem); not via DB.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from uuid import UUID

from berry.config import settings
from berry.core.agent.session_store import SessionStore, generate_session_id
from berry.core.db.models import Project
from berry.core.db.repos.project_repo import ProjectRepo
from berry.core.project.service import ProjectService
from berry.gateway.methods.registry import CallContext, MethodRegistry
from berry.protocol.errors import ErrorCode, ProtocolError
from berry.protocol.methods_core import (
    CORE_METHODS,
    DeletedResult,
    LearningResetParams,
    MessageEnvelope,
    ResetResult,
    SessionCreateParams,
    SessionDeleteParams,
    SessionDetail,
    SessionDetailParams,
    SessionListParams,
    SessionMessagesParams,
    SessionMeta,
)
from berry.protocol.types import Page, SessionSummary


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


def _project_sessions_dir(project: Project) -> Path:
    return ProjectService(settings.data_root).sessions_dir(project)


async def list_sessions(
    params: SessionListParams, ctx: CallContext
) -> Page[SessionSummary]:
    project = await _get_owned_project(params.project_id, ctx)
    sessions_dir = _project_sessions_dir(project)
    if not sessions_dir.exists():
        return Page[SessionSummary](items=[], next_cursor=None)

    items: list[SessionSummary] = []
    for sid_dir in sorted(sessions_dir.iterdir(), reverse=True):
        if not sid_dir.is_dir():
            continue
        store = SessionStore(sid_dir)
        meta = store.read_meta()
        if meta is None:
            continue
        message_count = sum(
            sum(1 for line in p.open(encoding="utf-8") if line.strip())
            for p in store.list_message_files_oldest_first()
        )
        items.append(
            SessionSummary(
                id=meta.id,
                project_id=UUID(meta.project_id),
                user_id=UUID(meta.user_id),
                channel=meta.channel,
                status=meta.status,
                started_at=datetime.fromisoformat(meta.started_at),
                ended_at=(
                    datetime.fromisoformat(meta.ended_at) if meta.ended_at else None
                ),
                title=meta.title,
                message_count=message_count,
                metadata=meta.metadata,
            )
        )
    return Page[SessionSummary](items=items, next_cursor=None)


async def create(
    params: SessionCreateParams, ctx: CallContext
) -> SessionMeta:
    project = await _get_owned_project(params.project_id, ctx)
    sid = generate_session_id()
    svc = ProjectService(settings.data_root)
    store = SessionStore(svc.session_dir(project, sid))
    meta = store.create(
        session_id=sid,
        user_id=ctx.user_id,
        project_id=project.id,
        channel=ctx.transport,
        metadata=params.metadata,
    )
    return SessionMeta(
        id=meta.id,
        project_id=UUID(meta.project_id),
        user_id=UUID(meta.user_id),
        channel=meta.channel,
        status=meta.status,
        started_at=datetime.fromisoformat(meta.started_at),
        ended_at=None,
        title=meta.title,
        metadata=meta.metadata,
    )


async def _find_session_store(
    session_id: str, ctx: CallContext
) -> tuple[SessionStore, Project]:
    """Scan all user projects to find a session_id (MVP simple, slow but works)."""
    repo = ProjectRepo(ctx.db)
    projects = await repo.list_by_user(ctx.user_id)
    svc = ProjectService(settings.data_root)
    for p in projects:
        sd = svc.session_dir(p, session_id)
        if sd.is_dir():
            return SessionStore(sd), p
    raise ProtocolError(
        ErrorCode.SESSION_NOT_FOUND, f"session {session_id} not found"
    )


async def detail(
    params: SessionDetailParams, ctx: CallContext
) -> SessionDetail:
    store, _ = await _find_session_store(params.session_id, ctx)
    meta = store.read_meta()
    if meta is None:
        raise ProtocolError(
            ErrorCode.SESSION_NOT_FOUND, f"session {params.session_id} not found"
        )

    raw = store.load_all_messages()
    recent = raw[-params.message_limit:] if params.message_limit > 0 else raw
    return SessionDetail(
        meta=SessionMeta(
            id=meta.id,
            project_id=UUID(meta.project_id),
            user_id=UUID(meta.user_id),
            channel=meta.channel,
            status=meta.status,
            started_at=datetime.fromisoformat(meta.started_at),
            ended_at=(
                datetime.fromisoformat(meta.ended_at) if meta.ended_at else None
            ),
            title=meta.title,
            metadata=meta.metadata,
        ),
        messages=[
            MessageEnvelope(
                role=env["role"],
                content=env["content"],
                created_at=datetime.fromisoformat(env["created_at"]),
                metadata=env.get("metadata", {}),
            )
            for env in recent
        ],
    )


async def messages(
    params: SessionMessagesParams, ctx: CallContext
) -> Page[MessageEnvelope]:
    store, _ = await _find_session_store(params.session_id, ctx)
    raw = store.load_all_messages()
    page = raw[-params.limit:]
    return Page[MessageEnvelope](
        items=[
            MessageEnvelope(
                role=env["role"],
                content=env["content"],
                created_at=datetime.fromisoformat(env["created_at"]),
                metadata=env.get("metadata", {}),
            )
            for env in page
        ],
        next_cursor=None,
    )


async def delete(
    params: SessionDeleteParams, ctx: CallContext
) -> DeletedResult:
    store, _ = await _find_session_store(params.session_id, ctx)
    if params.hard:
        shutil.rmtree(store.dir, ignore_errors=True)
    else:
        store.update_meta(status="abandoned")
    return DeletedResult(deleted=True)


async def learning_reset(
    params: LearningResetParams, ctx: CallContext
) -> ResetResult:
    """Clear all learning data for a fresh start."""
    project = await _get_owned_project(params.project_id, ctx)
    svc = ProjectService(settings.data_root)
    cleared: list[str] = []

    # 1. Delete all sessions
    sessions_dir = svc.sessions_dir(project)
    if sessions_dir.exists():
        count = len(list(sessions_dir.iterdir()))
        shutil.rmtree(sessions_dir)
        sessions_dir.mkdir(exist_ok=True)
        cleared.append(f"{count} sessions")

    # 2. Clear workspace-level learning files
    ws = svc.workspace_path(project)
    for name in ("INTERVIEW.md", "ROADMAP.md"):
        p = ws / name
        if p.exists():
            p.unlink()
            cleared.append(name)

    modules_dir = ws / "modules"
    if modules_dir.exists():
        shutil.rmtree(modules_dir)
        cleared.append("modules/")

    berry_dir = ws / ".berry"
    if berry_dir.exists():
        shutil.rmtree(berry_dir)
        cleared.append(".berry/")

    # 3. Clear global memory
    memory_dir = settings.data_root / "memory"
    if memory_dir.exists():
        for f in memory_dir.iterdir():
            f.unlink()
        cleared.append("memory")

    # 4. Clear global todos
    todos_path = Path.cwd() / ".berry" / "todos.json"
    if todos_path.exists():
        todos_path.unlink()
        cleared.append("todos")

    return ResetResult(cleared=True, items_cleared=cleared)


def register(registry: MethodRegistry) -> None:
    registry.register(CORE_METHODS["session.list"], list_sessions)  # type: ignore[arg-type]
    registry.register(CORE_METHODS["session.create"], create)  # type: ignore[arg-type]
    registry.register(CORE_METHODS["session.detail"], detail)  # type: ignore[arg-type]
    registry.register(CORE_METHODS["session.messages"], messages)  # type: ignore[arg-type]
    registry.register(CORE_METHODS["session.delete"], delete)  # type: ignore[arg-type]
    registry.register(CORE_METHODS["learning.reset"], learning_reset)  # type: ignore[arg-type]
