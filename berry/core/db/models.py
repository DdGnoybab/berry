"""SQLModel 表定义:users / sessions / messages。

设计原则见 docs/berry-db-schema.md:
- 主键 UUID(gen_random_uuid())
- 时间戳 timestamptz
- 不加 CHECK 约束(Python enum 校验)
- 半结构化字段进 metadata jsonb
"""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlmodel import Field, SQLModel

# 所有 UUID 主键的 SQL 端默认值:让 PG 自己用 pgcrypto 的 gen_random_uuid() 生成
# 这样无论是 ORM、psql、PyCharm Database 还是别的客户端 INSERT,都不用手填 id
_UUID_SERVER_DEFAULT = text("gen_random_uuid()")


def _now_utc() -> datetime:
    """SQLModel 默认值,用 timezone-aware now。

    实际写入数据库的默认值由 server_default=func.now() 兜底,
    这里只是 Python 端的 fallback。
    """
    return datetime.now(timezone.utc)


# ─── User ───────────────────────────────────────────────


class User(SQLModel, table=True):
    __tablename__ = "users"  # type: ignore[assignment]
    __table_args__ = (
        UniqueConstraint("external_source", "external_id", name="uq_users_external"),
    )

    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=_UUID_SERVER_DEFAULT,
        ),
    )
    external_id: str = Field(sa_column=Column(String, nullable=False))
    external_source: str = Field(sa_column=Column(String, nullable=False))
    display_name: str = Field(sa_column=Column(String, nullable=False))

    # 字段名用 metadata_,DB 列名仍叫 metadata(SQLModel 保留字 metadata 不能直接用)
    metadata_: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSONB, nullable=False, server_default="{}"),
    )

    created_at: datetime = Field(
        default_factory=_now_utc,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=func.now()
        ),
    )
    updated_at: datetime = Field(
        default_factory=_now_utc,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
            onupdate=func.now(),  # ORM 层 update 自动更新;PG trigger 后续再加
        ),
    )


# ─── Session ────────────────────────────────────────────


class Session(SQLModel, table=True):
    __tablename__ = "sessions"  # type: ignore[assignment]

    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=_UUID_SERVER_DEFAULT,
        ),
    )
    user_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    channel: str = Field(sa_column=Column(String, nullable=False))
    channel_chat_id: str | None = Field(
        default=None, sa_column=Column(String, nullable=True)
    )
    status: str = Field(
        default="active", sa_column=Column(String, nullable=False, server_default="active")
    )
    title: str | None = Field(default=None, sa_column=Column(String, nullable=True))

    metadata_: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSONB, nullable=False, server_default="{}"),
    )

    created_at: datetime = Field(
        default_factory=_now_utc,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=func.now()
        ),
    )
    updated_at: datetime = Field(
        default_factory=_now_utc,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
            onupdate=func.now(),
        ),
    )


# ─── Message ────────────────────────────────────────────


class Message(SQLModel, table=True):
    __tablename__ = "messages"  # type: ignore[assignment]

    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=_UUID_SERVER_DEFAULT,
        ),
    )
    session_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    role: str = Field(sa_column=Column(String, nullable=False))
    # content holds a JSON list of ContentBlock dicts (see berry/core/llm/types.py).
    # Stored as JSONB; typed as `list` here so SQLModel doesn't infer a stricter shape.
    content: list[Any] = Field(
        sa_column=Column(JSONB, nullable=False),
    )
    metadata_: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSONB, nullable=False, server_default="{}"),
    )
    created_at: datetime = Field(
        default_factory=_now_utc,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=func.now()
        ),
    )


# ─── LlmCallLog ────────────────────────────────────────


class LlmCallLog(SQLModel, table=True):
    """Full audit log of every LLM call: request + response as JSONB.

    Streamed responses are reassembled into a complete LlmResponse before
    being written here (Round 3 in ConversationRuntime).
    """

    __tablename__ = "llm_call_logs"  # type: ignore[assignment]

    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=_UUID_SERVER_DEFAULT,
        ),
    )
    session_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    request: dict[str, Any] = Field(
        sa_column=Column(JSONB, nullable=False),
    )
    response: dict[str, Any] = Field(
        sa_column=Column(JSONB, nullable=False),
    )
    created_at: datetime = Field(
        default_factory=_now_utc,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=func.now()
        ),
    )


# ─── Goal ───────────────────────────────────────────────


class Goal(SQLModel, table=True):
    """A learning goal owned by a user.

    domain="learning" Day-1; "work"/"style"/"diet" added without schema change
    in future rounds (ADR-0003).
    """

    __tablename__ = "goals"  # type: ignore[assignment]

    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=_UUID_SERVER_DEFAULT,
        ),
    )
    user_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    domain: str = Field(
        sa_column=Column(String, nullable=False, server_default="learning"),
    )
    title: str = Field(sa_column=Column(String, nullable=False))
    status: str = Field(
        default="drafting",
        sa_column=Column(String, nullable=False, server_default="drafting"),
    )
    workspace_path: str = Field(sa_column=Column(String, nullable=False))
    current_milestone_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("milestones.id", ondelete="SET NULL", use_alter=True),
            nullable=True,
        ),
    )

    metadata_: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSONB, nullable=False, server_default="{}"),
    )
    created_at: datetime = Field(
        default_factory=_now_utc,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=func.now()
        ),
    )
    updated_at: datetime = Field(
        default_factory=_now_utc,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
            onupdate=func.now(),
        ),
    )


# ─── Milestone ──────────────────────────────────────────


class Milestone(SQLModel, table=True):
    """One step inside a Goal. Ordered by `order_index` (0-based)."""

    __tablename__ = "milestones"  # type: ignore[assignment]
    __table_args__ = (
        UniqueConstraint("goal_id", "order_index", name="uq_milestones_order"),
    )

    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=_UUID_SERVER_DEFAULT,
        ),
    )
    goal_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("goals.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    order_index: int = Field(sa_column=Column(Integer, nullable=False))
    name: str = Field(sa_column=Column(String, nullable=False))
    description: str = Field(sa_column=Column(String, nullable=False))
    status: str = Field(
        default="pending",
        sa_column=Column(String, nullable=False, server_default="pending"),
    )
    passed_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    metadata_: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSONB, nullable=False, server_default="{}"),
    )
    created_at: datetime = Field(
        default_factory=_now_utc,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=func.now()
        ),
    )
    updated_at: datetime = Field(
        default_factory=_now_utc,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
            onupdate=func.now(),
        ),
    )


# ─── Material ───────────────────────────────────────────


class Material(SQLModel, table=True):
    """A .md file backing a Milestone. File system is the source of truth;
    this row is metadata + index. See spec §八.8.3.
    """

    __tablename__ = "materials"  # type: ignore[assignment]
    __table_args__ = (
        UniqueConstraint("milestone_id", "filename", name="uq_materials_filename"),
    )

    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=_UUID_SERVER_DEFAULT,
        ),
    )
    milestone_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("milestones.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    filename: str = Field(sa_column=Column(String, nullable=False))
    source_url: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    source_title: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    summary: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    size_bytes: int = Field(sa_column=Column(Integer, nullable=False, server_default="0"))
    content_hash: str = Field(sa_column=Column(String, nullable=False))

    metadata_: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSONB, nullable=False, server_default="{}"),
    )
    created_at: datetime = Field(
        default_factory=_now_utc,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=func.now()
        ),
    )
    updated_at: datetime = Field(
        default_factory=_now_utc,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
            onupdate=func.now(),
        ),
    )


# ─── Attempt ────────────────────────────────────────────


class Attempt(SQLModel, table=True):
    """One Q+answer+score cycle for a Milestone. See spec §八.8.4."""

    __tablename__ = "attempts"  # type: ignore[assignment]

    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=_UUID_SERVER_DEFAULT,
        ),
    )
    milestone_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("milestones.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    kind: str = Field(sa_column=Column(String, nullable=False))    # "application" | "choice"
    question: str = Field(sa_column=Column(String, nullable=False))

    # choice-specific (null for application)
    choices: list[str] | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )
    correct_index: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=True),
    )

    user_answer: str | None = Field(default=None, sa_column=Column(String, nullable=True))

    # scoring
    score: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    reasoning: str | None = Field(default=None, sa_column=Column(String, nullable=True))
    reference_points: list[str] | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )

    user_decision: str | None = Field(
        default=None,
        sa_column=Column(String, nullable=True),  # "next" | "retry" | "reread" | null
    )

    metadata_: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSONB, nullable=False, server_default="{}"),
    )
    created_at: datetime = Field(
        default_factory=_now_utc,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=func.now()
        ),
    )
