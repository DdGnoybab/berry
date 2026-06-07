"""project.* method handlers."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select

from berry.config import settings
from berry.core.db.models import Project
from berry.core.db.repos.project_repo import ProjectRepo
from berry.core.project.progress import compute_progress
from berry.core.project.service import (
    ProjectPathError,
    ProjectService,
    validate_project_name,
)
from berry.gateway.methods.registry import CallContext, MethodRegistry
from berry.protocol.errors import ErrorCode, ProtocolError
from berry.protocol.methods_core import (
    CORE_METHODS,
    DeletedResult,
    ProjectArchiveParams,
    ProjectCreateParams,
    ProjectDeleteParams,
    ProjectDetailParams,
    ProjectListParams,
    ProjectUpdateParams,
)
from berry.protocol.types import Page, ProjectProgressSummary, ProjectSummary


def _row_to_summary(row: Project) -> ProjectSummary:
    progress: ProjectProgressSummary | None = None
    if row.domain == "learning":
        svc = ProjectService(settings.data_root)
        ws = svc.workspace_path(row)
        p = compute_progress(ws)
        progress = ProjectProgressSummary(
            phase=p.phase,
            percent=p.percent,
            done_atoms=p.done_atoms,
            total_atoms=p.total_atoms,
            done_modules=p.done_modules,
            total_modules=p.total_modules,
            current_atom=p.current_atom,
            topic=p.topic,
        )
    return ProjectSummary(
        id=row.id,
        user_id=row.user_id,
        name=row.name,
        title=row.title,
        domain=row.domain,
        workspace_path=row.workspace_path,
        created_at=row.created_at,
        updated_at=row.updated_at,
        metadata=row.metadata_,
        progress=progress,
    )


async def list_projects(
    params: ProjectListParams, ctx: CallContext
) -> Page[ProjectSummary]:
    repo = ProjectRepo(ctx.db)
    rows = await repo.list_by_user(ctx.user_id)
    if params.domain:
        rows = [r for r in rows if r.domain == params.domain]
    return Page[ProjectSummary](
        items=[_row_to_summary(r) for r in rows],
        next_cursor=None,
    )


async def create(
    params: ProjectCreateParams, ctx: CallContext
) -> ProjectSummary:
    try:
        validate_project_name(params.name)
    except ProjectPathError as exc:
        raise ProtocolError(
            ErrorCode.INVALID_INPUT, str(exc)
        ) from exc

    repo = ProjectRepo(ctx.db)
    existing = await repo.get_by_user_and_name(ctx.user_id, params.name)
    if existing is not None:
        raise ProtocolError(
            ErrorCode.PROJECT_NAME_CONFLICT,
            f"project name {params.name!r} already exists for this user",
        )

    svc = ProjectService(settings.data_root)
    workspace_path = svc.workspace_relative_path(ctx.user_id, params.name)

    row = await repo.create(
        user_id=ctx.user_id,
        name=params.name,
        title=params.title,
        domain=params.domain,
        workspace_path=workspace_path,
    )
    svc.init_workspace(row)
    return _row_to_summary(row)


async def detail(
    params: ProjectDetailParams, ctx: CallContext
) -> ProjectSummary:
    row = await _get_owned_project(params.id, ctx)
    return _row_to_summary(row)


async def update(
    params: ProjectUpdateParams, ctx: CallContext
) -> ProjectSummary:
    row = await _get_owned_project(params.id, ctx)
    forbidden = set(params.patch.keys()) - {"title", "metadata"}
    if forbidden:
        raise ProtocolError(
            ErrorCode.INVALID_INPUT,
            f"cannot update fields: {sorted(forbidden)}",
        )
    if "title" in params.patch:
        row.title = str(params.patch["title"])
    if "metadata" in params.patch:
        row.metadata_ = dict(params.patch["metadata"])
    ctx.db.add(row)
    await ctx.db.commit()
    await ctx.db.refresh(row)
    return _row_to_summary(row)


async def archive(
    params: ProjectArchiveParams, ctx: CallContext
) -> ProjectSummary:
    row = await _get_owned_project(params.id, ctx)
    md: dict[str, Any] = dict(row.metadata_)
    md["archived_at"] = datetime.now(UTC).isoformat()
    row.metadata_ = md
    ctx.db.add(row)
    await ctx.db.commit()
    await ctx.db.refresh(row)
    return _row_to_summary(row)


async def delete(
    params: ProjectDeleteParams, ctx: CallContext
) -> DeletedResult:
    row = await _get_owned_project(params.id, ctx)
    if params.hard:
        svc = ProjectService(settings.data_root)
        ws = svc.workspace_path(row)
        await ctx.db.delete(row)
        await ctx.db.commit()
        if ws.exists():
            shutil.rmtree(ws, ignore_errors=True)
    else:
        md: dict[str, Any] = dict(row.metadata_)
        md["archived_at"] = datetime.now(UTC).isoformat()
        row.metadata_ = md
        ctx.db.add(row)
        await ctx.db.commit()
    return DeletedResult(deleted=True)


async def _get_owned_project(project_id: UUID, ctx: CallContext) -> Project:
    result = await ctx.db.execute(
        select(Project).where(Project.id == project_id)  # type: ignore[arg-type]
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise ProtocolError(
            ErrorCode.PROJECT_NOT_FOUND,
            f"project {project_id} not found",
        )
    if row.user_id != ctx.user_id:
        raise ProtocolError(
            ErrorCode.FORBIDDEN,
            f"project {project_id} does not belong to current user",
        )
    return row


def register(registry: MethodRegistry) -> None:
    registry.register(CORE_METHODS["project.list"], list_projects)  # type: ignore[arg-type]
    registry.register(CORE_METHODS["project.create"], create)  # type: ignore[arg-type]
    registry.register(CORE_METHODS["project.detail"], detail)  # type: ignore[arg-type]
    registry.register(CORE_METHODS["project.update"], update)  # type: ignore[arg-type]
    registry.register(CORE_METHODS["project.archive"], archive)  # type: ignore[arg-type]
    registry.register(CORE_METHODS["project.delete"], delete)  # type: ignore[arg-type]
