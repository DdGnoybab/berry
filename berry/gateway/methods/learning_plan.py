"""``learning.plan_preview`` and ``learning.create_project`` handlers.

These two power the new-project flow's "3-step funnel":
  Step 1: user types topic + goal      (frontend only)
  Step 2: learning.plan_preview         (this module, SSE streaming)
  Step 3: learning.create_project       (this module, atomic commit)

Step 2 uses a sandboxed PreviewRuntime (no file write tools) so the
LLM can WebSearch + synthesize a plan without ever touching disk.
The plan is shipped back as the FINAL assistant message JSON.

Step 3 takes the user-confirmed plan and commits everything in one
shot: DB row + workspace files + first Session. Failure leaves no
partial state (best-effort rollback).
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from datetime import datetime
from uuid import UUID

from berry.config import settings
from berry.core.agent.events import (
    TextDelta,
    ToolCallStart,
    ToolResult,
    TurnEnd,
    TurnStart,
)
from berry.core.agent.preview_runtime import build_preview_runtime
from berry.core.agent.session import AgentSession
from berry.core.db.repos.project_repo import ProjectRepo
from berry.core.project.service import (
    ProjectPathError,
    ProjectService,
    validate_project_name,
)
from berry.domain.enums import Channel as ChannelEnum
from berry.domain.enums import SessionStatus
from berry.gateway.methods.registry import CallContext, MethodRegistry
from berry.observability.logging import get_logger
from berry.protocol.errors import ErrorCode, ProtocolError
from berry.protocol.events import AgentEvent
from berry.protocol.methods_core import (
    CORE_METHODS,
    LearningCreateProjectParams,
    LearningCreateProjectResult,
    LearningPlanPreviewParams,
    PlanResult,
    SessionMeta,
)
from berry.protocol.types import ProjectProgressSummary, ProjectSummary

logger = get_logger(__name__)

# Lazy-cached preview runtime (one per process; thread-safe enough for MVP)
_preview_runtime = None
_preview_system_prompt: str | None = None


def _get_preview_runtime():
    global _preview_runtime, _preview_system_prompt
    if _preview_runtime is None:
        _preview_runtime, _preview_system_prompt = build_preview_runtime()
    return _preview_runtime, _preview_system_prompt


# ─── helpers ────────────────────────────────────────────────────────────


def _slug_topic(topic: str) -> str:
    """Convert 'Redis 面试' → 'redis-面试' style, validated against project slug rules.

    Project name rule (service.py:_NAME_RE) is currently ASCII-only:
    ``^[a-z0-9][a-z0-9_-]{0,62}$``. To accept Chinese topics gracefully
    we strip non-ASCII to a transliteration-free fallback ``learning-<ts>``.
    """
    raw = topic.strip().lower()
    raw = re.sub(r"[\s/]+", "-", raw)
    raw = re.sub(r"[^a-z0-9_-]", "", raw)
    if raw and re.match(r"^[a-z0-9]", raw):
        return raw[:63]
    # Fallback when topic is non-ASCII (e.g. pure Chinese); name field
    # is for routing, title carries the human label.
    return f"learning-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


def _build_preview_user_text(params: LearningPlanPreviewParams) -> str:
    """Compose the first user message for the preview turn."""
    parts = [
        f"Topic: {params.topic}",
        f"Goal: {params.goal}",
    ]
    if params.previous_plan:
        parts.append(
            "Previous plan (you generated this earlier; keep / adjust as the "
            "user requested):\n```json\n"
            + json.dumps(params.previous_plan.model_dump(), ensure_ascii=False, indent=2)
            + "\n```"
        )
    if params.feedback:
        parts.append(f"User feedback for adjustment: {params.feedback}")
    # Strong final reminder — the system prompt says it once, but on
    # adjustment turns the LLM tends to slip into prose. Repeat the
    # contract here so it cannot miss it.
    parts.append(
        "FINAL OUTPUT REQUIREMENT (do not skip this):\n"
        "  - You MUST end the turn by emitting EXACTLY one fenced "
        "```json\\n{...}\\n``` block as your final assistant message.\n"
        "  - The JSON object MUST contain keys `modules` (array) and "
        "`interview_md` (string).\n"
        "  - Do NOT respond in prose. Do NOT explain what you did. Just "
        "output the JSON block.\n"
        "  - WebSearch as needed first, then emit the JSON."
    )
    return "\n\n".join(parts)


_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_plan_from_text(text: str) -> PlanResult | None:
    """Pull the final JSON plan out of an assistant message.

    Try fenced ```json {...}``` first; fall back to the first top-level
    {...} block. Returns ``None`` if nothing parseable is found.
    """
    candidates: list[str] = []
    fenced = _JSON_FENCE.findall(text)
    candidates.extend(fenced)
    # bare {...} (greedy from first { to last })
    first = text.find("{")
    last = text.rfind("}")
    if 0 <= first < last:
        candidates.append(text[first : last + 1])

    for cand in candidates:
        try:
            data = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        try:
            return PlanResult.model_validate(data)
        except Exception:  # noqa: BLE001
            continue
    return None


# ─── handler: streaming preview ─────────────────────────────────────────


async def plan_preview(
    params: LearningPlanPreviewParams, ctx: CallContext
) -> AsyncIterator[AgentEvent]:
    """Stream the plan-preview turn.

    Channels render the AgentEvents however they like (web shows tool
    progress; CLI prints). The FINAL assistant text is expected to
    contain a fenced JSON plan; the channel/frontend extracts it.

    We mirror the AgentEvent stream from the runtime AND emit a
    synthetic ``TextDelta`` containing ``<<plan-result>>...JSON...<</plan-result>>``
    if we successfully extracted a plan, so the frontend doesn't need
    its own JSON-parsing logic.
    """
    runtime, system_prompt = _get_preview_runtime()

    # Ephemeral session — no DB row, no file. The marker prefix is
    # purely for logs; the EventBus uses session_id as routing key
    # but no channel subscribes to ``preview-*`` ids on web (the
    # turn_stream_endpoint mirrors all events itself).
    session_id = f"preview-{datetime.now().strftime('%Y%m%dT%H%M%S')}"
    session = AgentSession(
        id=session_id,
        user_id=ctx.user_id,
        channel=ChannelEnum.WEB,
        status=SessionStatus.ACTIVE,
        title=f"plan preview: {params.topic}",
        messages=[],
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    user_text = _build_preview_user_text(params)
    accumulated_text: list[str] = []

    pending_turn_end: TurnEnd | None = None

    async for ev in runtime.run_turn(
        session=session, user_text=user_text, system_prompt=system_prompt
    ):
        if isinstance(ev, TextDelta):
            accumulated_text.append(ev.text)

        # Defer turn_end so we can inject the plan-result/error TextDelta
        # BEFORE it. The frontend uses turn_end as the trigger to scan
        # textBuffer for <<plan-result>>; if we yielded turn_end first,
        # the synthetic TextDelta would arrive too late.
        if isinstance(ev, TurnEnd):
            pending_turn_end = ev
            continue

        yield ev  # type: ignore[misc]

    # turn ended — extract plan from accumulated assistant text and ship
    # the synthetic event(s), then finally the deferred turn_end.
    full = "".join(accumulated_text)
    plan = _extract_plan_from_text(full)
    if plan is None:
        logger.warning(
            "plan_preview_no_json",
            topic=params.topic,
            sample=full[:300],
        )
        yield TextDelta(
            text="\n\n<<plan-error>>could not parse plan JSON<</plan-error>>"
        )  # type: ignore[misc]
    else:
        yield TextDelta(
            text=f"\n\n<<plan-result>>{plan.model_dump_json()}<</plan-result>>"
        )  # type: ignore[misc]

    # Always emit turn_end — even if the LLM stream ended without one
    # (e.g. max inner loops, token limit). The frontend needs turn_end
    # to trigger plan extraction from textBuffer.
    if pending_turn_end is not None:
        yield pending_turn_end  # type: ignore[misc]
    else:
        yield TurnEnd(stop_reason="end_turn")  # type: ignore[misc]


# ─── handler: atomic commit ─────────────────────────────────────────────


def _build_init_priming_message(topic: str, goal: str, plan: PlanResult) -> str:
    """Synthetic 'first user message' for the LLM's init turn.

    Sent silently from the system after a project is created — the user
    hasn't typed anything yet. Tells the LLM to do a brief welcome and
    immediately call ``ask_user_question`` so the user lands on a chat
    that already has buttons, not a blank page.
    """
    first_module = plan.modules[0]
    first_atom = first_module.atoms[0] if first_module.atoms else None
    atom_label = (
        f"{first_module.id} / {first_atom.id} {first_atom.name}"
        if first_atom
        else first_module.id
    )
    return (
        f"我刚选好了学习计划:\n"
        f"- 主题:{topic}\n"
        f"- 目标:{goal}\n"
        f"- 共 {len(plan.modules)} 个模块,{sum(len(m.atoms) for m in plan.modules)} 个 atom\n"
        f"- 第一个 atom:{atom_label}\n\n"
        f"请按 SKILL.md 走第一轮流程:\n"
        f"  1. 用一两句话欢迎我并简单介绍我们要学的方向\n"
        f"  2. 立刻调 `ask_user_question` 让我选下一步\n"
        f"     (建议选项:开始第一题 / 先看看完整路线图 / 调整一下计划)\n"
        f"调完工具就停,不要再多说话。"
    )


async def create_project(
    params: LearningCreateProjectParams, ctx: CallContext
) -> AsyncIterator[AgentEvent]:
    """Atomically create Project + workspace + first Session, then stream
    the LLM's first turn.

    Stream sequence:
      1. ``<<project-created>>{project, session}<</project-created>>`` TextDelta
         — frontend uses this to switch active session before LLM starts.
      2. Normal turn events (turn_start / text_delta / tool_call_start /
         tool_result / suggestion_emitted / turn_end) from the priming
         turn — LLM welcomes + asks first question.

    On commit failure (steps 1-5) we yield a single error TextDelta and
    return — frontend shows the modal error.
    """
    if not params.plan.modules:
        raise ProtocolError(
            ErrorCode.INVALID_INPUT, "plan must have at least one module"
        )

    repo = ProjectRepo(ctx.db)
    svc = ProjectService(settings.data_root)

    # 1. Pick a non-conflicting slug. If user retries with same topic we
    # bump a -2 / -3 suffix.
    base = _slug_topic(params.topic)
    try:
        validate_project_name(base)
    except ProjectPathError as exc:
        raise ProtocolError(ErrorCode.INVALID_INPUT, str(exc)) from exc

    slug = base
    n = 2
    while await repo.get_by_user_and_name(ctx.user_id, slug):
        slug = f"{base}-{n}"
        n += 1

    # 2. DB row
    workspace_rel = svc.workspace_relative_path(ctx.user_id, slug)
    project = await repo.create(
        user_id=ctx.user_id,
        name=slug,
        title=params.topic,
        domain="learning",
        workspace_path=workspace_rel,
    )

    # ── from here on, on any failure, roll back via best-effort cleanup ──
    workspace = svc.workspace_path(project)
    session_meta = None
    first_module = params.plan.modules[0]
    first_atom = first_module.atoms[0] if first_module.atoms else None

    try:
        svc.init_workspace(project)
        logger.info(
            "learning_create_workspace_init",
            project_id=str(project.id),
            workspace=str(workspace),
        )

        # 3. Content files
        learner_md = _render_learner_md(topic=params.topic, goal=params.goal)
        (workspace / "LEARNER.md").write_text(learner_md, encoding="utf-8")

        roadmap_md = _render_roadmap_md(plan=params.plan, topic=params.topic)
        (workspace / "ROADMAP.md").write_text(roadmap_md, encoding="utf-8")

        (workspace / "INTERVIEW.md").write_text(
            params.plan.interview_md, encoding="utf-8"
        )

        # 4. progress.json
        berry_dir = workspace / ".berry"
        berry_dir.mkdir(exist_ok=True)
        progress = {
            "topic": params.topic,
            "goal": params.goal,
            "macro_state": "MODULE_INTRO",
            "current": {
                "module": first_module.id,
                "atom": first_atom.id if first_atom else None,
                "micro_state": "PROBING",
            },
            "modules": {
                m.id: {
                    "name": m.name,
                    "status": "pending",
                    "atoms": {
                        a.id: {"name": a.name, "status": "pending"}
                        for a in m.atoms
                    },
                }
                for m in params.plan.modules
            },
        }
        (berry_dir / "progress.json").write_text(
            json.dumps(progress, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Verify critical files exist before proceeding
        for fname in ("LEARNER.md", "ROADMAP.md", "INTERVIEW.md"):
            fpath = workspace / fname
            if not fpath.exists():
                raise RuntimeError(f"write_text succeeded but {fname} not found at {fpath}")
        if not (berry_dir / "progress.json").exists():
            raise RuntimeError("progress.json not found after write")

        logger.info(
            "learning_create_files_written",
            project_id=str(project.id),
            files=[f.name for f in workspace.iterdir()],
        )

        # 5. First session
        from berry.core.agent.session_store import SessionStore, generate_session_id

        sid = generate_session_id()
        store = SessionStore(svc.session_dir(project, sid))
        session_meta = store.create(
            session_id=sid,
            user_id=ctx.user_id,
            project_id=project.id,
            channel=ctx.transport,
            metadata={"created_by": "learning.create_project"},
        )
        logger.info(
            "learning_create_session",
            session_id=sid,
            meta_exists=(store.dir / "meta.json").exists(),
        )

    except Exception as exc:
        logger.error(
            "learning_create_project_failed_rolling_back",
            project_id=str(project.id),
            error_type=type(exc).__name__,
            error=str(exc),
            exc_info=True,
        )
        import shutil

        try:
            await ctx.db.delete(project)
            await ctx.db.commit()
        except Exception:  # noqa: BLE001
            logger.warning("rollback_db_delete_failed", exc_info=True)
        if workspace.exists():
            shutil.rmtree(workspace, ignore_errors=True)
        # Tell the frontend; the SSE stream then ends.
        yield TextDelta(
            text=f"<<project-error>>create_project failed: "
            f"{type(exc).__name__}: {exc}<</project-error>>"
        )  # type: ignore[misc]
        return

    # ── Commit succeeded. Tell frontend so it switches active session
    # BEFORE the LLM starts streaming, then run the priming turn. ──
    await ctx.db.refresh(project)
    project_summary = ProjectSummary(
        id=project.id,
        user_id=project.user_id,
        name=project.name,
        title=project.title,
        domain=project.domain,
        workspace_path=project.workspace_path,
        created_at=project.created_at,
        updated_at=project.updated_at,
        metadata=project.metadata_,
        progress=ProjectProgressSummary(
            phase="learning",
            percent=0,
            done_atoms=0,
            total_atoms=sum(len(m.atoms) for m in params.plan.modules),
            done_modules=0,
            total_modules=len(params.plan.modules),
            current_atom=(
                f"{first_module.id}/{first_atom.id}" if first_atom else None
            ),
            topic=params.topic,
        ),
    )
    session_summary = SessionMeta(
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
    handoff_payload = LearningCreateProjectResult(
        project=project_summary, session=session_summary
    )
    yield TextDelta(
        text=f"<<project-created>>{handoff_payload.model_dump_json()}<</project-created>>"
    )  # type: ignore[misc]

    # ── Run the priming turn through the configured TurnRunner. The
    # synthetic user message is persisted into the session along with
    # the assistant response so future turns see the original context. ──
    from berry.core.agent.persistence import load_agent_session
    from berry.gateway.methods.turn import get_runner

    runner = get_runner()
    if runner is None:
        logger.warning("create_project_no_runner_configured_skipping_priming")
        return

    from berry.core.agent.session_store import SessionStore

    store = SessionStore(svc.session_dir(project, session_meta.id))
    agent_session = load_agent_session(store)
    if agent_session is None:
        logger.warning(
            "create_project_session_load_failed",
            session_id=session_meta.id,
        )
        return

    priming_text = _build_init_priming_message(
        params.topic, params.goal, params.plan
    )
    pre_count = len(agent_session.messages)
    try:
        async for ev in runner.run_turn(
            session=agent_session, user_text=priming_text
        ):
            yield ev  # type: ignore[misc]
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "create_project_priming_turn_failed",
            session_id=session_meta.id,
            error_type=type(exc).__name__,
            error=str(exc),
            exc_info=True,
        )

    # Persist new messages added by the priming turn (mirrors turn.send).
    new_messages = agent_session.messages[pre_count:]
    for msg in new_messages:
        store.append_message(msg)


# ─── content templates ──────────────────────────────────────────────────


def _render_learner_md(*, topic: str, goal: str) -> str:
    return f"""\
# Learner Profile

> 这份文件由 berry-L 学习助手读取作为 system prompt 的一部分。
> 你可以随时编辑它,下次会话生效。

- topic: {topic}
- goal: {goal}
- language: zh-CN

## 背景
(可选填:你的技术背景。)

## 节奏
(可选填:每次想花多久?多久学一次?)

## 偏好
(可选填:你喜欢什么风格的讲解?有什么红线?)
"""


def _render_roadmap_md(*, plan: PlanResult, topic: str) -> str:
    lines = [f"# {topic} 学习路线图\n"]
    for m in plan.modules:
        lines.append(f"## {m.id} {m.name}\n")
        for a in m.atoms:
            lines.append(f"- {a.id} {a.name}")
        lines.append("")
    return "\n".join(lines)


# ─── registry ───────────────────────────────────────────────────────────


def register(registry: MethodRegistry) -> None:
    registry.register(CORE_METHODS["learning.plan_preview"], plan_preview)  # type: ignore[arg-type]
    registry.register(CORE_METHODS["learning.create_project"], create_project)  # type: ignore[arg-type]
