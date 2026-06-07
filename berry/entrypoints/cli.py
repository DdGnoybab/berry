"""CLI entrypoint — drives ConversationRuntime directly.

Startup sequence:
  1. Load .env / config
  2. Build DB engine + sessionmaker
  3. Seed default user
  4. Get user's project, create one if absent
  5. Build ConversationRuntime (generic — behavior driven by system prompt + skills)
  6. Create a new session
  7. REPL: each input → run_turn → render
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from berry.channels.cli.approval import CliApprovalChannel
from berry.channels.cli.renderer import render
from berry.config import settings
from berry.core.agent.approval import ApprovalChannel
from berry.core.agent.events import AgentEvent
from berry.core.agent.prompt import build_default_system_prompt
from berry.core.agent.runtime import ConversationRuntime
from berry.core.agent.tool_registry import ToolRegistry
from berry.core.db.repos.project_repo import ProjectRepo
from berry.core.db.repos.user_repo import UserRepo
from berry.core.db.session import async_session_factory, engine
from berry.core.llm.adapters.anthropic_messages import AnthropicMessagesAdapter
from berry.core.llm.adapters.base import Adapter
from berry.core.llm.adapters.openai_completions import OpenAICompletionsAdapter
from berry.core.llm.enums import KnownApi
from berry.core.llm.gateway import ModelGateway
from berry.core.llm.registry import ModelRegistry
from berry.core.project.service import ProjectService
from berry.core.tools.core import (
    AskUserQuestionTool,
    BashTool,
    GlobSearchTool,
    GrepSearchTool,
    SkillTool,
    TodoReadTool,
    TodoWriteTool,
)
from berry.core.tools.files import EditFileTool, ReadFileTool, WriteFileTool
from berry.core.tools.memory.read import MemoryReadTool
from berry.core.tools.memory.write import MemoryWriteTool
from berry.core.tools.web.fetch import WebFetchTool
from berry.core.tools.web.registry import SearchProviderRegistry
from berry.core.tools.web.search import WebSearchTool
from berry.gateway.methods import register_core
from berry.gateway.methods.registry import CallContext, MethodRegistry
from berry.gateway.methods.turn import configure_runner
from berry.protocol.errors import ProtocolError
from berry.protocol.methods_core import SessionMeta
from berry.security.permissions import LayeredPolicy

DEFAULT_USER_HANDLE = "default"
DEMO_PROJECT_NAME = "cli-demo"


# ─── Runner construction ────────────────────────────────────


def _build_runtime(
    *,
    approval_channel: ApprovalChannel | None = None,
    cwd_resolver: Callable[[str], Path] | None = None,
) -> tuple[ConversationRuntime, str]:
    """Construct ConversationRuntime + system prompt from config files.

    Args:
        approval_channel: optional override; defaults to ``CliApprovalChannel``.
            Feishu entrypoint passes ``FeishuApprovalChannel`` here so that the
            same business-agnostic runtime can serve both channels.
        cwd_resolver: optional ``session_id -> Path`` callable. Feishu passes
            one (per-user, per-active-topic learning workspaces). CLI omits it,
            falling back to ``Path.cwd()``.

    Returns (runtime, system_prompt) — the CLI passes system_prompt to run_turn
    so ConversationRuntime stays business-agnostic.
    """
    repo_root = Path(__file__).resolve().parent.parent.parent
    models_path = repo_root / "config" / "models.yaml"
    model_registry = ModelRegistry(models_path)
    model_registry.load()
    adapters: dict[str, Adapter] = {
        KnownApi.OPENAI_COMPLETIONS.value: OpenAICompletionsAdapter(),
        KnownApi.ANTHROPIC_MESSAGES.value: AnthropicMessagesAdapter(),
    }
    gateway = ModelGateway(model_registry, adapters)

    search_path = repo_root / "config" / "search.yaml"
    search_registry = SearchProviderRegistry(search_path)
    search_registry.load()

    tool_registry = ToolRegistry(
        [
            BashTool(),
            ReadFileTool(),
            WriteFileTool(),
            EditFileTool(),
            GrepSearchTool(),
            GlobSearchTool(),
            WebSearchTool(search_registry),
            WebFetchTool(),
            TodoWriteTool(),
            TodoReadTool(),
            SkillTool(),
            AskUserQuestionTool(),
            MemoryReadTool(),
            MemoryWriteTool(),
        ]
    )
    policy = LayeredPolicy()
    channel = approval_channel if approval_channel is not None else CliApprovalChannel()

    runtime = ConversationRuntime(
        llm_gateway=gateway,
        tool_registry=tool_registry,
        approval_policy=policy,
        approval_channel=channel,
        db_session_factory=async_session_factory,
        model_id="main",
        cwd_resolver=cwd_resolver,
    )

    system_prompt = build_default_system_prompt(cwd=Path.cwd())

    return runtime, system_prompt


# ─── Thin TurnRunner adapter ─────────────────────────────────────────────────


class _CliTurnRunner:
    """Wraps ConversationRuntime to satisfy TurnRunner Protocol.

    Holds the base system_prompt + an optional ``cwd_resolver`` so we
    can recompute the workspace each turn and augment the prompt with
    learning persona / LEARNER.md / bootstrap when the active project
    is a learning workspace. See ``core/skills/learning_persona.py``.

    The augmentation is per-turn (not per-process) because in the web
    channel one process serves many Projects — Redis vs LangGraph have
    different LEARNER.md contents and Pn one might not be a learning
    project at all.
    """

    def __init__(
        self,
        runtime: ConversationRuntime,
        system_prompt: str,
        *,
        cwd_resolver: Callable[[str], Path] | None = None,
    ) -> None:
        self._runtime = runtime
        self._base_system_prompt = system_prompt
        self._cwd_resolver = cwd_resolver

    def _system_prompt_for(self, session_id: str) -> str:
        if self._cwd_resolver is None:
            return self._base_system_prompt
        from berry.core.skills.learning_persona import augment_system_prompt

        try:
            workspace = self._cwd_resolver(session_id)
        except Exception:  # noqa: BLE001 — resolver should never break a turn
            return self._base_system_prompt
        return augment_system_prompt(self._base_system_prompt, workspace)

    def run_turn(
        self,
        session: Any,
        user_text: str,
    ) -> AsyncIterator[AgentEvent]:
        return self._runtime.run_turn(
            session=session,
            user_text=user_text,
            system_prompt=self._system_prompt_for(session.id),
        )


def _build_skill_invoke_prompt(skill_name: str, args: str = "") -> str:
    """Build a user prompt that instructs the LLM to invoke a skill.

    Mirrors claw-code's approach: the CLI transforms /skill commands into
    prompts that tell the LLM to use the skill tool.
    """
    parts = [f"Use the `skill` tool to load the '{skill_name}' skill and follow its instructions."]
    if args:
        parts.append(f"Context from user: {args}")
    return " ".join(parts)


# ─── Helpers ──────────────────────────────────────────────────────────────────


async def _seed_user() -> UUID:
    async with async_session_factory() as db:
        user = await UserRepo(db).get_or_create_by_handle(
            handle=DEFAULT_USER_HANDLE,
            display_name="Default User",
        )
        return user.id


async def _ensure_demo_project(user_id: UUID) -> UUID:
    async with async_session_factory() as db:
        repo = ProjectRepo(db)
        existing = await repo.get_by_user_and_name(user_id, DEMO_PROJECT_NAME)
        if existing is not None:
            return existing.id

    async with async_session_factory() as db:
        repo = ProjectRepo(db)
        svc = ProjectService(settings.data_root)
        ws_path = svc.workspace_relative_path(user_id, DEMO_PROJECT_NAME)
        project = await repo.create(
            user_id=user_id,
            name=DEMO_PROJECT_NAME,
            title="CLI Demo",
            domain="general",
            workspace_path=ws_path,
        )
        svc.init_workspace(project)
        return project.id


def _make_ctx(
    *, user_id: UUID, project_id: UUID, db: Any
) -> CallContext:
    return CallContext(
        user_id=user_id,
        request_id=f"cli-{datetime.now().isoformat()}",
        transport="cli",
        db=db,
        project_id=project_id,
    )


async def _create_session(
    registry: MethodRegistry, user_id: UUID, project_id: UUID
) -> str:
    async with async_session_factory() as db:
        ctx = _make_ctx(user_id=user_id, project_id=project_id, db=db)
        result = await registry.call(
            "session.create", {"project_id": str(project_id)}, ctx
        )
    assert isinstance(result, SessionMeta)
    return result.id


async def _run_turn(
    registry: MethodRegistry,
    user_id: UUID,
    project_id: UUID,
    session_id: str,
    text: str,
) -> AsyncIterator[AgentEvent]:
    async with async_session_factory() as db:
        ctx = _make_ctx(user_id=user_id, project_id=project_id, db=db)
        async for ev in registry.call_stream(
            "turn.send",
            {"session_id": session_id, "text": text},
            ctx,
        ):
            yield ev  # type: ignore[misc]


async def _async_main() -> None:
    logging.basicConfig(level=logging.WARNING)
    try:
        await _run()
    finally:
        await engine.dispose()


async def _run() -> None:
    user_id = await _seed_user()
    print(f"[demo] user_id     = {user_id}")

    project_id = await _ensure_demo_project(user_id)
    print(f"[demo] project_id  = {project_id}")

    runtime, system_prompt = _build_runtime()
    runner = _CliTurnRunner(runtime, system_prompt)
    configure_runner(runner)  # type: ignore[arg-type]

    registry = MethodRegistry()
    register_core(registry)

    session_id = await _create_session(registry, user_id, project_id)
    print(f"[demo] session_id  = {session_id}")
    print()
    print("berry CLI - 输入消息后回车发送。/quit 退出。")
    print()

    while True:
        try:
            text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            return
        if not text:
            continue
        if text in {"/quit", "/q", "/exit"}:
            print("bye")
            return

        # Slash-command: /learn → invoke learning skill
        if text.startswith("/learn"):
            skill_args = text[len("/learn"):].strip()
            text = _build_skill_invoke_prompt("learning", skill_args)

        try:
            async for ev in _run_turn(
                registry, user_id, project_id, session_id, text
            ):
                render(ev)
        except ProtocolError as exc:
            print(f"\n[error] {exc.code}: {exc.message}\n", flush=True)
        except Exception as exc:
            print(f"\n[runtime error] {type(exc).__name__}: {exc}\n", flush=True)


def main() -> None:
    """Sync entry point."""
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
