"""upload.* method handlers.

MVP only accepts .md. Stored at <workspace>/uploads/<uuid>.md + .meta.json.
HTTP multipart endpoint (Stage 3) internally translates to upload.create.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from berry.config import settings
from berry.core.db.repos.project_repo import ProjectRepo
from berry.core.project.service import ProjectService
from berry.gateway.methods.registry import CallContext, MethodRegistry
from berry.protocol.errors import ErrorCode, ProtocolError
from berry.protocol.methods_core import (
    CORE_METHODS,
    DeletedResult,
    UploadCreateParams,
    UploadDeleteParams,
    UploadListParams,
)
from berry.protocol.types import Page, UploadInfo

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5MB


async def create(
    params: UploadCreateParams, ctx: CallContext
) -> UploadInfo:
    if not params.filename.lower().endswith(".md"):
        raise ProtocolError(
            ErrorCode.INVALID_FILE_TYPE, "only .md uploads are supported"
        )

    content_bytes = params.content.encode("utf-8")
    if len(content_bytes) > MAX_UPLOAD_BYTES:
        raise ProtocolError(
            ErrorCode.FILE_TOO_LARGE,
            f"upload exceeds {MAX_UPLOAD_BYTES} bytes",
        )

    repo = ProjectRepo(ctx.db)
    project = await repo.get_by_id(params.project_id)
    if project is None or project.user_id != ctx.user_id:
        raise ProtocolError(
            ErrorCode.PROJECT_NOT_FOUND,
            f"project {params.project_id} not found",
        )

    upload_id = uuid4()
    svc = ProjectService(settings.data_root)
    uploads_dir = svc.uploads_dir(project)
    uploads_dir.mkdir(parents=True, exist_ok=True)

    md_path = uploads_dir / f"{upload_id}.md"
    meta_path = uploads_dir / f"{upload_id}.meta.json"

    md_path.write_text(params.content, encoding="utf-8")

    meta = {
        "id": str(upload_id),
        "user_id": str(ctx.user_id),
        "project_id": str(project.id),
        "original_filename": params.filename,
        "storage_path": str(md_path.relative_to(settings.data_root.resolve())),
        "size_bytes": len(content_bytes),
        "content_hash": "sha256:" + hashlib.sha256(content_bytes).hexdigest(),
        "metadata": {},
        "created_at": datetime.now(UTC).isoformat(),
    }
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return UploadInfo(
        id=upload_id,
        user_id=ctx.user_id,
        project_id=project.id,
        filename=params.filename,
        storage_path=meta["storage_path"],
        size_bytes=meta["size_bytes"],
        content_hash=meta["content_hash"],
        metadata={},
        created_at=datetime.fromisoformat(meta["created_at"]),  # type: ignore[arg-type]
    )


async def list_uploads(
    params: UploadListParams, ctx: CallContext
) -> Page[UploadInfo]:
    repo = ProjectRepo(ctx.db)
    project = await repo.get_by_id(params.project_id)
    if project is None or project.user_id != ctx.user_id:
        raise ProtocolError(
            ErrorCode.PROJECT_NOT_FOUND,
            f"project {params.project_id} not found",
        )

    svc = ProjectService(settings.data_root)
    uploads_dir = svc.uploads_dir(project)
    items: list[UploadInfo] = []
    if not uploads_dir.exists():
        return Page[UploadInfo](items=[], next_cursor=None)

    for meta_path in sorted(uploads_dir.glob("*.meta.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        items.append(
            UploadInfo(
                id=UUID(meta["id"]),
                user_id=UUID(meta["user_id"]),
                project_id=UUID(meta["project_id"]),
                filename=meta["original_filename"],
                storage_path=meta["storage_path"],
                size_bytes=meta["size_bytes"],
                content_hash=meta["content_hash"],
                metadata=meta.get("metadata", {}),
                created_at=datetime.fromisoformat(meta["created_at"]),
            )
        )
    return Page[UploadInfo](items=items, next_cursor=None)


async def delete(
    params: UploadDeleteParams, ctx: CallContext
) -> DeletedResult:
    repo = ProjectRepo(ctx.db)
    projects = await repo.list_by_user(ctx.user_id)
    svc = ProjectService(settings.data_root)
    for project in projects:
        uploads_dir = svc.uploads_dir(project)
        md_path = uploads_dir / f"{params.upload_id}.md"
        meta_path = uploads_dir / f"{params.upload_id}.meta.json"
        if md_path.exists() or meta_path.exists():
            md_path.unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)
            return DeletedResult(deleted=True)
    raise ProtocolError(
        ErrorCode.UPLOAD_NOT_FOUND, f"upload {params.upload_id} not found"
    )


def register(registry: MethodRegistry) -> None:
    registry.register(CORE_METHODS["upload.create"], create)  # type: ignore[arg-type]
    registry.register(CORE_METHODS["upload.list"], list_uploads)  # type: ignore[arg-type]
    registry.register(CORE_METHODS["upload.delete"], delete)  # type: ignore[arg-type]
