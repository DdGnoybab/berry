"""核心 method 表。

domain-agnostic,所有 domain(learning / work / style)共用。
domain-specific method 由 assistants/<name>/methods.py 自己注册。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from berry.protocol.events import AgentEvent
from berry.protocol.types import (
    LlmCallSummary,
    Page,
    ProjectSummary,
    SessionSummary,
    TaskInfo,
    UploadInfo,
    UserInfo,
)

# ─── MethodSpec ────────────────────────────────────────


class MethodSpec(BaseModel):
    """一个 method 的元信息:名字 + 参数 schema + 返回 schema + 流事件 schema。

    由 registry 用来:
      - 自动校验 params(用 params_schema.model_validate)
      - 生成自描述端点 /v1/methods.json(给前端做 TS 类型生成)
      - 决定一发一回 vs 流式(stream_event_schema 是否 None)
    """

    name: str
    params_schema: type[BaseModel]
    result_schema: type[BaseModel] | None
    stream_event_schema: Any = None  # type[BaseModel] | Annotated union (e.g. AgentEvent)
    description: str
    domain: str = "core"  # "core" / "learning" / "work" / ...

    model_config = {"arbitrary_types_allowed": True}


# ─── system.* ───────────────────────────────────────────


class HealthParams(BaseModel):
    pass


class HealthResult(BaseModel):
    status: str
    version: str


class MeParams(BaseModel):
    pass


class MeResult(BaseModel):
    user: UserInfo


# ─── project.* ──────────────────────────────────────────


class ProjectListParams(BaseModel):
    domain: str | None = None


class ProjectCreateParams(BaseModel):
    name: str = Field(description="slug, lowercase letters/digits/underscore/dash")
    title: str
    domain: str = "learning"


class ProjectDetailParams(BaseModel):
    id: UUID


class ProjectUpdateParams(BaseModel):
    id: UUID
    patch: dict[str, Any]


class ProjectArchiveParams(BaseModel):
    id: UUID


class ProjectDeleteParams(BaseModel):
    id: UUID
    hard: bool = False


class DeletedResult(BaseModel):
    deleted: bool


class ResetResult(BaseModel):
    cleared: bool
    items_cleared: list[str]


# ─── session.* ──────────────────────────────────────────


class SessionListParams(BaseModel):
    project_id: UUID


class SessionCreateParams(BaseModel):
    project_id: UUID
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionMeta(BaseModel):
    id: str
    project_id: UUID
    user_id: UUID
    channel: str
    status: str
    started_at: datetime
    ended_at: datetime | None = None
    title: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionDetailParams(BaseModel):
    session_id: str
    message_limit: int = 50


class MessageEnvelope(BaseModel):
    """messages.jsonl one-line parsed shape."""

    role: str
    content: list[dict[str, Any]]
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionDetail(BaseModel):
    meta: SessionMeta
    messages: list[MessageEnvelope]


class SessionMessagesParams(BaseModel):
    session_id: str
    limit: int = 50
    before: str | None = None


class SessionDeleteParams(BaseModel):
    session_id: str
    hard: bool = False


# ─── turn.* ─────────────────────────────────────────────


class TurnSendParams(BaseModel):
    session_id: str
    text: str


class TurnCancelParams(BaseModel):
    session_id: str
    turn_id: str


class CancelledResult(BaseModel):
    cancelled: bool


# ─── approval.* ─────────────────────────────────────────


class ApprovalRespondParams(BaseModel):
    approval_id: str
    decision: str
    reason: str | None = None


class ApprovalAck(BaseModel):
    accepted: bool


# ─── task.* ─────────────────────────────────────────────


class TaskListParams(BaseModel):
    project_id: UUID
    status: str | None = None


class TaskDetailParams(BaseModel):
    task_id: UUID


class TaskCancelParams(BaseModel):
    task_id: UUID


# ─── upload.* ───────────────────────────────────────────


class UploadCreateParams(BaseModel):
    """Create upload via method call.

    HTTP transport uses multipart endpoint -> internally translates to this method call.
    Stage 1 only implements the method;真正的 multipart 端点 Stage 3 加。
    """

    project_id: UUID
    filename: str
    content: str


class UploadListParams(BaseModel):
    project_id: UUID


class UploadDeleteParams(BaseModel):
    upload_id: UUID


# ─── llm_call.* ─────────────────────────────────────────


class LlmCallListParams(BaseModel):
    project_id: UUID | None = None
    model: str | None = None
    since: datetime | None = None
    limit: int = 50


class LlmCallDetailParams(BaseModel):
    id: UUID


class LlmCallDetail(BaseModel):
    id: UUID
    user_id: UUID
    project_id: UUID | None = None
    session_id: str | None = None
    model: str
    request: dict[str, Any]
    response: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


# ─── learning.* ─────────────────────────────────────────


class LearningResetParams(BaseModel):
    project_id: UUID


# ─── learning.plan_preview / learning.create_project ──────


class PlanAtom(BaseModel):
    """One atomic learning unit inside a module."""

    id: str        # "a1" / "a2" / ...
    name: str


class PlanModule(BaseModel):
    """One module in the proposed learning plan."""

    id: str        # "01-overview" / "02-data-structures" / ...
    name: str
    atoms: list[PlanAtom]


class PlanResult(BaseModel):
    """Output of ``learning.plan_preview`` — the LLM-generated learning plan,
    not yet committed to disk."""

    modules: list[PlanModule]
    interview_md: str


class LearningPlanPreviewParams(BaseModel):
    topic: str = Field(min_length=1, description="What to learn, e.g. 'Redis'.")
    goal: str = Field(
        default="interview",
        description="One of: interview / deep / easy. Drives plan depth.",
    )
    feedback: str | None = Field(
        default=None,
        description=(
            "Optional user feedback for re-generation: e.g. "
            "'我已经会 SDS 了,跳过这块,加一个分布式锁的模块'."
        ),
    )
    previous_plan: PlanResult | None = Field(
        default=None,
        description="Previous plan to adjust from. Null on first try.",
    )


class LearningCreateProjectParams(BaseModel):
    topic: str
    goal: str = "interview"
    plan: PlanResult


class LearningCreateProjectResult(BaseModel):
    project: ProjectSummary
    session: SessionMeta


class SessionResumeCreateParams(BaseModel):
    """Create a new session AND immediately stream a resume turn.

    Different from ``session.create`` (one-shot RPC, no LLM kicked off):
    this RPC commits a fresh session and then streams the LLM's first
    turn — which uses ``ask_user_question`` to offer resume options
    based on the project's current ``progress.json``.
    """

    project_id: UUID


# ─── 核心 method 字典 ──────────────────────────────────


CORE_METHODS: dict[str, MethodSpec] = {
    # system
    "system.health": MethodSpec(
        name="system.health",
        params_schema=HealthParams,
        result_schema=HealthResult,
        description="Health check.",
    ),
    "system.me": MethodSpec(
        name="system.me",
        params_schema=MeParams,
        result_schema=MeResult,
        description="Current user info.",
    ),

    # project
    "project.list": MethodSpec(
        name="project.list",
        params_schema=ProjectListParams,
        result_schema=Page[ProjectSummary],
        description="List my projects, optionally filtered by domain.",
    ),
    "project.create": MethodSpec(
        name="project.create",
        params_schema=ProjectCreateParams,
        result_schema=ProjectSummary,
        description="Create a project. domain decides which assistant handles it.",
    ),
    "project.detail": MethodSpec(
        name="project.detail",
        params_schema=ProjectDetailParams,
        result_schema=ProjectSummary,
        description="Get project detail.",
    ),
    "project.update": MethodSpec(
        name="project.update",
        params_schema=ProjectUpdateParams,
        result_schema=ProjectSummary,
        description="Update project title/metadata. Cannot change name/domain.",
    ),
    "project.archive": MethodSpec(
        name="project.archive",
        params_schema=ProjectArchiveParams,
        result_schema=ProjectSummary,
        description="Archive (soft): set metadata.archived_at.",
    ),
    "project.delete": MethodSpec(
        name="project.delete",
        params_schema=ProjectDeleteParams,
        result_schema=DeletedResult,
        description="Delete (hard=true also wipes workspace dir).",
    ),

    # session
    "session.list": MethodSpec(
        name="session.list",
        params_schema=SessionListParams,
        result_schema=Page[SessionSummary],
        description="List sessions for a project (read from filesystem).",
    ),
    "session.create": MethodSpec(
        name="session.create",
        params_schema=SessionCreateParams,
        result_schema=SessionMeta,
        description="Create a new session (mkdir + meta.json).",
    ),
    "session.detail": MethodSpec(
        name="session.detail",
        params_schema=SessionDetailParams,
        result_schema=SessionDetail,
        description="Session meta + recent messages.",
    ),
    "session.messages": MethodSpec(
        name="session.messages",
        params_schema=SessionMessagesParams,
        result_schema=Page[MessageEnvelope],
        description="Paginated messages from messages.jsonl.",
    ),
    "session.delete": MethodSpec(
        name="session.delete",
        params_schema=SessionDeleteParams,
        result_schema=DeletedResult,
        description="Delete session (hard=true removes session dir).",
    ),

    # turn
    "turn.send": MethodSpec(
        name="turn.send",
        params_schema=TurnSendParams,
        result_schema=None,
        stream_event_schema=AgentEvent,
        description="Send a user message; stream AgentEvents back.",
    ),
    "turn.cancel": MethodSpec(
        name="turn.cancel",
        params_schema=TurnCancelParams,
        result_schema=CancelledResult,
        description="Cancel an in-flight turn.",
    ),

    # approval
    "approval.respond": MethodSpec(
        name="approval.respond",
        params_schema=ApprovalRespondParams,
        result_schema=ApprovalAck,
        description="Respond to a pending approval request.",
    ),

    # task
    "task.list": MethodSpec(
        name="task.list",
        params_schema=TaskListParams,
        result_schema=Page[TaskInfo],
        description="List long-running tasks for a project.",
    ),
    "task.detail": MethodSpec(
        name="task.detail",
        params_schema=TaskDetailParams,
        result_schema=TaskInfo,
        description="Task status detail.",
    ),
    "task.cancel": MethodSpec(
        name="task.cancel",
        params_schema=TaskCancelParams,
        result_schema=TaskInfo,
        description="Cancel a running task.",
    ),

    # upload
    "upload.create": MethodSpec(
        name="upload.create",
        params_schema=UploadCreateParams,
        result_schema=UploadInfo,
        description="Create an upload (MVP: .md only).",
    ),
    "upload.list": MethodSpec(
        name="upload.list",
        params_schema=UploadListParams,
        result_schema=Page[UploadInfo],
        description="List uploads for a project.",
    ),
    "upload.delete": MethodSpec(
        name="upload.delete",
        params_schema=UploadDeleteParams,
        result_schema=DeletedResult,
        description="Delete upload.",
    ),

    # llm_call
    "llm_call.list": MethodSpec(
        name="llm_call.list",
        params_schema=LlmCallListParams,
        result_schema=Page[LlmCallSummary],
        description="List LLM call audit records.",
    ),
    "llm_call.detail": MethodSpec(
        name="llm_call.detail",
        params_schema=LlmCallDetailParams,
        result_schema=LlmCallDetail,
        description="Full request/response for an LLM call.",
    ),

    # learning
    "learning.reset": MethodSpec(
        name="learning.reset",
        params_schema=LearningResetParams,
        result_schema=ResetResult,
        description="Clear all learning data (sessions, memory, todos, progress) for a fresh start.",
    ),
    "learning.plan_preview": MethodSpec(
        name="learning.plan_preview",
        params_schema=LearningPlanPreviewParams,
        result_schema=None,
        stream_event_schema=AgentEvent,
        description=(
            "Stream a learning-plan preview for a topic+goal. "
            "Side-effect-free: uses a sandboxed runtime with WebSearch only, "
            "no file writes. Final assistant message is the JSON plan."
        ),
        domain="learning",
    ),
    "learning.create_project": MethodSpec(
        name="learning.create_project",
        params_schema=LearningCreateProjectParams,
        result_schema=None,
        stream_event_schema=AgentEvent,
        description=(
            "Atomically create a learning Project + workspace files + first "
            "Session from a confirmed plan, then immediately stream the LLM's "
            "first turn (welcome + first ask_user_question). Frontend receives "
            "a synthetic ``<<project-created>>{...}<</project-created>>`` "
            "TextDelta first, then normal turn events."
        ),
        domain="learning",
    ),
    "session.resume_create": MethodSpec(
        name="session.resume_create",
        params_schema=SessionResumeCreateParams,
        result_schema=None,
        stream_event_schema=AgentEvent,
        description=(
            "Create a new session in an existing learning project and "
            "immediately stream a 'resume' turn. Frontend receives a "
            "``<<session-created>>{session}<</session-created>>`` TextDelta "
            "first, then turn events. The LLM emits a single sentence "
            "summarising last position + ask_user_question with options "
            "tailored to the saved progress.json state."
        ),
        domain="learning",
    ),
}
