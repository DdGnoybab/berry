"""SQLModel 表定义:users / projects / llm_call_logs。

设计哲学:DB 是查询索引,不是 source of truth(见 ADR-0004)。
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, SQLModel

# UUID server-side default:让 PG 自己 gen_random_uuid()
_UUID_SERVER_DEFAULT = text("gen_random_uuid()")


def _now_utc() -> datetime:
    """SQLModel 默认值,用 timezone-aware now。"""
    return datetime.now(UTC)


# ─── User ───────────────────────────────────────────────


class User(SQLModel, table=True):
    """身份。MVP 单用户也建一行 (handle='default')。

    handle 替代了之前的 (external_source, external_id) 联合键。
    例:
      - "default"           CLI 默认用户
      - "feishu:ou_xxx"     飞书 open_id
      - "web:user@x.com"    Web 注册用户(未来)
    """

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("handle", name="uq_users_handle"),)

    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=_UUID_SERVER_DEFAULT,
        ),
    )
    handle: str = Field(sa_column=Column(String, nullable=False))
    display_name: str = Field(sa_column=Column(String, nullable=False))
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


# ─── Project ────────────────────────────────────────────


class Project(SQLModel, table=True):
    """用户跟 Berry 协作的一个长期主题。

    元数据在 DB,业务状态(progress / materials / sessions)全在文件系统:
      data/projects/<user_id>/<name>/

    domain 决定哪个 assistant 接手("learning" MVP 唯一实现)。
    """

    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_projects_user_name"),)

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
    name: str = Field(sa_column=Column(String, nullable=False))      # slug
    title: str = Field(sa_column=Column(String, nullable=False))     # 展示名
    domain: str = Field(sa_column=Column(String, nullable=False))    # learning / work / ...
    workspace_path: str = Field(sa_column=Column(String, nullable=False))
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


# ─── LlmCallLog ────────────────────────────────────────


class LlmCallLog(SQLModel, table=True):
    """每次 LLM 调用的完整审计。

    跨 session 聚合(per user / per project / per model)走 SQL。
    """

    __tablename__ = "llm_call_logs"

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
    project_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    session_id: str | None = Field(
        default=None, sa_column=Column(String, nullable=True)
    )  # 文件系统的 session_id 字符串,无 FK
    model: str = Field(sa_column=Column(String, nullable=False))
    request: dict[str, Any] = Field(
        sa_column=Column(JSONB, nullable=False),
    )
    response: dict[str, Any] = Field(
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
