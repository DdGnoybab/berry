"""共享 Pydantic 类型: Page / Cursor / 业务摘要 model.

handler 返回的数据形态都在这里定义, 被 method spec 的 result_schema 引用.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

# ─── 分页 ──────────────────────────────────────────────


class Page[T](BaseModel):
    """通用分页响应."""

    items: list[T]
    next_cursor: str | None = None


# ─── 用户 / 项目 摘要 ──────────────────────────────────


class UserInfo(BaseModel):
    id: UUID
    handle: str
    display_name: str


class ProjectProgressSummary(BaseModel):
    """Derived progress info, computed each call from workspace files."""

    phase: str            # "uninitialized" | "planning" | "learning" | "done"
    percent: int          # 0-100
    done_atoms: int = 0
    total_atoms: int = 0
    done_modules: int = 0
    total_modules: int = 0
    current_atom: str | None = None
    topic: str | None = None


class ProjectSummary(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    title: str
    domain: str
    workspace_path: str
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    progress: ProjectProgressSummary | None = None
    """Learning progress for ``domain == "learning"`` projects.
    None for non-learning projects.
    """


# ─── Session 摘要(从文件读出来, 无 DB) ──────────────


class SessionSummary(BaseModel):
    id: str                            # 文件系统的 session_id 字符串
    project_id: UUID
    user_id: UUID
    channel: str
    status: str                        # active / completed / abandoned
    started_at: datetime
    ended_at: datetime | None = None
    title: str | None = None
    message_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


# ─── Task / Upload / LlmCall ───────────────────────────


class TaskInfo(BaseModel):
    id: UUID
    user_id: UUID
    session_id: str | None = None
    project_id: UUID | None = None
    kind: str
    status: str
    payload: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class UploadInfo(BaseModel):
    id: UUID
    user_id: UUID
    project_id: UUID | None = None
    filename: str
    storage_path: str
    size_bytes: int
    content_hash: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class LlmCallSummary(BaseModel):
    id: UUID
    user_id: UUID
    project_id: UUID | None = None
    session_id: str | None = None
    model: str
    created_at: datetime
